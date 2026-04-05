"""Auth service — multi-backend authentication aggregator."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from gilbert.config import AuthConfig
from gilbert.interfaces.auth import AuthInfo, AuthProvider, UserContext
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver
from gilbert.interfaces.storage import StorageBackend

logger = logging.getLogger(__name__)

_SESSIONS = "auth_sessions"


class AuthService(Service):
    """Aggregates multiple AuthProviders and manages sessions.

    Capabilities: ``authentication``.
    Requires: ``users``, ``entity_storage``.
    """

    def __init__(self, config: AuthConfig) -> None:
        self._config = config
        self._providers: dict[str, AuthProvider] = {}
        self._storage: StorageBackend | None = None
        self._user_service: Any = None  # UserService, resolved at start

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="auth",
            capabilities=frozenset({"authentication"}),
            requires=frozenset({"users", "entity_storage"}),
            optional=frozenset({"credentials"}),
        )

    async def start(self, resolver: ServiceResolver) -> None:
        # Resolve dependencies.
        self._user_service = resolver.require_capability("users")
        storage_svc = resolver.require_capability("entity_storage")
        self._storage = storage_svc.backend  # type: ignore[attr-defined]

        # Initialize configured providers.
        for prov_cfg in self._config.providers:
            if not prov_cfg.enabled:
                continue
            if prov_cfg.type == "local":
                from gilbert.integrations.local_auth import LocalAuthProvider

                provider = LocalAuthProvider(self._user_service.backend)
                await provider.initialize(prov_cfg.settings)
                self._providers["local"] = provider
                logger.info("Registered auth provider: local")
            else:
                logger.warning(
                    "Unknown built-in auth provider type: %s (use a plugin)",
                    prov_cfg.type,
                )

    async def stop(self) -> None:
        for provider in self._providers.values():
            try:
                await provider.close()
            except Exception:
                logger.exception("Error closing auth provider: %s", provider.provider_type)

    # ---- Provider management ----

    def register_provider(self, provider: AuthProvider) -> None:
        """Register an additional auth provider (for plugins)."""
        self._providers[provider.provider_type] = provider
        logger.info("Registered auth provider: %s", provider.provider_type)

    def list_providers(self) -> list[str]:
        """Return registered provider type names."""
        return sorted(self._providers.keys())

    # ---- Authentication ----

    async def authenticate(
        self, provider_type: str, credentials: dict[str, Any]
    ) -> UserContext | None:
        """Authenticate via a specific provider.

        On success: resolves/creates local user, creates session, returns UserContext.
        On failure: returns None.
        """
        provider = self._providers.get(provider_type)
        if provider is None:
            logger.warning("Auth attempt with unknown provider: %s", provider_type)
            return None

        auth_info = await provider.authenticate(credentials)
        if auth_info is None:
            return None

        # Resolve or create local user.
        user = await self._resolve_local_user(auth_info)
        if user is None:
            return None

        # Update last_login.
        user_id = user["_id"]
        await self._user_service.backend.update_user(
            user_id, {"last_login": datetime.now(UTC).isoformat()}
        )

        # Create session.
        session_id = await self._create_session(user_id, provider_type)

        return UserContext(
            user_id=user_id,
            email=user["email"],
            display_name=user.get("display_name", ""),
            roles=frozenset(user.get("roles", [])),
            provider=provider_type,
            session_id=session_id,
        )

    async def _resolve_local_user(self, auth_info: AuthInfo) -> dict[str, Any] | None:
        """Find or create a local user from auth info."""
        backend = self._user_service.backend

        # 1. Try provider link lookup.
        user = await backend.get_user_by_provider_link(
            auth_info.provider_type, auth_info.provider_user_id
        )
        if user is not None:
            return user

        # 2. Try email lookup (link if found).
        user = await backend.get_user_by_email(auth_info.email)
        if user is not None:
            # Don't link external providers to root.
            if not user.get("is_root", False):
                await self._user_service.add_provider_link(
                    user["_id"], auth_info.provider_type, auth_info.provider_user_id
                )
            return user

        # 3. Create new local user from external provider info.
        import uuid

        user_id = f"usr_{uuid.uuid4().hex[:12]}"
        user = await self._user_service.create_user(
            user_id,
            {
                "email": auth_info.email,
                "display_name": auth_info.display_name,
                "provider_links": [
                    {
                        "provider_type": auth_info.provider_type,
                        "provider_user_id": auth_info.provider_user_id,
                    }
                ],
            },
        )
        logger.info(
            "Created local user %s from %s provider",
            user_id,
            auth_info.provider_type,
        )
        return user

    # ---- Session management ----

    async def _create_session(self, user_id: str, provider: str) -> str:
        """Create a new session and return the session ID."""
        assert self._storage is not None
        session_id = f"sess_{secrets.token_urlsafe(32)}"
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=self._config.session_ttl_seconds)
        await self._storage.put(
            _SESSIONS,
            session_id,
            {
                "user_id": user_id,
                "provider": provider,
                "created_at": now.isoformat(),
                "expires_at": expires.isoformat(),
            },
        )
        return session_id

    async def validate_session(self, session_id: str) -> UserContext | None:
        """Validate a session token and return a UserContext, or None."""
        if not session_id or self._storage is None:
            return None

        session = await self._storage.get(_SESSIONS, session_id)
        if session is None:
            return None

        # Check expiry.
        expires_str = session.get("expires_at", "")
        if expires_str:
            expires = datetime.fromisoformat(expires_str)
            if datetime.now(UTC) > expires:
                await self._storage.delete(_SESSIONS, session_id)
                return None

        # Load user.
        user_id = session.get("user_id", "")
        user = await self._user_service.backend.get_user(user_id)
        if user is None:
            await self._storage.delete(_SESSIONS, session_id)
            return None

        return UserContext(
            user_id=user["_id"],
            email=user["email"],
            display_name=user.get("display_name", ""),
            roles=frozenset(user.get("roles", [])),
            provider=session.get("provider", "local"),
            session_id=session_id,
        )

    async def invalidate_session(self, session_id: str) -> None:
        """Delete a session."""
        if self._storage is not None:
            await self._storage.delete(_SESSIONS, session_id)

    # ---- Provider sync ----

    async def sync_provider(self, provider_type: str) -> int:
        """Sync users from an external provider. Returns count of synced users."""
        provider = self._providers.get(provider_type)
        if provider is None:
            raise KeyError(f"Unknown provider: {provider_type}")

        auth_infos = await provider.sync_users()
        role_mappings = await provider.get_role_mappings()
        backend = self._user_service.backend
        count = 0

        for info in auth_infos:
            # Store remote user entity.
            await backend.put_provider_user(
                info.provider_type,
                info.provider_user_id,
                {
                    "email": info.email,
                    "display_name": info.display_name,
                    "raw": info.raw,
                },
            )

            # Resolve or create local user.
            user = await self._resolve_local_user(info)
            if user is None:
                continue

            # Update provider_users with local_user_id link.
            await backend.put_provider_user(
                info.provider_type,
                info.provider_user_id,
                {
                    "local_user_id": user["_id"],
                    "email": info.email,
                    "display_name": info.display_name,
                    "raw": info.raw,
                },
            )

            # Apply role mappings from external groups.
            if role_mappings and info.raw:
                groups = info.raw.get("groups", [])
                mapped_roles = {
                    role_mappings[g] for g in groups if g in role_mappings
                }
                if mapped_roles:
                    current_roles = await backend.get_roles(user["_id"])
                    await backend.set_roles(user["_id"], current_roles | mapped_roles)

            count += 1

        logger.info("Synced %d users from %s", count, provider_type)
        return count

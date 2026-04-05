"""Auth service — session management and authentication aggregator.

Discovers all ``authentication_provider`` services and delegates
authentication to them. Manages sessions centrally.
"""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from gilbert.config import AuthConfig
from gilbert.interfaces.auth import (
    AuthenticationService,
    AuthInfo,
    LoginMethod,
    UserContext,
)
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver
from gilbert.interfaces.storage import StorageBackend

logger = logging.getLogger(__name__)

_SESSIONS = "auth_sessions"


class AuthService(Service):
    """Central authentication and session management.

    Discovers all services with the ``authentication_provider`` capability,
    provides a unified authentication API, and manages session lifecycle.

    Capabilities: ``authentication``.
    Requires: ``users``, ``entity_storage``.
    """

    def __init__(self, config: AuthConfig) -> None:
        self._config = config
        self._storage: StorageBackend | None = None
        self._user_service: Any = None
        self._resolver: ServiceResolver | None = None

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="auth",
            capabilities=frozenset({"authentication"}),
            requires=frozenset({"users", "entity_storage"}),
            optional=frozenset({"authentication_provider"}),
        )

    async def start(self, resolver: ServiceResolver) -> None:
        self._user_service = resolver.require_capability("users")
        storage_svc = resolver.require_capability("entity_storage")
        self._storage = storage_svc.backend  # type: ignore[attr-defined]
        self._resolver = resolver

        providers = self._get_auth_services()
        logger.info(
            "Auth service started — %d authentication provider(s): %s",
            len(providers),
            ", ".join(p.provider_type for p in providers),
        )

    async def stop(self) -> None:
        pass

    # ---- Provider discovery ----

    def _get_auth_services(self) -> list[AuthenticationService]:
        """Discover all running AuthenticationService instances."""
        if self._resolver is None:
            return []
        result: list[AuthenticationService] = []
        for svc in self._resolver.get_all("authentication_provider"):
            if isinstance(svc, AuthenticationService):
                result.append(svc)
        return result

    def get_login_methods(self) -> list[LoginMethod]:
        """Return login methods from all authentication providers."""
        return [svc.get_login_method() for svc in self._get_auth_services()]

    def get_provider(self, provider_type: str) -> AuthenticationService | None:
        """Get a specific authentication provider by type."""
        for svc in self._get_auth_services():
            if svc.provider_type == provider_type:
                return svc
        return None

    # ---- Authentication ----

    async def authenticate(
        self, provider_type: str, credentials: dict[str, Any]
    ) -> UserContext | None:
        """Authenticate via a specific provider.

        On success: resolves/creates local user, creates session, returns UserContext.
        """
        provider = self.get_provider(provider_type)
        if provider is None:
            logger.warning("Auth attempt with unknown provider: %s", provider_type)
            return None

        auth_info = await provider.authenticate(credentials)
        if auth_info is None:
            return None

        return await self._finalize_auth(auth_info, provider_type)

    async def handle_callback(
        self, provider_type: str, params: dict[str, Any]
    ) -> UserContext | None:
        """Handle an external auth callback (e.g., OAuth redirect)."""
        provider = self.get_provider(provider_type)
        if provider is None:
            logger.warning("Callback for unknown provider: %s", provider_type)
            return None

        auth_info = await provider.handle_callback(params)
        if auth_info is None:
            return None

        return await self._finalize_auth(auth_info, provider_type)

    async def _finalize_auth(
        self, auth_info: AuthInfo, provider_type: str
    ) -> UserContext | None:
        """Resolve local user, update last_login, create session."""
        user = await self._resolve_local_user(auth_info)
        if user is None:
            return None

        user_id = user["_id"]
        await self._user_service.backend.update_user(
            user_id, {"last_login": datetime.now(UTC).isoformat()}
        )

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
            if not user.get("is_root", False):
                await self._user_service.add_provider_link(
                    user["_id"], auth_info.provider_type, auth_info.provider_user_id
                )
            return user

        # 3. Create new local user.
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
        if not session_id or self._storage is None:
            return None

        session = await self._storage.get(_SESSIONS, session_id)
        if session is None:
            return None

        expires_str = session.get("expires_at", "")
        if expires_str:
            expires = datetime.fromisoformat(expires_str)
            if datetime.now(UTC) > expires:
                await self._storage.delete(_SESSIONS, session_id)
                return None

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
        if self._storage is not None:
            await self._storage.delete(_SESSIONS, session_id)

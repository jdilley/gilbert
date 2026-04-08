"""Local authentication — password-based authentication service."""

import logging
from typing import Any

from gilbert.interfaces.auth import (
    AuthenticationService,
    AuthInfo,
    AuthProvider,
    LoginMethod,
)
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver
from gilbert.interfaces.users import UserBackend

logger = logging.getLogger(__name__)


class LocalAuthenticationService(Service, AuthenticationService):
    """Authenticates users against locally stored password hashes.

    Uses argon2id for password hashing and verification.

    Capabilities: ``authentication_provider``.
    Requires: ``users``.
    """

    def __init__(self) -> None:
        self._users: UserBackend | None = None
        self._hasher: Any = None

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="auth_local",
            capabilities=frozenset({"authentication_provider"}),
            requires=frozenset({"users"}),
        )

    async def start(self, resolver: ServiceResolver) -> None:
        user_svc = resolver.require_capability("users")
        self._users = user_svc.backend  # type: ignore[attr-defined]

        from argon2 import PasswordHasher

        self._hasher = PasswordHasher()
        logger.info("Local authentication service started")

    async def stop(self) -> None:
        pass

    # --- AuthenticationService ---

    @property
    def provider_type(self) -> str:
        return "local"

    def get_login_method(self) -> LoginMethod:
        return LoginMethod(
            provider_type="local",
            display_name="Sign In",
            method="form",
            form_action="/auth/login/local",
        )

    async def authenticate(self, credentials: dict[str, Any]) -> AuthInfo | None:
        """Authenticate with username or email plus password.

        Accepts ``{"email": ..., "password": ...}`` where the ``email``
        field can contain either a username or an email address.
        """
        if self._users is None:
            return None

        identifier = credentials.get("email", "")
        password = credentials.get("password", "")
        if not identifier or not password:
            return None

        # Try username first, fall back to email
        user = await self._users.get_user_by_username(identifier)
        if user is None:
            user = await self._users.get_user_by_email(identifier)
        if user is None:
            return None

        stored_hash = user.get("password_hash", "")
        if not stored_hash:
            return None

        if not self._verify_password(stored_hash, password):
            return None

        return AuthInfo(
            provider_type="local",
            provider_user_id=user["_id"],
            email=user.get("email", ""),
            display_name=user.get("display_name", ""),
            roles=frozenset(user.get("roles", [])),
        )

    # --- Utilities ---

    def hash_password(self, password: str) -> str:
        """Hash a plaintext password. Used when creating/updating users."""
        if self._hasher is None:
            from argon2 import PasswordHasher

            self._hasher = PasswordHasher()
        return self._hasher.hash(password)

    def _verify_password(self, stored_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(stored_hash, password)
        except Exception:
            logger.debug("Password verification failed for hash")
            return False


# Keep the old AuthProvider interface for backward compat during transition.
class LocalAuthProvider(AuthProvider):
    """Legacy AuthProvider wrapper. Prefer LocalAuthenticationService."""

    def __init__(self, user_backend: UserBackend) -> None:
        self._users = user_backend
        self._hasher: Any = None

    @property
    def provider_type(self) -> str:
        return "local"

    async def initialize(self, config: dict[str, Any]) -> None:
        from argon2 import PasswordHasher

        self._hasher = PasswordHasher()

    async def close(self) -> None:
        pass

    async def authenticate(self, credentials: dict[str, Any]) -> AuthInfo | None:
        identifier = credentials.get("email", "")
        password = credentials.get("password", "")
        if not identifier or not password:
            return None

        # Try username first, fall back to email
        user = await self._users.get_user_by_username(identifier)
        if user is None:
            user = await self._users.get_user_by_email(identifier)
        if user is None:
            return None

        stored_hash = user.get("password_hash", "")
        if not stored_hash:
            return None

        try:
            if not self._hasher.verify(stored_hash, password):
                return None
        except Exception:
            return None

        return AuthInfo(
            provider_type="local",
            provider_user_id=user["_id"],
            email=user.get("email", ""),
            display_name=user.get("display_name", ""),
            roles=frozenset(user.get("roles", [])),
        )

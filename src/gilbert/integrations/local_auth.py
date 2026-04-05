"""Local authentication provider — password-based authentication."""

import logging
from typing import Any

from gilbert.interfaces.auth import AuthInfo, AuthProvider
from gilbert.interfaces.users import UserBackend

logger = logging.getLogger(__name__)


class LocalAuthProvider(AuthProvider):
    """Authenticates users against locally stored password hashes.

    Uses argon2id for password hashing and verification.
    """

    def __init__(self, user_backend: UserBackend) -> None:
        self._users = user_backend
        self._hasher: Any = None  # PasswordHasher, lazily imported

    @property
    def provider_type(self) -> str:
        return "local"

    async def initialize(self, config: dict[str, Any]) -> None:
        from argon2 import PasswordHasher

        self._hasher = PasswordHasher()

    async def close(self) -> None:
        pass

    async def authenticate(self, credentials: dict[str, Any]) -> AuthInfo | None:
        """Authenticate with ``{"email": ..., "password": ...}``."""
        email = credentials.get("email", "")
        password = credentials.get("password", "")
        if not email or not password:
            return None

        user = await self._users.get_user_by_email(email)
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
            email=user["email"],
            display_name=user.get("display_name", ""),
            roles=frozenset(user.get("roles", [])),
        )

    def hash_password(self, password: str) -> str:
        """Hash a plaintext password. Used when creating/updating users."""
        if self._hasher is None:
            from argon2 import PasswordHasher

            self._hasher = PasswordHasher()
        return self._hasher.hash(password)

    def _verify_password(self, stored_hash: str, password: str) -> bool:
        """Verify a password against a stored hash."""
        try:
            return self._hasher.verify(stored_hash, password)
        except Exception:
            logger.debug("Password verification failed for hash")
            return False

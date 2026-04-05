"""Tests for LocalAuthProvider — password hashing and verification."""

from typing import Any

import pytest

from gilbert.integrations.local_auth import LocalAuthProvider
from gilbert.interfaces.users import UserBackend

# --- Stub user backend ---


class StubUserBackend(UserBackend):
    """In-memory user backend for testing."""

    def __init__(self) -> None:
        self._users: dict[str, dict[str, Any]] = {}

    async def create_user(self, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        entity = {**data, "_id": user_id}
        self._users[user_id] = entity
        return entity

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self._users.get(user_id)

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        for u in self._users.values():
            if u.get("email") == email:
                return u
        return None

    async def get_user_by_provider_link(
        self, provider_type: str, provider_user_id: str
    ) -> dict[str, Any] | None:
        return None

    async def update_user(self, user_id: str, data: dict[str, Any]) -> None:
        if user_id in self._users:
            self._users[user_id].update(data)

    async def delete_user(self, user_id: str) -> None:
        self._users.pop(user_id, None)

    async def list_users(
        self, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        return list(self._users.values())

    async def add_provider_link(
        self, user_id: str, provider_type: str, provider_user_id: str
    ) -> None:
        pass

    async def remove_provider_link(self, user_id: str, provider_type: str) -> None:
        pass

    async def set_roles(self, user_id: str, roles: set[str]) -> None:
        if user_id in self._users:
            self._users[user_id]["roles"] = sorted(roles)

    async def get_roles(self, user_id: str) -> set[str]:
        u = self._users.get(user_id)
        return set(u.get("roles", [])) if u else set()

    async def put_provider_user(
        self, provider_type: str, provider_user_id: str, data: dict[str, Any]
    ) -> None:
        pass

    async def get_provider_user(
        self, provider_type: str, provider_user_id: str
    ) -> dict[str, Any] | None:
        return None

    async def list_provider_users(
        self, provider_type: str, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        return []


# --- Fixtures ---


@pytest.fixture
async def local_auth() -> LocalAuthProvider:
    backend = StubUserBackend()
    provider = LocalAuthProvider(backend)
    await provider.initialize({})

    # Create a test user with a hashed password.
    pw_hash = provider.hash_password("secret123")
    await backend.create_user("u1", {
        "email": "test@example.com",
        "display_name": "Test",
        "password_hash": pw_hash,
        "roles": ["user"],
    })

    return provider


# --- Tests ---


def test_provider_type() -> None:
    provider = LocalAuthProvider(StubUserBackend())
    assert provider.provider_type == "local"


async def test_authenticate_success(local_auth: LocalAuthProvider) -> None:
    info = await local_auth.authenticate({"email": "test@example.com", "password": "secret123"})
    assert info is not None
    assert info.email == "test@example.com"
    assert info.provider_type == "local"
    assert info.provider_user_id == "u1"


async def test_authenticate_wrong_password(local_auth: LocalAuthProvider) -> None:
    info = await local_auth.authenticate({"email": "test@example.com", "password": "wrong"})
    assert info is None


async def test_authenticate_unknown_email(local_auth: LocalAuthProvider) -> None:
    info = await local_auth.authenticate({"email": "nobody@example.com", "password": "secret123"})
    assert info is None


async def test_authenticate_empty_credentials(local_auth: LocalAuthProvider) -> None:
    assert await local_auth.authenticate({}) is None
    assert await local_auth.authenticate({"email": "", "password": ""}) is None


async def test_hash_password_produces_valid_hash(local_auth: LocalAuthProvider) -> None:
    h = local_auth.hash_password("mypassword")
    assert h.startswith("$argon2")

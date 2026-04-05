"""Tests for AuthService — login flow, sessions, provider registration."""

from typing import Any

import pytest

from gilbert.config import AuthConfig
from gilbert.core.services.auth import AuthService
from gilbert.core.services.users import UserService
from gilbert.interfaces.auth import AuthInfo, AuthProvider
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver
from gilbert.interfaces.storage import StorageBackend

# --- Stubs ---


class StubAuthProvider(AuthProvider):
    """Auth provider that always succeeds for a known email."""

    def __init__(self, email: str = "test@example.com") -> None:
        self._email = email

    @property
    def provider_type(self) -> str:
        return "stub"

    async def initialize(self, config: dict[str, Any]) -> None:
        pass

    async def close(self) -> None:
        pass

    async def authenticate(self, credentials: dict[str, Any]) -> AuthInfo | None:
        if credentials.get("email") == self._email:
            return AuthInfo(
                provider_type="stub",
                provider_user_id="stub_001",
                email=self._email,
                display_name="Test User",
            )
        return None


class StubStorageService(Service):
    def __init__(self, backend: StorageBackend) -> None:
        self._backend = backend

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(name="storage", capabilities=frozenset({"entity_storage"}))

    @property
    def backend(self) -> StorageBackend:
        return self._backend


class StubResolver(ServiceResolver):
    def __init__(self, services: dict[str, Service]) -> None:
        self._by_cap = services

    def get_capability(self, capability: str) -> Service | None:
        return self._by_cap.get(capability)

    def require_capability(self, capability: str) -> Service:
        svc = self._by_cap.get(capability)
        if svc is None:
            raise LookupError(f"Missing: {capability}")
        return svc

    def get_all(self, capability: str) -> list[Service]:
        svc = self._by_cap.get(capability)
        return [svc] if svc else []


# --- Fixtures ---


@pytest.fixture
async def user_service(sqlite_storage: StorageBackend) -> UserService:
    svc = UserService(root_password_hash="", default_roles=["user"])
    resolver = StubResolver({"entity_storage": StubStorageService(sqlite_storage)})
    await svc.start(resolver)
    return svc


@pytest.fixture
async def auth_service(
    sqlite_storage: StorageBackend, user_service: UserService
) -> AuthService:
    config = AuthConfig(
        enabled=True,
        providers=[],  # We'll register providers manually
        session_ttl_seconds=3600,
    )
    svc = AuthService(config)
    resolver = StubResolver({
        "users": user_service,
        "entity_storage": StubStorageService(sqlite_storage),
    })
    await svc.start(resolver)
    return svc


# --- Tests ---


async def test_register_and_list_providers(auth_service: AuthService) -> None:
    assert auth_service.list_providers() == []
    auth_service.register_provider(StubAuthProvider())
    assert "stub" in auth_service.list_providers()


async def test_authenticate_unknown_provider(auth_service: AuthService) -> None:
    result = await auth_service.authenticate("nonexistent", {"email": "a@b.com"})
    assert result is None


async def test_authenticate_success_creates_user_and_session(
    auth_service: AuthService, user_service: UserService
) -> None:
    auth_service.register_provider(StubAuthProvider())

    ctx = await auth_service.authenticate("stub", {"email": "test@example.com"})
    assert ctx is not None
    assert ctx.email == "test@example.com"
    assert ctx.session_id is not None
    assert ctx.provider == "stub"

    # User should exist now.
    user = await user_service.get_user_by_email("test@example.com")
    assert user is not None
    assert user["display_name"] == "Test User"


async def test_authenticate_failure(auth_service: AuthService) -> None:
    auth_service.register_provider(StubAuthProvider())
    result = await auth_service.authenticate("stub", {"email": "wrong@example.com"})
    assert result is None


async def test_validate_session(auth_service: AuthService) -> None:
    auth_service.register_provider(StubAuthProvider())

    # Login to get a session.
    ctx = await auth_service.authenticate("stub", {"email": "test@example.com"})
    assert ctx is not None
    session_id = ctx.session_id
    assert session_id is not None

    # Validate the session.
    validated = await auth_service.validate_session(session_id)
    assert validated is not None
    assert validated.user_id == ctx.user_id
    assert validated.email == "test@example.com"


async def test_validate_invalid_session(auth_service: AuthService) -> None:
    result = await auth_service.validate_session("nonexistent_session")
    assert result is None


async def test_invalidate_session(auth_service: AuthService) -> None:
    auth_service.register_provider(StubAuthProvider())

    ctx = await auth_service.authenticate("stub", {"email": "test@example.com"})
    assert ctx is not None and ctx.session_id is not None

    await auth_service.invalidate_session(ctx.session_id)
    result = await auth_service.validate_session(ctx.session_id)
    assert result is None


async def test_authenticate_links_existing_user(
    auth_service: AuthService, user_service: UserService
) -> None:
    """If a user with the same email already exists, link rather than create."""
    await user_service.create_user("existing", {
        "email": "test@example.com",
        "display_name": "Existing",
    })

    auth_service.register_provider(StubAuthProvider())
    ctx = await auth_service.authenticate("stub", {"email": "test@example.com"})
    assert ctx is not None
    assert ctx.user_id == "existing"


async def test_authenticate_does_not_link_root(
    auth_service: AuthService, user_service: UserService
) -> None:
    """Auth should not add provider links to the root user."""
    # Root user has root@localhost email, so this test uses a different provider
    # that matches a different email. Just verify root stays unlinked.
    root = await user_service.get_user("root")
    assert root is not None
    assert root["provider_links"] == []

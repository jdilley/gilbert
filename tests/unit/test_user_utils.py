"""Tests for user identity utilities — resolve_display_name."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from gilbert.core.user_utils import resolve_display_name


class FakeUserBackend:
    def __init__(self, users: dict[str, dict[str, Any]]) -> None:
        self._users = users

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self._users.get(user_id)


class FakeUserService:
    def __init__(self, users: dict[str, dict[str, Any]]) -> None:
        self.backend = FakeUserBackend(users)

    def service_info(self) -> Any:
        from gilbert.interfaces.service import ServiceInfo
        return ServiceInfo(name="users", capabilities=frozenset({"users"}))


class FakeResolver:
    def __init__(self, user_svc: FakeUserService | None = None) -> None:
        self._user_svc = user_svc

    def get_capability(self, cap: str) -> Any:
        if cap == "users":
            return self._user_svc
        return None


# --- Resolution with user service ---


class TestResolveWithUserService:
    @pytest.mark.asyncio
    async def test_resolves_to_first_name(self) -> None:
        resolver = FakeResolver(FakeUserService({
            "usr_abc123": {"display_name": "Brian Dilley", "email": "b@test.com"},
        }))
        name = await resolve_display_name("usr_abc123", resolver)
        assert name == "Brian"

    @pytest.mark.asyncio
    async def test_resolves_full_name_when_requested(self) -> None:
        resolver = FakeResolver(FakeUserService({
            "usr_abc123": {"display_name": "Brian Dilley", "email": "b@test.com"},
        }))
        name = await resolve_display_name("usr_abc123", resolver, first_name_only=False)
        assert name == "Brian Dilley"

    @pytest.mark.asyncio
    async def test_single_name_returns_as_is(self) -> None:
        resolver = FakeResolver(FakeUserService({
            "usr_abc123": {"display_name": "Brian", "email": "b@test.com"},
        }))
        name = await resolve_display_name("usr_abc123", resolver)
        assert name == "Brian"

    @pytest.mark.asyncio
    async def test_empty_display_name_falls_back(self) -> None:
        resolver = FakeResolver(FakeUserService({
            "usr_abc123": {"display_name": "", "email": "b@test.com"},
        }))
        # No display_name → falls back to user_id parsing
        name = await resolve_display_name("usr_abc123", resolver)
        assert name == "usr_abc123"

    @pytest.mark.asyncio
    async def test_user_not_found_falls_back(self) -> None:
        resolver = FakeResolver(FakeUserService({}))
        name = await resolve_display_name("usr_abc123", resolver)
        assert name == "usr_abc123"


# --- Fallback parsing (no user service) ---


class TestFallbackParsing:
    @pytest.mark.asyncio
    async def test_email_style_id_parses_local_part(self) -> None:
        name = await resolve_display_name("brian.dilley@gmail.com", None)
        assert name == "Brian Dilley"

    @pytest.mark.asyncio
    async def test_underscore_email_parses(self) -> None:
        name = await resolve_display_name("john_doe@company.com", None)
        assert name == "John Doe"

    @pytest.mark.asyncio
    async def test_plain_id_returned_as_is(self) -> None:
        name = await resolve_display_name("usr_569171d4c248", None)
        # No @ sign, no space → returned as-is
        assert name == "usr_569171d4c248"

    @pytest.mark.asyncio
    async def test_name_with_space_returns_first(self) -> None:
        name = await resolve_display_name("Brian Dilley", None)
        assert name == "Brian"

    @pytest.mark.asyncio
    async def test_no_resolver_uses_fallback(self) -> None:
        name = await resolve_display_name("brian.dilley@test.com", None)
        assert name == "Brian Dilley"


# --- Edge cases ---


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_resolver_with_no_user_service(self) -> None:
        resolver = FakeResolver(None)
        name = await resolve_display_name("usr_abc", resolver)
        assert name == "usr_abc"

    @pytest.mark.asyncio
    async def test_user_service_raises_exception(self) -> None:
        """If user service throws, falls back gracefully."""
        backend = AsyncMock()
        backend.get_user = AsyncMock(side_effect=RuntimeError("db error"))
        user_svc = MagicMock()
        user_svc.backend = backend
        resolver = MagicMock()
        resolver.get_capability = lambda cap: user_svc if cap == "users" else None

        name = await resolve_display_name("usr_abc", resolver)
        assert name == "usr_abc"

"""Unit tests for the MCPService supervisor loop.

Exercises the connect / backoff / monitor / reconnect state machine
using a fake backend whose ``connect`` / ``list_tools`` behaviors can
be rigged per-test. Supervisor timing is compressed to sub-second
intervals so the whole test class runs in under a second.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from gilbert.core.services.mcp import MCPService
from gilbert.interfaces.mcp import (
    MCPBackend,
    MCPContentBlock,
    MCPServerRecord,
    MCPToolResult,
    MCPToolSpec,
)
from tests.unit.test_mcp_service import FakeACL, FakeStorage


class ProgrammableBackend(MCPBackend):
    """Fake backend whose connect/list_tools outcomes can be programmed.

    Each instance pops from shared ``connect_outcomes`` / ``list_outcomes``
    class-level queues so a test can set up a multi-attempt scenario
    that survives the supervisor creating fresh instances on reconnect.
    """

    backend_name = ""

    connect_outcomes: list[bool] = []
    """``True`` → successful connect, ``False`` → raise ConnectionError."""
    list_outcomes: list[bool] = []
    """``True`` → list_tools returns canned tool, ``False`` → raise."""
    connect_attempts: int = 0
    list_attempts: int = 0

    @classmethod
    def reset(cls) -> None:
        cls.connect_outcomes = []
        cls.list_outcomes = []
        cls.connect_attempts = 0
        cls.list_attempts = 0

    def __init__(self) -> None:
        self.record: MCPServerRecord | None = None
        self.closed: bool = False
        self.tools_changed_cb: Any = None

    async def connect(self, record: MCPServerRecord) -> None:
        type(self).connect_attempts += 1
        ok = self.connect_outcomes.pop(0) if self.connect_outcomes else True
        if not ok:
            raise ConnectionError(f"synthetic failure #{type(self).connect_attempts}")
        self.record = record

    async def close(self) -> None:
        self.closed = True

    async def list_tools(self) -> list[MCPToolSpec]:
        type(self).list_attempts += 1
        ok = self.list_outcomes.pop(0) if self.list_outcomes else True
        if not ok:
            raise ConnectionError(
                f"synthetic list_tools failure #{type(self).list_attempts}",
            )
        return [MCPToolSpec(name="ping", description="", input_schema={})]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        return MCPToolResult(
            content=(MCPContentBlock(type="text", text="ok"),),
        )

    async def set_tools_changed_callback(self, callback: Any) -> None:
        self.tools_changed_cb = callback


@pytest.fixture
def programmable_backend() -> Any:
    original = MCPBackend._registry.get("stdio")
    ProgrammableBackend.reset()
    MCPBackend._registry["stdio"] = ProgrammableBackend
    try:
        yield ProgrammableBackend
    finally:
        ProgrammableBackend.reset()
        if original is not None:
            MCPBackend._registry["stdio"] = original
        else:
            MCPBackend._registry.pop("stdio", None)


def _make_svc(ttl: int = 1) -> MCPService:
    """Build a minimally-wired MCPService with compressed timings."""
    svc = MCPService()
    svc._enabled = True
    svc._storage = FakeStorage()
    svc._acl_svc = FakeACL()
    svc._reconnect_initial_delay = 0.02
    svc._reconnect_max_delay = 0.1
    svc._reconnect_multiplier = 2.0
    svc._reconnect_jitter = 0.0
    svc._connect_timeout = 2.0
    return svc


def _record(id: str = "srv1", ttl: int = 1) -> MCPServerRecord:
    return MCPServerRecord(
        id=id,
        name="Test",
        slug=f"s-{id}",
        transport="stdio",
        command=("true",),
        owner_id="alice",
        tool_cache_ttl_seconds=ttl,
    )


class TestSupervisorConnect:
    @pytest.mark.asyncio
    async def test_successful_connect_sets_connected(
        self,
        programmable_backend: type[ProgrammableBackend],
    ) -> None:
        programmable_backend.connect_outcomes = [True]
        svc = _make_svc()
        record = _record()
        entry = await svc._start_client(record)
        assert entry is not None
        # Wait for the supervisor to finish its first connect.
        for _ in range(40):
            if entry.connected:
                break
            await asyncio.sleep(0.01)
        assert entry.connected is True
        assert entry.retry_count == 0
        assert entry.last_error is None
        await svc._stop_client(record.id)

    @pytest.mark.asyncio
    async def test_reconnect_after_transient_failure(
        self,
        programmable_backend: type[ProgrammableBackend],
    ) -> None:
        """Two failed connects, then success — retry_count climbs then
        resets, and last_error is cleared on the successful attempt."""
        programmable_backend.connect_outcomes = [False, False, True]
        svc = _make_svc()
        record = _record()
        entry = await svc._start_client(record)
        assert entry is not None

        # Wait for eventual success.
        for _ in range(200):
            if entry.connected:
                break
            await asyncio.sleep(0.01)
        assert entry.connected is True, (
            f"supervisor never connected; retry_count={entry.retry_count} "
            f"last_error={entry.last_error}"
        )
        assert entry.retry_count == 0  # reset on success
        assert entry.last_error is None
        assert programmable_backend.connect_attempts >= 3
        await svc._stop_client(record.id)

    @pytest.mark.asyncio
    async def test_backoff_surfaces_retry_state(
        self,
        programmable_backend: type[ProgrammableBackend],
    ) -> None:
        """While connect is failing, retry_count and next_retry_at are
        visible to the serializer before the next attempt fires."""
        # Force indefinite failure.
        programmable_backend.connect_outcomes = [False] * 50
        svc = _make_svc()
        record = _record()
        entry = await svc._start_client(record)
        assert entry is not None

        # Wait until at least one failure has been recorded.
        for _ in range(100):
            if entry.retry_count >= 1:
                break
            await asyncio.sleep(0.01)
        assert entry.retry_count >= 1
        assert entry.next_retry_at is not None
        assert entry.connected is False
        assert "synthetic" in (entry.last_error or "")
        await svc._stop_client(record.id)


class TestSupervisorHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_failure_triggers_reconnect(
        self,
        programmable_backend: type[ProgrammableBackend],
    ) -> None:
        """Connected → list_tools (health check) fails → supervisor
        drops back to reconnect. The second connect succeeds and
        retry_count reflects the transient drop."""
        # Initial connect ok, first list_tools (eager prime) ok,
        # next health check fails, reconnect ok, subsequent list ok.
        programmable_backend.connect_outcomes = [True, True]
        programmable_backend.list_outcomes = [True, False, True]
        svc = _make_svc(ttl=1)  # 1s health-check interval
        record = _record(ttl=1)
        entry = await svc._start_client(record)
        assert entry is not None

        # Wait for initial connect.
        for _ in range(200):
            if entry.connected:
                break
            await asyncio.sleep(0.01)
        assert entry.connected is True

        # Wait for the health check to fail and the reconnect to
        # complete — the backend gets swapped, so check by attempt
        # counter.
        for _ in range(400):
            if programmable_backend.connect_attempts >= 2:
                break
            await asyncio.sleep(0.02)
        assert programmable_backend.connect_attempts >= 2
        # The supervisor should reconnect successfully.
        for _ in range(100):
            if entry.connected:
                break
            await asyncio.sleep(0.02)
        assert entry.connected is True
        await svc._stop_client(record.id)


class TestSupervisorCancellation:
    @pytest.mark.asyncio
    async def test_stop_client_cancels_supervisor_during_backoff(
        self,
        programmable_backend: type[ProgrammableBackend],
    ) -> None:
        """Stopping a client mid-backoff must not raise and must close
        the backend cleanly."""
        programmable_backend.connect_outcomes = [False] * 50
        svc = _make_svc()
        record = _record()
        entry = await svc._start_client(record)
        assert entry is not None

        # Wait for backoff state.
        for _ in range(100):
            if entry.retry_count >= 1:
                break
            await asyncio.sleep(0.01)
        assert entry.retry_count >= 1

        # Stop should complete without error.
        await svc._stop_client(record.id)
        assert record.id not in svc._clients

    @pytest.mark.asyncio
    async def test_stop_while_connected_closes_cleanly(
        self,
        programmable_backend: type[ProgrammableBackend],
    ) -> None:
        programmable_backend.connect_outcomes = [True]
        svc = _make_svc()
        record = _record()
        entry = await svc._start_client(record)
        assert entry is not None
        for _ in range(200):
            if entry.connected:
                break
            await asyncio.sleep(0.01)
        assert entry.connected is True
        await svc._stop_client(record.id)
        assert record.id not in svc._clients


class TestSerializedRetryState:
    @pytest.mark.asyncio
    async def test_retry_state_in_serialized_record(
        self,
        programmable_backend: type[ProgrammableBackend],
    ) -> None:
        from gilbert.interfaces.auth import UserContext

        programmable_backend.connect_outcomes = [False] * 50
        svc = _make_svc()
        record = _record()
        entry = await svc._start_client(record)
        assert entry is not None
        for _ in range(100):
            if entry.retry_count >= 1:
                break
            await asyncio.sleep(0.01)

        alice = UserContext(
            user_id="alice",
            email="a@x",
            display_name="A",
            roles=frozenset({"user"}),
        )
        view = svc._serialize_record(entry.record, alice)
        assert view["retry_count"] >= 1
        assert view["next_retry_at"] is not None
        assert view["connected"] is False
        await svc._stop_client(record.id)

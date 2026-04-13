"""Tests for ServiceManager hot-load (start_service) and hot-unload
(stop_and_unregister) helpers used by runtime plugin install."""

from __future__ import annotations

import pytest

from gilbert.core.service_manager import ServiceManager
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver


class _StubService(Service):
    def __init__(
        self,
        name: str,
        capabilities: frozenset[str] = frozenset(),
        start_error: Exception | None = None,
    ) -> None:
        self._info = ServiceInfo(name=name, capabilities=capabilities)
        self._start_error = start_error
        self.started = False
        self.stopped = False

    def service_info(self) -> ServiceInfo:
        return self._info

    async def start(self, resolver: ServiceResolver) -> None:
        if self._start_error:
            raise self._start_error
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def manager() -> ServiceManager:
    return ServiceManager()


# ── start_service ────────────────────────────────────────────────────


async def test_start_service_starts_a_registered_service(manager: ServiceManager) -> None:
    svc = _StubService("late", capabilities=frozenset({"late_cap"}))
    manager.register(svc)

    await manager.start_service("late")

    assert svc.started
    assert "late" in manager.started_services
    # Capability is now resolvable via the manager.
    assert manager.get_by_capability("late_cap") is svc


async def test_start_service_is_noop_for_already_started(manager: ServiceManager) -> None:
    svc = _StubService("ready", capabilities=frozenset({"ready_cap"}))
    manager.register(svc)
    await manager.start_all()
    svc.started = False  # detect a redundant restart

    await manager.start_service("ready")

    # Should NOT have been re-started.
    assert svc.started is False
    assert manager.started_services.count("ready") == 1


async def test_start_service_unknown_raises(manager: ServiceManager) -> None:
    with pytest.raises(LookupError, match="not found"):
        await manager.start_service("ghost")


async def test_start_service_failure_marks_failed_and_propagates(
    manager: ServiceManager,
) -> None:
    svc = _StubService(
        "broken",
        capabilities=frozenset({"broken_cap"}),
        start_error=RuntimeError("boom"),
    )
    manager.register(svc)

    with pytest.raises(RuntimeError, match="boom"):
        await manager.start_service("broken")

    assert "broken" in manager.failed_services
    assert "broken" not in manager.started_services


# ── stop_and_unregister ──────────────────────────────────────────────


async def test_stop_and_unregister_removes_started_service(
    manager: ServiceManager,
) -> None:
    svc = _StubService("foo", capabilities=frozenset({"foo_cap", "shared_cap"}))
    manager.register(svc)
    await manager.start_all()

    await manager.stop_and_unregister("foo")

    assert svc.stopped
    assert "foo" not in manager.started_services
    assert "foo" not in manager.list_services()
    # Capability index drops empty entries entirely.
    assert "foo_cap" not in manager.list_capabilities()
    assert "shared_cap" not in manager.list_capabilities()


async def test_stop_and_unregister_keeps_other_capability_owners(
    manager: ServiceManager,
) -> None:
    svc_a = _StubService("a", capabilities=frozenset({"shared_cap"}))
    svc_b = _StubService("b", capabilities=frozenset({"shared_cap"}))
    manager.register(svc_a)
    manager.register(svc_b)
    await manager.start_all()

    await manager.stop_and_unregister("a")

    caps = manager.list_capabilities()
    assert "shared_cap" in caps
    assert caps["shared_cap"] == ["b"]
    assert manager.get_by_capability("shared_cap") is svc_b


async def test_stop_and_unregister_unknown_raises(manager: ServiceManager) -> None:
    with pytest.raises(LookupError, match="not found"):
        await manager.stop_and_unregister("ghost")


async def test_stop_and_unregister_handles_unstarted_service(
    manager: ServiceManager,
) -> None:
    svc = _StubService("never-started", capabilities=frozenset({"x"}))
    manager.register(svc)

    await manager.stop_and_unregister("never-started")

    # stop() should not have been called since the service never started.
    assert svc.stopped is False
    assert "never-started" not in manager.list_services()

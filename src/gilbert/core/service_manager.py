"""Service manager — registration, dependency resolution, and lifecycle management."""

import logging
from typing import Any

from gilbert.interfaces.events import Event, EventBus
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver

logger = logging.getLogger(__name__)


class ServiceManager(ServiceResolver):
    """Manages service registration, dependency resolution, startup, and discovery."""

    def __init__(self) -> None:
        self._registered: dict[str, Service] = {}
        self._capabilities: dict[str, list[str]] = {}  # capability -> [service_names]
        self._started: list[str] = []
        self._failed: set[str] = set()
        self._event_bus: EventBus | None = None

    def register(self, service: Service) -> None:
        """Register a service. Must be called before start_all()."""
        info = service.service_info()
        if info.name in self._registered:
            raise ValueError(f"Service already registered: {info.name}")

        self._registered[info.name] = service
        for cap in info.capabilities:
            self._capabilities.setdefault(cap, []).append(info.name)

        logger.info(
            "Service registered: %s (provides: %s)",
            info.name,
            ", ".join(sorted(info.capabilities)) or "none",
        )

    async def start_all(self) -> None:
        """Resolve dependencies and start all services in topological order."""
        remaining = dict(self._registered)
        started_caps: set[str] = set()

        while remaining:
            # Find services whose requires are all satisfied
            ready = [
                name
                for name, svc in remaining.items()
                if svc.service_info().requires <= started_caps
            ]

            if not ready:
                # Everything left has unsatisfied dependencies
                for name, svc in remaining.items():
                    missing = svc.service_info().requires - started_caps
                    logger.error(
                        "Service %s cannot start: missing required capabilities: %s",
                        name,
                        ", ".join(sorted(missing)),
                    )
                    self._failed.add(name)
                break

            for name in ready:
                svc = remaining.pop(name)
                info = svc.service_info()
                try:
                    await svc.start(self)
                    self._started.append(name)
                    started_caps |= info.capabilities
                    logger.info("Service started: %s", name)
                    await self._publish_event("service.started", name, info)
                except Exception:
                    logger.exception("Service %s failed to start", name)
                    self._failed.add(name)
                    await self._publish_event("service.failed", name, info)

        total = len(self._started)
        failed = len(self._failed)
        logger.info(
            "Service startup complete: %d started, %d failed", total, failed
        )

    async def stop_all(self) -> None:
        """Stop all started services in reverse order."""
        for name in reversed(self._started):
            svc = self._registered.get(name)
            if svc is None:
                continue
            try:
                await svc.stop()
                logger.info("Service stopped: %s", name)
            except Exception:
                logger.exception("Error stopping service: %s", name)
        self._started.clear()

    def set_event_bus(self, bus: EventBus) -> None:
        """Set the event bus for publishing lifecycle events."""
        self._event_bus = bus

    # --- Discovery API ---

    def get_service(self, name: str) -> Service | None:
        """Get a service by name (only if started)."""
        if name in self._started:
            return self._registered.get(name)
        return None

    def get_by_capability(self, capability: str) -> Service | None:
        """Get the first started service providing a capability."""
        for name in self._capabilities.get(capability, []):
            if name in self._started:
                return self._registered[name]
        return None

    def get_all_by_capability(self, capability: str) -> list[Service]:
        """Get all started services providing a capability."""
        return [
            self._registered[name]
            for name in self._capabilities.get(capability, [])
            if name in self._started
        ]

    def list_capabilities(self) -> dict[str, list[str]]:
        """List all registered capabilities and their providing service names."""
        return {cap: list(names) for cap, names in self._capabilities.items()}

    @property
    def started_services(self) -> list[str]:
        """Names of all successfully started services."""
        return list(self._started)

    @property
    def failed_services(self) -> set[str]:
        """Names of all services that failed to start."""
        return set(self._failed)

    # --- ServiceResolver implementation ---

    def get_capability(self, capability: str) -> Service | None:
        return self.get_by_capability(capability)

    def require_capability(self, capability: str) -> Service:
        svc = self.get_by_capability(capability)
        if svc is None:
            raise LookupError(f"No started service provides capability: {capability}")
        return svc

    def get_all(self, capability: str) -> list[Service]:
        return self.get_all_by_capability(capability)

    # --- Internal ---

    async def _publish_event(self, event_type: str, name: str, info: ServiceInfo) -> None:
        if self._event_bus is None:
            return
        try:
            await self._event_bus.publish(Event(
                event_type=event_type,
                data={
                    "service": name,
                    "capabilities": sorted(info.capabilities),
                },
                source=name,
            ))
        except Exception:
            logger.debug("Failed to publish service event: %s", event_type)

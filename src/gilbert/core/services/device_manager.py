"""Device manager service — wraps DeviceManager as a discoverable service."""

import logging

from gilbert.core.device_manager import DeviceManager
from gilbert.core.services.event_bus import EventBusService
from gilbert.core.services.storage import StorageService
from gilbert.interfaces.devices import DeviceProvider
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver

logger = logging.getLogger(__name__)


class DeviceManagerService(Service):
    """Provides device management capabilities. Requires storage and event bus."""

    def __init__(self) -> None:
        self._manager: DeviceManager | None = None

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="device_manager",
            capabilities=frozenset({"device_management", "device_registry"}),
            requires=frozenset({"document_storage", "event_bus"}),
        )

    async def start(self, resolver: ServiceResolver) -> None:
        storage_svc = resolver.require_capability("document_storage")
        bus_svc = resolver.require_capability("event_bus")

        assert isinstance(storage_svc, StorageService)
        assert isinstance(bus_svc, EventBusService)

        self._manager = DeviceManager(storage_svc.backend, bus_svc.bus)

    @property
    def manager(self) -> DeviceManager:
        if self._manager is None:
            raise RuntimeError("DeviceManagerService not started")
        return self._manager

    async def discover_providers(self, resolver: ServiceResolver) -> None:
        """Pull devices from all started DeviceProvider services."""
        for svc in resolver.get_all("device_provider"):
            if isinstance(svc, DeviceProvider):
                try:
                    devices = await svc.discover_devices()
                    for device in devices:
                        await self.manager.add_device(device, svc.provider_name)
                    logger.info(
                        "Discovered %d devices from %s", len(devices), svc.provider_name
                    )
                except Exception:
                    logger.exception(
                        "Failed to discover devices from %s", svc.provider_name
                    )

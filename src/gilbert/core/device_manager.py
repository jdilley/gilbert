"""Device manager — central registry of active devices."""

import logging
from typing import Any

from gilbert.interfaces.devices import Device, DeviceType
from gilbert.interfaces.events import Event, EventBus
from gilbert.interfaces.storage import StorageBackend

logger = logging.getLogger(__name__)


class DeviceManager:
    """Central registry of active devices. Facade over integrations and storage."""

    def __init__(self, storage: StorageBackend, event_bus: EventBus) -> None:
        self._devices: dict[str, Device] = {}
        self._storage = storage
        self._event_bus = event_bus

    async def add_device(self, device: Device, provider: str) -> None:
        """Register a discovered device."""
        self._devices[device.device_id] = device
        await self._storage.put("devices", device.device_id, {
            "device_type": device.device_type.value,
            "name": device.name,
            "provider": provider,
            "attributes": device.attributes,
        })
        logger.info(
            "Device added: %s (%s) via %s", device.name, device.device_id, provider
        )
        await self._event_bus.publish(Event(
            event_type="device.added",
            data={"device_id": device.device_id, "type": device.device_type.value},
            source=device.device_id,
        ))

    async def remove_device(self, device_id: str) -> None:
        """Remove a device from the registry."""
        device = self._devices.pop(device_id, None)
        await self._storage.delete("devices", device_id)
        if device:
            logger.info("Device removed: %s (%s)", device.name, device_id)
            await self._event_bus.publish(Event(
                event_type="device.removed",
                data={"device_id": device_id},
                source=device_id,
            ))

    def get_device(self, device_id: str) -> Device | None:
        """Get a device by ID."""
        return self._devices.get(device_id)

    def get_devices_by_type(self, device_type: DeviceType) -> list[Device]:
        """Get all devices of a given type."""
        return [d for d in self._devices.values() if d.device_type == device_type]

    def all_devices(self) -> list[Device]:
        """Get all registered devices."""
        return list(self._devices.values())

    async def refresh_device(self, device_id: str) -> None:
        """Refresh a device's state from hardware and publish changes."""
        device = self._devices.get(device_id)
        if device is None:
            raise KeyError(f"Device not found: {device_id}")

        old_attrs = dict(device.attributes)
        await device.refresh()
        new_attrs = device.attributes

        if new_attrs != old_attrs:
            logger.debug("Device state changed: %s", device_id)
            await self._storage.put("device_states", device_id, new_attrs)
            await self._event_bus.publish(Event(
                event_type="device.state_changed",
                source=device_id,
                data={"old": old_attrs, "new": new_attrs},
            ))

    async def refresh_all(self) -> None:
        """Refresh all devices."""
        for device_id in list(self._devices.keys()):
            try:
                await self.refresh_device(device_id)
            except Exception:
                logger.exception("Failed to refresh device: %s", device_id)

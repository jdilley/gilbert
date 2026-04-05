"""Tests for DeviceProvider discovery via DeviceManagerService."""

from typing import Any
from unittest.mock import AsyncMock, PropertyMock

import pytest

from gilbert.core.device_manager import DeviceManager
from gilbert.core.services.device_manager import DeviceManagerService
from gilbert.interfaces.devices import Device, DeviceProvider, DeviceState, DeviceType
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver


def _make_mock_device(
    device_id: str = "light-1",
    name: str = "Test Light",
    device_type: DeviceType = DeviceType.LIGHT,
) -> AsyncMock:
    device = AsyncMock(spec=Device)
    type(device).device_id = PropertyMock(return_value=device_id)
    type(device).name = PropertyMock(return_value=name)
    type(device).device_type = PropertyMock(return_value=device_type)
    type(device).state = PropertyMock(return_value=DeviceState.ONLINE)
    type(device).attributes = PropertyMock(return_value={"is_on": True})
    return device


class StubDeviceProviderService(Service):
    """A service that also provides devices."""

    def __init__(self, name: str, devices: list[Device]) -> None:
        self._name = name
        self._devices = devices

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name=self._name,
            capabilities=frozenset({"device_provider"}),
        )

    @property
    def provider_name(self) -> str:
        return self._name

    async def discover_devices(self) -> list[Device]:
        return list(self._devices)


class FailingProviderService(Service):
    """A device provider that raises during discovery."""

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="failing",
            capabilities=frozenset({"device_provider"}),
        )

    @property
    def provider_name(self) -> str:
        return "failing"

    async def discover_devices(self) -> list[Device]:
        raise ConnectionError("cannot connect")


def test_stub_provider_implements_protocol() -> None:
    """Verify our stub satisfies the DeviceProvider protocol."""
    provider = StubDeviceProviderService("test", [])
    assert isinstance(provider, DeviceProvider)


async def test_discover_providers_adds_devices() -> None:
    light = _make_mock_device("light-1", "Living Room Light")
    lock = _make_mock_device("lock-1", "Front Door", DeviceType.LOCK)

    provider = StubDeviceProviderService("lutron", [light, lock])

    resolver = AsyncMock(spec=ServiceResolver)
    resolver.get_all.return_value = [provider]

    dm_svc = DeviceManagerService()
    # Manually set up the manager with mocks
    storage = AsyncMock()
    event_bus = AsyncMock()
    dm_svc._manager = DeviceManager(storage, event_bus)

    await dm_svc.discover_providers(resolver)

    resolver.get_all.assert_called_once_with("device_provider")
    assert dm_svc.manager.get_device("light-1") is light
    assert dm_svc.manager.get_device("lock-1") is lock
    assert len(dm_svc.manager.all_devices()) == 2


async def test_discover_providers_multiple_providers() -> None:
    light = _make_mock_device("light-1", "Light")
    sensor = _make_mock_device("sensor-1", "Motion", DeviceType.SENSOR)

    provider_a = StubDeviceProviderService("lutron", [light])
    provider_b = StubDeviceProviderService("unifi", [sensor])

    resolver = AsyncMock(spec=ServiceResolver)
    resolver.get_all.return_value = [provider_a, provider_b]

    dm_svc = DeviceManagerService()
    dm_svc._manager = DeviceManager(AsyncMock(), AsyncMock())

    await dm_svc.discover_providers(resolver)

    assert len(dm_svc.manager.all_devices()) == 2


async def test_discover_providers_continues_on_error() -> None:
    """One failing provider should not prevent others from being discovered."""
    light = _make_mock_device("light-1", "Light")

    failing = FailingProviderService()
    working = StubDeviceProviderService("lutron", [light])

    resolver = AsyncMock(spec=ServiceResolver)
    resolver.get_all.return_value = [failing, working]

    dm_svc = DeviceManagerService()
    dm_svc._manager = DeviceManager(AsyncMock(), AsyncMock())

    await dm_svc.discover_providers(resolver)

    # The working provider's device should still be registered
    assert dm_svc.manager.get_device("light-1") is light


async def test_discover_providers_no_providers() -> None:
    resolver = AsyncMock(spec=ServiceResolver)
    resolver.get_all.return_value = []

    dm_svc = DeviceManagerService()
    dm_svc._manager = DeviceManager(AsyncMock(), AsyncMock())

    await dm_svc.discover_providers(resolver)

    assert dm_svc.manager.all_devices() == []


async def test_discover_providers_stores_provider_name() -> None:
    light = _make_mock_device("light-1", "Light")
    provider = StubDeviceProviderService("lutron", [light])

    resolver = AsyncMock(spec=ServiceResolver)
    resolver.get_all.return_value = [provider]

    storage = AsyncMock()
    dm_svc = DeviceManagerService()
    dm_svc._manager = DeviceManager(storage, AsyncMock())

    await dm_svc.discover_providers(resolver)

    # Verify storage was called with provider name
    storage.put.assert_called_once()
    stored_data = storage.put.call_args[0][2]
    assert stored_data["provider"] == "lutron"

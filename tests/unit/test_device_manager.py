"""Tests for DeviceManager — uses mocks for storage and event bus."""

from typing import Any
from unittest.mock import AsyncMock, PropertyMock

import pytest

from gilbert.core.device_manager import DeviceManager
from gilbert.interfaces.devices import Device, DeviceState, DeviceType
from gilbert.interfaces.events import Event


def _make_mock_device(
    device_id: str = "light-1",
    name: str = "Test Light",
    device_type: DeviceType = DeviceType.LIGHT,
    state: DeviceState = DeviceState.ONLINE,
    attributes: dict[str, Any] | None = None,
) -> AsyncMock:
    """Create a mock Device."""
    device = AsyncMock(spec=Device)
    type(device).device_id = PropertyMock(return_value=device_id)
    type(device).name = PropertyMock(return_value=name)
    type(device).device_type = PropertyMock(return_value=device_type)
    type(device).state = PropertyMock(return_value=state)
    type(device).attributes = PropertyMock(return_value=attributes or {"is_on": True})
    return device


@pytest.fixture
def storage() -> AsyncMock:
    mock = AsyncMock()
    return mock


@pytest.fixture
def event_bus() -> AsyncMock:
    mock = AsyncMock()
    return mock


@pytest.fixture
def manager(storage: AsyncMock, event_bus: AsyncMock) -> DeviceManager:
    return DeviceManager(storage, event_bus)


async def test_add_device(manager: DeviceManager, storage: AsyncMock, event_bus: AsyncMock) -> None:
    device = _make_mock_device()
    await manager.add_device(device, "lutron")

    assert manager.get_device("light-1") is device
    storage.put.assert_called_once()
    event_bus.publish.assert_called_once()
    event: Event = event_bus.publish.call_args[0][0]
    assert event.event_type == "device.added"
    assert event.data["device_id"] == "light-1"


async def test_remove_device(manager: DeviceManager, storage: AsyncMock, event_bus: AsyncMock) -> None:
    device = _make_mock_device()
    await manager.add_device(device, "lutron")
    event_bus.reset_mock()

    await manager.remove_device("light-1")

    assert manager.get_device("light-1") is None
    storage.delete.assert_called_once_with("devices", "light-1")
    event_bus.publish.assert_called_once()
    event: Event = event_bus.publish.call_args[0][0]
    assert event.event_type == "device.removed"


async def test_remove_nonexistent_device(manager: DeviceManager, event_bus: AsyncMock) -> None:
    await manager.remove_device("nonexistent")
    event_bus.publish.assert_not_called()


async def test_get_device(manager: DeviceManager) -> None:
    assert manager.get_device("light-1") is None

    device = _make_mock_device()
    await manager.add_device(device, "lutron")
    assert manager.get_device("light-1") is device


async def test_get_devices_by_type(manager: DeviceManager) -> None:
    light = _make_mock_device("light-1", "Light", DeviceType.LIGHT)
    thermo = _make_mock_device("thermo-1", "Thermostat", DeviceType.THERMOSTAT)
    await manager.add_device(light, "lutron")
    await manager.add_device(thermo, "nest")

    lights = manager.get_devices_by_type(DeviceType.LIGHT)
    assert len(lights) == 1
    assert lights[0].device_id == "light-1"

    thermostats = manager.get_devices_by_type(DeviceType.THERMOSTAT)
    assert len(thermostats) == 1


async def test_all_devices(manager: DeviceManager) -> None:
    assert manager.all_devices() == []

    light = _make_mock_device("light-1")
    thermo = _make_mock_device("thermo-1", device_type=DeviceType.THERMOSTAT)
    await manager.add_device(light, "lutron")
    await manager.add_device(thermo, "nest")

    assert len(manager.all_devices()) == 2


async def test_refresh_device_publishes_on_change(
    manager: DeviceManager, storage: AsyncMock, event_bus: AsyncMock
) -> None:
    # Start with is_on=True, after refresh it changes to is_on=False
    attrs = {"is_on": True}
    device = _make_mock_device(attributes=attrs)

    async def simulate_state_change() -> None:
        # Simulate hardware changing state during refresh
        type(device).attributes = PropertyMock(return_value={"is_on": False})

    device.refresh.side_effect = simulate_state_change
    await manager.add_device(device, "lutron")
    event_bus.reset_mock()
    storage.reset_mock()

    await manager.refresh_device("light-1")

    event_bus.publish.assert_called_once()
    event: Event = event_bus.publish.call_args[0][0]
    assert event.event_type == "device.state_changed"
    assert event.data["old"] == {"is_on": True}
    assert event.data["new"] == {"is_on": False}


async def test_refresh_device_no_change_no_event(
    manager: DeviceManager, event_bus: AsyncMock
) -> None:
    device = _make_mock_device(attributes={"is_on": True})
    await manager.add_device(device, "lutron")
    event_bus.reset_mock()

    await manager.refresh_device("light-1")
    event_bus.publish.assert_not_called()


async def test_refresh_device_not_found(manager: DeviceManager) -> None:
    with pytest.raises(KeyError, match="Device not found"):
        await manager.refresh_device("nonexistent")


async def test_refresh_all(manager: DeviceManager) -> None:
    d1 = _make_mock_device("d1")
    d2 = _make_mock_device("d2")
    await manager.add_device(d1, "a")
    await manager.add_device(d2, "b")

    await manager.refresh_all()
    d1.refresh.assert_called_once()
    d2.refresh.assert_called_once()


async def test_refresh_all_continues_on_error(manager: DeviceManager) -> None:
    d1 = _make_mock_device("d1")
    d2 = _make_mock_device("d2")
    d1.refresh.side_effect = ConnectionError("timeout")
    await manager.add_device(d1, "a")
    await manager.add_device(d2, "b")

    await manager.refresh_all()  # should not raise
    d2.refresh.assert_called_once()

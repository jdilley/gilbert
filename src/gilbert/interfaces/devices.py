"""Device interface hierarchy — ABCs for all controllable device types."""

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class DeviceType(StrEnum):
    LIGHT = "light"
    THERMOSTAT = "thermostat"
    LOCK = "lock"
    SPEAKER = "speaker"
    DISPLAY = "display"
    SWITCH = "switch"
    SENSOR = "sensor"


class DeviceState(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"
    ERROR = "error"


class Device(ABC):
    """Base interface for all controllable devices."""

    @property
    @abstractmethod
    def device_id(self) -> str: ...

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def device_type(self) -> DeviceType: ...

    @property
    @abstractmethod
    def state(self) -> DeviceState: ...

    @property
    @abstractmethod
    def attributes(self) -> dict[str, Any]: ...

    @abstractmethod
    async def refresh(self) -> None:
        """Poll the device for current state."""
        ...

    @abstractmethod
    async def execute_command(self, command: str, **kwargs: Any) -> None:
        """Generic command dispatch for device-specific commands."""
        ...


class Light(Device):
    """A light that can be turned on/off and optionally dimmed/colored."""

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.LIGHT

    @property
    @abstractmethod
    def is_on(self) -> bool: ...

    @property
    @abstractmethod
    def brightness(self) -> int | None:
        """0-100, or None if not dimmable."""
        ...

    @property
    @abstractmethod
    def color_temp(self) -> int | None:
        """Color temperature in Kelvin, or None if not supported."""
        ...

    @abstractmethod
    async def turn_on(
        self, brightness: int | None = None, color_temp: int | None = None
    ) -> None: ...

    @abstractmethod
    async def turn_off(self) -> None: ...


class Thermostat(Device):
    """A thermostat with temperature reading and setpoint control."""

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.THERMOSTAT

    @property
    @abstractmethod
    def current_temp(self) -> float: ...

    @property
    @abstractmethod
    def target_temp(self) -> float | None: ...

    @property
    @abstractmethod
    def mode(self) -> str:
        """e.g., 'heat', 'cool', 'auto', 'off'."""
        ...

    @abstractmethod
    async def set_target_temp(self, temp: float) -> None: ...

    @abstractmethod
    async def set_mode(self, mode: str) -> None: ...


class Lock(Device):
    """A smart lock."""

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.LOCK

    @property
    @abstractmethod
    def is_locked(self) -> bool: ...

    @abstractmethod
    async def lock(self) -> None: ...

    @abstractmethod
    async def unlock(self) -> None: ...


class Speaker(Device):
    """An audio speaker/player."""

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.SPEAKER

    @property
    @abstractmethod
    def is_playing(self) -> bool: ...

    @property
    @abstractmethod
    def volume(self) -> int:
        """0-100."""
        ...

    @abstractmethod
    async def play(self, uri: str | None = None) -> None: ...

    @abstractmethod
    async def pause(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def set_volume(self, level: int) -> None: ...


class Display(Device):
    """A TV or display."""

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.DISPLAY

    @property
    @abstractmethod
    def is_on(self) -> bool: ...

    @property
    @abstractmethod
    def current_input(self) -> str | None: ...

    @abstractmethod
    async def turn_on(self) -> None: ...

    @abstractmethod
    async def turn_off(self) -> None: ...

    @abstractmethod
    async def set_input(self, input_name: str) -> None: ...


class Switch(Device):
    """A simple on/off switch or relay."""

    @property
    def device_type(self) -> DeviceType:
        return DeviceType.SWITCH

    @property
    @abstractmethod
    def is_on(self) -> bool: ...

    @abstractmethod
    async def turn_on(self) -> None: ...

    @abstractmethod
    async def turn_off(self) -> None: ...


@runtime_checkable
class DeviceProvider(Protocol):
    """Protocol for services that can discover and provide devices.

    Any service that provides devices should implement this protocol
    and declare the ``"device_provider"`` capability in its ServiceInfo.
    """

    @property
    def provider_name(self) -> str:
        """Human-readable name identifying this provider (used in device registry)."""
        ...

    async def discover_devices(self) -> list[Device]:
        """Discover and return devices managed by this provider."""
        ...

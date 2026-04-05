# Device Interfaces

## Summary
ABC hierarchy for all controllable device types. `Device` is the base, with type-specific subclasses for Light, Thermostat, Lock, Speaker, Display, and Switch. `DeviceProvider` protocol allows services to optionally provide devices.

## Details
Located in `src/gilbert/interfaces/devices.py`.

**Base `Device` ABC** provides:
- Properties: `device_id`, `name`, `device_type` (StrEnum), `state` (online/offline/unknown/error), `attributes` (dict)
- Methods: `refresh()` (async — polls hardware), `execute_command()` (async — generic dispatch)

**Type-specific ABCs** extend Device:
- `Light` — `is_on`, `brightness` (0-100), `color_temp` (Kelvin), `turn_on()`, `turn_off()`
- `Thermostat` — `current_temp`, `target_temp`, `mode`, `set_target_temp()`, `set_mode()`
- `Lock` — `is_locked`, `lock()`, `unlock()`
- `Speaker` — `is_playing`, `volume` (0-100), `play()`, `pause()`, `stop()`, `set_volume()`
- `Display` — `is_on`, `current_input`, `turn_on()`, `turn_off()`, `set_input()`
- `Switch` — `is_on`, `turn_on()`, `turn_off()`

**DeviceProvider protocol** (`@runtime_checkable`):
- `provider_name` property — identifies the source of devices
- `discover_devices()` — returns list of Device instances
- Any Service declaring the `"device_provider"` capability should implement this protocol
- `DeviceManagerService.discover_providers()` finds all such services after startup and registers their devices

**Key pattern**: Properties read cached local state (sync). Mutation methods send commands to hardware (async). `refresh()` polls hardware and updates the cache (async).

## Related
- `src/gilbert/interfaces/devices.py` — all device ABCs and DeviceProvider protocol
- `src/gilbert/core/device_manager.py` — manages active device instances
- `src/gilbert/core/services/device_manager.py` — DeviceManagerService with discover_providers()
- `tests/unit/test_device_provider.py` — DeviceProvider discovery tests

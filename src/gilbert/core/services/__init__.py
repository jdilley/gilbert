"""Core service wrappers — thin adapters making existing components discoverable."""

from gilbert.core.services.credentials import CredentialService
from gilbert.core.services.device_manager import DeviceManagerService
from gilbert.core.services.event_bus import EventBusService
from gilbert.core.services.storage import StorageService
from gilbert.core.services.tts import TTSService

__all__ = [
    "CredentialService",
    "DeviceManagerService",
    "EventBusService",
    "StorageService",
    "TTSService",
]

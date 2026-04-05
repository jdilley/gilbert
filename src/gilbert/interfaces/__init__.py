"""Gilbert interfaces — ABCs and protocol definitions."""

from gilbert.interfaces.devices import (
    Device,
    DeviceProvider,
    DeviceState,
    DeviceType,
    Display,
    Light,
    Lock,
    Speaker,
    Switch,
    Thermostat,
)
from gilbert.interfaces.credentials import (
    AnyCredential,
    ApiKeyCredential,
    CredentialType,
    GoogleServiceAccountCredential,
    UsernamePasswordCredential,
)
from gilbert.interfaces.events import Event, EventBus, EventHandler
from gilbert.interfaces.plugin import Plugin, PluginMeta
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver
from gilbert.interfaces.storage import (
    Filter,
    FilterOp,
    IndexDefinition,
    Query,
    SortField,
    StorageBackend,
)
from gilbert.interfaces.tts import (
    AudioFormat,
    SynthesisRequest,
    SynthesisResult,
    TTSBackend,
    Voice,
)

__all__ = [
    "AnyCredential",
    "ApiKeyCredential",
    "AudioFormat",
    "CredentialType",
    "Device",
    "DeviceProvider",
    "DeviceState",
    "DeviceType",
    "Display",
    "Event",
    "EventBus",
    "EventHandler",
    "Filter",
    "FilterOp",
    "GoogleServiceAccountCredential",
    "IndexDefinition",
    "Light",
    "Lock",
    "Plugin",
    "PluginMeta",
    "Query",
    "Service",
    "ServiceInfo",
    "ServiceResolver",
    "SortField",
    "Speaker",
    "StorageBackend",
    "Switch",
    "SynthesisRequest",
    "SynthesisResult",
    "TTSBackend",
    "Thermostat",
    "UsernamePasswordCredential",
    "Voice",
]

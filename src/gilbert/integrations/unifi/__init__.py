"""UniFi integration — presence detection via Network, Protect, and Access."""

from gilbert.integrations.unifi.name_resolver import NameResolver
from gilbert.integrations.unifi.presence import UniFiPresenceBackend

__all__ = ["NameResolver", "UniFiPresenceBackend"]

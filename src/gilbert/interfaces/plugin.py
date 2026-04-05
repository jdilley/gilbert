"""Plugin interface — contract for extending Gilbert."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gilbert.core.service_manager import ServiceManager


@dataclass
class PluginMeta:
    """Metadata declared by a plugin."""

    name: str
    version: str
    description: str = ""
    device_types: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)


class Plugin(ABC):
    """Interface that all plugins must implement."""

    @abstractmethod
    def metadata(self) -> PluginMeta: ...

    @abstractmethod
    async def setup(self, services: ServiceManager) -> None:
        """Called when the plugin is loaded.

        Use `services` to register discoverable services with capabilities.
        """
        ...

    @abstractmethod
    async def teardown(self) -> None:
        """Called when the plugin is unloaded. Clean up resources."""
        ...

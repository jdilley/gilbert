"""Application bootstrap — wires everything together and manages lifecycle."""

import logging

from gilbert.config import GilbertConfig
from gilbert.core.device_manager import DeviceManager
from gilbert.core.events import InMemoryEventBus
from gilbert.core.logging import setup_logging
from gilbert.core.registry import ServiceRegistry
from gilbert.core.service_manager import ServiceManager
from gilbert.core.services import DeviceManagerService, EventBusService, StorageService, TTSService
from gilbert.core.services.credentials import CredentialService
from gilbert.interfaces.events import EventBus
from gilbert.interfaces.plugin import Plugin
from gilbert.interfaces.storage import StorageBackend
from gilbert.interfaces.tts import TTSBackend
from gilbert.plugins.loader import PluginLoader
from gilbert.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)


class Gilbert:
    """Main application. Boots the system, loads plugins, starts services."""

    def __init__(self, config: GilbertConfig) -> None:
        self.config = config
        self.registry = ServiceRegistry()
        self.service_manager = ServiceManager()
        self._plugins: list[Plugin] = []

    async def start(self) -> None:
        """Initialize all subsystems and start the application."""
        # 1. Logging (first — everything else should be able to log)
        setup_logging(
            level=self.config.logging.level,
            log_file=self.config.logging.file,
            ai_log_file=self.config.logging.ai_log_file,
        )
        logger.info("Starting Gilbert...")

        # 2. Register core services
        storage = await self._init_storage()
        self.service_manager.register(StorageService(storage))

        event_bus = InMemoryEventBus()
        self.service_manager.register(EventBusService(event_bus))
        self.service_manager.set_event_bus(event_bus)

        self.service_manager.register(CredentialService(self.config.credentials))

        self.service_manager.register(DeviceManagerService())

        # 3. Register TTS service if enabled
        if self.config.tts.enabled:
            tts_backend = self._create_tts_backend()
            self.service_manager.register(
                TTSService(
                    tts_backend,
                    self.config.tts.credential,
                    config=self.config.tts.settings,
                    voices=self.config.tts.voices,
                    default_voice=self.config.tts.default_voice,
                )
            )

        # 4. Also register in old registry for backward compat
        self.registry.register(StorageBackend, storage)
        self.registry.register(EventBus, event_bus)
        self.registry.register(ServiceManager, self.service_manager)

        # 5. Load plugins (they can register more services)
        loader = PluginLoader()
        for source in self.config.plugins:
            if source.enabled:
                try:
                    plugin = await loader.load(source.source)
                    await plugin.setup(self.service_manager)
                    self._plugins.append(plugin)
                except Exception:
                    logger.exception("Failed to load plugin: %s", source.source)

        # 6. Start all services (dependency resolution happens here)
        await self.service_manager.start_all()

        # 7. Register started services in old registry for backward compat
        dm_svc = self.service_manager.get_by_capability("device_management")
        if isinstance(dm_svc, DeviceManagerService):
            self.registry.register(DeviceManager, dm_svc.manager)

        # 8. Discover devices from provider services
        if isinstance(dm_svc, DeviceManagerService):
            await dm_svc.discover_providers(self.service_manager)

        started = len(self.service_manager.started_services)
        failed = len(self.service_manager.failed_services)
        logger.info(
            "Gilbert started — %d services (%d failed), %d plugins",
            started,
            failed,
            len(self._plugins),
        )

    async def stop(self) -> None:
        """Shut down all subsystems."""
        logger.info("Stopping Gilbert...")

        # Tear down plugins
        for plugin in reversed(self._plugins):
            try:
                await plugin.teardown()
            except Exception:
                logger.exception("Error tearing down plugin: %s", plugin.metadata().name)

        # Stop all services (reverse order, includes storage close)
        await self.service_manager.stop_all()

        logger.info("Gilbert stopped")

    def _create_tts_backend(self) -> TTSBackend:
        """Create the TTS backend based on config."""
        backend_name = self.config.tts.backend
        if backend_name == "elevenlabs":
            from gilbert.integrations.elevenlabs_tts import ElevenLabsTTS

            return ElevenLabsTTS()
        raise ValueError(f"Unknown TTS backend: {backend_name}")

    async def _init_storage(self) -> StorageBackend:
        """Initialize the storage backend based on config."""
        if self.config.storage.backend == "sqlite":
            from pathlib import Path

            db_path = Path(self.config.storage.connection).expanduser()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            storage = SQLiteStorage(str(db_path))
            await storage.initialize()
            return storage
        raise ValueError(f"Unknown storage backend: {self.config.storage.backend}")

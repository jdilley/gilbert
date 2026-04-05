# Plugin System

## Summary
Plugins extend Gilbert with new device types, services, or capabilities. Loaded from local paths or GitHub URLs via an explicit `create_plugin()` entry point.

## Details
**Plugin interface** (`src/gilbert/interfaces/plugin.py`):
- `PluginMeta` dataclass — name, version, description, device_types, services, required_capabilities
- `Plugin` ABC — `metadata()`, `setup(services: ServiceManager)`, `teardown()`
- During `setup()`, plugins register discoverable services into `ServiceManager`

**Plugin loader** (`src/gilbert/plugins/loader.py`):
- `PluginLoader.load(source)` — loads from local path or GitHub URL
- Local: expects `plugin.py` with `create_plugin() -> Plugin` function
- GitHub: clones to cache dir (`.gilbert/plugins/` or temp), then loads as local
- Validates metadata completeness after loading

**Plugin contract**: a plugin directory must contain `plugin.py` with a `create_plugin()` function. No magic class scanning, no entry_points, no metaclass tricks.

## Related
- `src/gilbert/interfaces/plugin.py` — Plugin, PluginMeta
- `src/gilbert/plugins/loader.py` — PluginLoader
- `src/gilbert/core/service_manager.py` — ServiceManager (discoverable services)
- [Service System](memory-service-system.md) — how services work

# Plugin System

## Summary
Plugins extend Gilbert with new services, tools, and capabilities. They can live in external directories, declare dependencies on other plugins, provide default configuration, and store data in isolated directories. Plugins implement the `Configurable` protocol to read settings from the `ConfigurationService`; there is no CredentialService. Config is stored in entity storage.

## Details

### Plugin Interface (`src/gilbert/interfaces/plugin.py`)
- **`PluginMeta`** dataclass — `name`, `version`, `description`, `provides` (capabilities), `requires` (capabilities), `depends_on` (other plugin names)
- **`PluginContext`** dataclass — passed to `setup()`, contains:
  - `services: ServiceManager` — register and discover services
  - `config: dict[str, Any]` — this plugin's resolved config section
  - `data_dir: Path` — `.gilbert/plugin-data/<plugin-name>/` for persistent data
- **`Plugin`** ABC — `metadata()`, `setup(context: PluginContext)`, `teardown()`

### Plugin Manifest (`plugin.yaml`)
Each plugin directory contains a `plugin.yaml` manifest declaring:
- Metadata: `name`, `version`, `description`
- Capability declarations: `provides`, `requires`
- Plugin-level dependencies: `depends_on` (other plugin names)
- Default configuration: `config` section (merged into config chain)

### Plugin Loader (`src/gilbert/plugins/loader.py`)
- **Directory scanning**: `scan_directories(dirs)` — finds subdirs with `plugin.yaml`
- **Manifest parsing**: `PluginManifest` class wraps parsed `plugin.yaml` data
- **Config collection**: `collect_default_configs(manifests)` — gathers all plugin default configs
- **Dependency resolution**: `topological_sort(manifests)` — orders by `depends_on` (cycle detection)
- **Loading**: `load(source)` for path/URL, `load_from_manifest(manifest)` for scanned plugins
- Entry point contract: `plugin.py` with `create_plugin() -> Plugin` function

### Configuration Layering
Three-layer merge order:
1. `gilbert.yaml` (core defaults)
2. Plugin default configs from `plugin.yaml` files (namespaced under `plugins.config.<name>`)
3. `.gilbert/config.yaml` (user overrides — wins over plugin defaults)

Users override plugin config in `.gilbert/config.yaml`:
```yaml
plugins:
  config:
    my-plugin:
      poll_interval: 60
```

### Config Model (`src/gilbert/config.py`)
- **`PluginsConfig`** — `directories: list[str]`, `sources: list[PluginSource]`, `config: dict[str, dict[str, Any]]`
- `GilbertConfig.plugins` is a `PluginsConfig` (replaces old `list[PluginSource]`)
- Legacy list format is auto-migrated during `load_config()`

### Bootstrap Flow (`src/gilbert/core/app.py`)
- `Gilbert.create()` class method handles the full config layering:
  1. Reads base config to discover plugin directories
  2. Scans directories for manifests
  3. Collects plugin default configs
  4. Calls `load_config(plugin_defaults=...)` for three-layer merge
- `Gilbert.start()` loads plugins after core services are registered:
  1. Topologically sorts discovered manifests by `depends_on`
  2. Loads each plugin, creates its data dir, passes `PluginContext`
  3. Also loads legacy explicit sources (path/URL)
  4. Then `service_manager.start_all()` resolves service dependencies
- Each successfully-loaded plugin is tracked in `Gilbert._plugins` as a `LoadedPlugin` dataclass holding the plugin instance, the install path on disk, and the set of service names registered during `setup()` (snapshotted by diffing `service_manager.list_services()` before/after).
- `Gilbert.make_plugin_context(name)` is the shared context builder used by both the boot-time loader and the runtime `PluginManagerService`.

### Runtime Install / Uninstall (`src/gilbert/core/services/plugin_manager.py`)
The `PluginManagerService` allows admins to install plugins at runtime from the web UI (`/plugins`) or chat (`/plugin install <url>` / `/plugin uninstall <name>` / `/plugin list`). Capabilities: `plugin_manager`, `ai_tools`, `ws_handlers`. WS frames: `plugins.list` / `plugins.install` / `plugins.uninstall` (admin-level via `interfaces/acl.py`).

**Install flow** (`PluginLoader.install_from_url` then service-side):
1. `_fetch_to(url)` routes by URL shape — archive suffix wins (`.zip`, `.tar.gz`, `.tgz`, `.tar.bz2`); GitHub URLs (with optional `/tree/<ref>/<subpath>` or `/blob/...`) are shallow-cloned. Anything else is rejected.
2. Archives are downloaded with `httpx.stream` (in `asyncio.to_thread`), extracted with safe-extract helpers that reject `..` and absolute paths, and unwrapped if there's a single top-level dir (the GitHub source-zip convention).
3. `_validate_plugin_dir` checks for `plugin.yaml` + `plugin.py` at the root, valid name (`[a-zA-Z][a-zA-Z0-9_-]*`), and required version.
4. `_test_load` imports the plugin under a throwaway `gilbert_plugin_test_<uuid>` package name (cleaned up afterward) so `create_plugin()` is verified before we commit anything to disk.
5. The directory is moved into `installed-plugins/<name>/`. Existing installs raise unless `force=True`.
6. `PluginManagerService.install` snapshots the registered-service set, calls `loader.load_from_manifest()` + `plugin.setup(ctx)`, diffs to learn which services the plugin added, then `service_manager.start_service(name)` for each new one.
7. The plugin is appended to `Gilbert._plugins` (so it's torn down on shutdown) and a row is persisted in the `gilbert.plugin_installs` entity collection (`{_id, name, version, source_url, install_path, installed_at, registered_services}`).
8. **Rollback on failure**: any service registered between snapshots is `stop_and_unregister`'d, the install dir is removed, and the registry stays clean.

**Uninstall flow**: `plugin.teardown()`, `service_manager.stop_and_unregister(name)` for each registered service (capabilities are unindexed and the service is dropped from `_registered`/`_started`), `Gilbert.remove_loaded_plugin`, registry row deleted, install dir removed, and any cached `gilbert_plugin_<sanitized>.*` entries are purged from `sys.modules` so a future re-install gets a fresh import.

**ServiceManager helpers** (`src/gilbert/core/service_manager.py`):
- `start_service(name)` — start a service that was registered after `start_all()` (e.g. inside a plugin `setup()` that ran post-boot). No-op if already started.
- `stop_and_unregister(name)` — stop + remove a service entirely, with capability index cleanup. Publishes `service.stopped`. Used by uninstall.

**Source buckets**: `list_installed()` classifies each plugin as `std` / `local` / `installed` / `unknown` by which configured `plugins.directories` entry contains its install path. Only `installed`-bucket plugins are uninstallable through this service — std-plugins and local-plugins are managed outside the runtime.

### Plugin Data Directory
Plugins store persistent data in `.gilbert/plugin-data/<plugin-name>/`. Plugins never write to their own source directory. The data dir is created automatically during plugin setup.

### Credential Handling
There is no CredentialService. Plugins store credentials inline in their configuration (via `ConfigurationService` and entity storage). Sensitive config params are marked with `sensitive=True` in `ConfigParam` declarations.

## Related
- `src/gilbert/interfaces/plugin.py` — Plugin, PluginMeta, PluginContext
- `src/gilbert/plugins/loader.py` — PluginLoader, PluginManifest, install_from_url, archive helpers
- `src/gilbert/config.py` — PluginsConfig, load_config()
- `src/gilbert/core/app.py` — Gilbert.create(), _load_plugins(), make_plugin_context(), LoadedPlugin
- `src/gilbert/core/service_manager.py` — start_service(), stop_and_unregister() for hot load/unload
- `src/gilbert/core/services/plugin_manager.py` — PluginManagerService (install/uninstall/list_installed, /plugin tools, plugins.* WS handlers)
- `frontend/src/components/plugins/PluginsPage.tsx` — admin UI for the install registry
- [Service System](memory-service-system.md) — how services work
- [Configuration and Data Directory](memory-config-and-data-dir.md) — config layering

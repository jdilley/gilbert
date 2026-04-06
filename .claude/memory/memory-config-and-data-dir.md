# Configuration and Data Directory

## Summary
Layered YAML config system with three-layer merge: `gilbert.yaml` (committed defaults) + plugin default configs + `.gilbert/config.yaml` (per-installation overrides). The `.gilbert/` directory is the gitignored data folder for all per-instance data.

## Details
**Config layering** (`src/gilbert/config.py`):
1. `gilbert.yaml` at repo root — committed defaults, shipped with the repo
2. Plugin default configs from `plugin.yaml` files (namespaced under `plugins.config.<name>`)
3. `.gilbert/config.yaml` — per-installation overrides, deep-merged on top
4. Explicit path via `load_config(path=...)` bypasses layering

Deep merge means users only specify values they want to change in `.gilbert/config.yaml`.

**Config models** (Pydantic):
- `GilbertConfig` — top-level: storage, logging, plugins, integrations
- `StorageConfig` — backend type + connection string (default: `.gilbert/gilbert.db`)
- `LoggingConfig` — level, file path, AI log file path
- `PluginsConfig` — `directories` (scan paths), `sources` (explicit path/URL), `config` (per-plugin overrides)
- `PluginSource` — source (path or URL) + enabled flag

**`.gilbert/` directory** contains:
- `config.yaml` — user configuration overrides
- `gilbert.db` — SQLite database
- `gilbert.log` — general application log
- `ai_calls.log` — AI API call log (separate for debugging)
- `plugin-data/<plugin-name>/` — per-plugin persistent data directories
- Plugin cache (fetched GitHub repos)

**Key principle**: users clone the repo and run it. `.gilbert/` is auto-created on first start. No source files need editing for customization.

## Related
- `src/gilbert/config.py` — config loading and Pydantic models
- `gilbert.yaml` — committed default configuration
- `.gitignore` — `.gilbert/` is gitignored
- `src/gilbert/core/app.py` — reads config during bootstrap
- [Plugin System](memory-plugin-system.md) — plugin architecture details

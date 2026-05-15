# Migration System

## Summary
Gilbert has an arbitrary one-shot upgrade-script system at `src/gilbert/migrations/`. Migrations are **not** schema migrations — the storage is schema-less. They're general "run once after an update" scripts: rename a stored field, backfill a default on existing entities, move files in `.gilbert/`, purge orphans, recompute a derived index, anything else that needs to happen exactly once per install. Core migrations live in `src/gilbert/migrations/`; each plugin can ship its own at `<plugin>/migrations/`. State is tracked in the `_migrations` storage collection.

## Details

### File layout
- Core: `src/gilbert/migrations/0001_short_name.py`, `0002_…`, etc. (`runner.py` and `__init__.py` are reserved and skipped during discovery.)
- Plugins: `std-plugins/<name>/migrations/0001_…py` (and the same path under `local-plugins/` / `installed-plugins/`).
- Filenames MUST match `NNNN_<identifier>.py` — 4-digit zero-padded ordering prefix, underscore, then a lowercase identifier. Anything else in the directory is silently skipped (helpers can live alongside migrations under names that don't match this pattern).

### Migration file contract
```python
description = "what this does (one short line)"

async def up(ctx: MigrationContext) -> None:
    # ctx.storage  — StorageBackend
    # ctx.repo_root — Path
    # ctx.log       — logging.Logger named ``gilbert.migrations``
    ...
```
- Make `up` idempotent. The runner records success after `up` returns; a crash mid-`up` will re-run on the next invocation.
- No `down` — Gilbert's storage is loose enough that rollback semantics are rarely useful. Roll forward with a new migration if you need to undo something.

### Discovery + tracking (`src/gilbert/migrations/runner.py`)
- `discover_migrations(plugin_dirs)` returns a flat ordered list across core + every plugin dir (sorted plugin-name then file-name within each plugin). Core migrations come first so plugin migrations can depend on core fields being shaped.
- `MigrationRunner(storage, repo_root)` reads applied state from the `_migrations` collection (entity id = `<scope>:<basename>`, e.g. `core:0001_split_inbox` or `sonos:0001_speaker_groups`).
- `runner.pending(migrations)` filters to unapplied.
- `runner.run(migrations)` applies each pending migration in order, recording one row per success. First failure re-raises (caller stops); earlier successes stay recorded.

### CLI — `gilbert.cli.migrate`
- `python -m gilbert.cli.migrate list` — print pending, **exit 1 if any** (so `gilbert.sh` can branch on it).
- `python -m gilbert.cli.migrate status` — print applied + pending, exit 0.
- `python -m gilbert.cli.migrate up` — apply every pending, exit 0/1.
- Boots only enough of Gilbert to open the configured storage backend and scan plugin directories (mirrors `gilbert.cli.doctor`'s no-service-startup pattern). The storage open/close handshake mirrors `Gilbert._init_storage`.

### Shell integration (`gilbert.sh`)
- `./gilbert.sh start` and `./gilbert.sh dev`:
  1. Run `sync_python_deps`.
  2. Run `check_pending_migrations` — if `gilbert.cli.migrate list` exits non-zero AND stdin is a TTY, prompt the user (y/N) to apply now. On non-TTY (systemd, CI), print a warning and skip.
  3. Build frontend.
  4. Enter the supervisor loop (which has its own sync inside but no migration check — auto-restarts don't reprompt).
- `./gilbert.sh update` — `git pull --ff-only` (refuses if working tree is dirty), `git submodule update --init --recursive --remote std-plugins`, `sync_python_deps`, then **unattended** `migrate up`. Leaves Gilbert stopped.
- `./gilbert.sh migrate <subcommand>` — passthrough to `gilbert.cli.migrate`.

### Scope key gotcha
Tracking is keyed by `<scope>:<basename>`. Renaming a migration file (e.g. `0001_x.py` → `0001_y.py`) creates a new key and re-runs. Don't rename applied migrations.

## Related
- `src/gilbert/migrations/runner.py` — discovery, tracking, execution.
- `src/gilbert/cli/migrate.py` — CLI entrypoint.
- `gilbert.sh` — `start` / `update` / `migrate` sub-commands.
- [Storage Pattern](memory-backend-pattern.md) — what `ctx.storage` is.
- [Plugin System](memory-plugin-system.md) — where `<plugin>/migrations/` fits in the plugin layout.

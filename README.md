# Gilbert

AI assistant for home and business automation. Extensible, plugin-driven architecture with discoverable services and device integrations.

## Quick Start

```bash
# Clone and enter the repo
git clone https://github.com/briandilley/gilbert.git
cd gilbert

# Install Python 3.12+ and dependencies via uv
uv python install 3.12
uv venv
uv pip install -e ".[dev]"

# Run tests
uv run pytest -v
```

On first run, Gilbert creates a `.gilbert/` directory for your local data (database, logs, config overrides). This folder is gitignored — your customizations stay local.

## Configuration

- `gilbert.yaml` — default configuration (committed, don't edit for personal use)
- `.gilbert/config.yaml` — your per-installation overrides (create this file, gitignored)

Overrides are deep-merged on top of defaults, so you only need to specify what you're changing.

## Documentation

See [CLAUDE.md](CLAUDE.md) for full architecture documentation, project structure, design decisions, and development guidelines.

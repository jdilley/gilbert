# local-plugins

Plugins you write yourself for this specific Gilbert installation.

Each subdirectory should contain a `plugin.yaml` manifest and a
`plugin.py` entry point exposing `create_plugin() -> Plugin`. See the
main Gilbert README's **Plugins** section and the first-party examples
under `std-plugins/` (from [briandilley/gilbert-plugins](https://github.com/briandilley/gilbert-plugins))
for the full contract.

**This directory is gitignored** — your local work never lands in
source control. If you build something you'd like to share, open a
pull request against `briandilley/gilbert-plugins` so it can ship
under `std-plugins/` for everyone.

Restart Gilbert after adding or changing a plugin here so the loader
picks it up on the next scan.

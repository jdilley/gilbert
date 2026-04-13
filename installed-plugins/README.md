# installed-plugins

Plugins installed at runtime from external sources — typically
fetched from GitHub URLs via the plugin loader rather than developed
locally or pulled from the first-party `std-plugins/` repository.

**Don't edit by hand.** The plugin loader owns this directory; files
here may be overwritten or cleaned up on the next run. Persistent,
hand-maintained plugins belong in `local-plugins/` instead.

**This directory is gitignored** — installed plugins are a
per-installation concern and never land in source control. If a
plugin is worth tracking, fork it or submit it upstream to
`briandilley/gilbert-plugins`.

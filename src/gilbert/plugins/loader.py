"""Plugin loader — discovers and loads plugins from local paths or GitHub URLs."""

import importlib.util
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from gilbert.interfaces.plugin import Plugin

logger = logging.getLogger(__name__)


class PluginError(Exception):
    """Raised when a plugin fails to load or validate."""


class PluginLoader:
    """Loads plugins from local directories or GitHub URLs."""

    def __init__(self, cache_dir: str | None = None) -> None:
        self._cache_dir = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "gilbert-plugins"

    async def load(self, source: str) -> Plugin:
        """Load a plugin from a local path or GitHub URL."""
        if source.startswith(("http://", "https://")):
            logger.info("Loading plugin from URL: %s", source)
            path = self._fetch_from_github(source)
        else:
            logger.info("Loading plugin from path: %s", source)
            path = Path(source)

        if not path.is_dir():
            raise PluginError(f"Plugin path is not a directory: {path}")

        plugin = self._load_from_path(path)
        self._validate_plugin(plugin)
        logger.info("Plugin loaded: %s v%s", plugin.metadata().name, plugin.metadata().version)
        return plugin

    def _load_from_path(self, path: Path) -> Plugin:
        """Load a plugin from a local directory.

        Expects the directory to contain a `plugin.py` with a
        `create_plugin() -> Plugin` function.
        """
        plugin_file = path / "plugin.py"
        if not plugin_file.exists():
            raise PluginError(f"No plugin.py found in {path}")

        module_name = f"gilbert_plugin_{path.name}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_file)
        if spec is None or spec.loader is None:
            raise PluginError(f"Could not load module spec from {plugin_file}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        create_fn = getattr(module, "create_plugin", None)
        if create_fn is None:
            raise PluginError(f"Plugin at {path} does not define create_plugin()")

        plugin = create_fn()
        if not isinstance(plugin, Plugin):
            raise PluginError(f"create_plugin() in {path} did not return a Plugin instance")

        return plugin

    def _fetch_from_github(self, url: str) -> Path:
        """Clone or update a GitHub repository into the cache directory."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # Derive a directory name from the URL
        repo_name = url.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        target = self._cache_dir / repo_name

        if target.exists():
            logger.debug("Updating cached plugin: %s", repo_name)
            subprocess.run(
                ["git", "-C", str(target), "pull", "--ff-only"],
                check=True,
                capture_output=True,
            )
        else:
            logger.debug("Cloning plugin: %s", url)
            subprocess.run(
                ["git", "clone", url, str(target)],
                check=True,
                capture_output=True,
            )

        return target

    @staticmethod
    def _validate_plugin(plugin: Plugin) -> None:
        """Verify a plugin's metadata is complete."""
        meta = plugin.metadata()
        if not meta.name:
            raise PluginError("Plugin metadata missing 'name'")
        if not meta.version:
            raise PluginError("Plugin metadata missing 'version'")

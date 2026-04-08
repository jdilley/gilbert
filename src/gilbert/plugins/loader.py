"""Plugin loader — discovers and loads plugins from directories, local paths, or GitHub URLs."""

import importlib.util
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from gilbert.interfaces.plugin import Plugin, PluginMeta

logger = logging.getLogger(__name__)


class PluginError(Exception):
    """Raised when a plugin fails to load or validate."""


class PluginManifest:
    """Parsed plugin.yaml manifest — metadata + default config."""

    def __init__(self, path: Path, raw: dict[str, Any]) -> None:
        self.path = path
        self.name: str = raw.get("name", path.name)
        self.version: str = raw.get("version", "0.0.0")
        self.description: str = raw.get("description", "")
        self.provides: list[str] = raw.get("provides", [])
        self.requires: list[str] = raw.get("requires", [])
        self.depends_on: list[str] = raw.get("depends_on", [])
        self.config: dict[str, Any] = raw.get("config", {})

    def to_plugin_meta(self) -> PluginMeta:
        return PluginMeta(
            name=self.name,
            version=self.version,
            description=self.description,
            provides=list(self.provides),
            requires=list(self.requires),
            depends_on=list(self.depends_on),
        )


class PluginLoader:
    """Loads plugins from directories, local paths, or GitHub URLs."""

    def __init__(self, cache_dir: str | None = None) -> None:
        self._cache_dir = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "gilbert-plugins"

    # --- Directory scanning ---

    def scan_directories(self, directories: list[str]) -> list[PluginManifest]:
        """Scan plugin directories for subdirectories containing plugin.yaml."""
        manifests: list[PluginManifest] = []
        for dir_path_str in directories:
            dir_path = Path(dir_path_str).expanduser().resolve()
            if not dir_path.is_dir():
                logger.warning("Plugin directory does not exist: %s", dir_path)
                continue
            for child in sorted(dir_path.iterdir()):
                if not child.is_dir():
                    continue
                manifest_file = child / "plugin.yaml"
                if not manifest_file.exists():
                    continue
                try:
                    manifest = self._parse_manifest(child, manifest_file)
                    manifests.append(manifest)
                    logger.info(
                        "Discovered plugin: %s v%s at %s",
                        manifest.name,
                        manifest.version,
                        child,
                    )
                except Exception:
                    logger.exception("Failed to parse plugin manifest: %s", manifest_file)
        return manifests

    def collect_default_configs(self, manifests: list[PluginManifest]) -> dict[str, dict[str, Any]]:
        """Collect default config sections from all plugin manifests.

        Returns a dict mapping plugin name to its default config dict.
        """
        defaults: dict[str, dict[str, Any]] = {}
        for manifest in manifests:
            if manifest.config:
                defaults[manifest.name] = dict(manifest.config)
        return defaults

    def topological_sort(self, manifests: list[PluginManifest]) -> list[PluginManifest]:
        """Sort plugins by depends_on order. Raises PluginError on cycles."""
        by_name: dict[str, PluginManifest] = {m.name: m for m in manifests}
        sorted_names: list[str] = []
        visited: set[str] = set()
        in_stack: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in in_stack:
                raise PluginError(f"Circular plugin dependency detected involving: {name}")
            in_stack.add(name)
            manifest = by_name.get(name)
            if manifest:
                for dep in manifest.depends_on:
                    if dep not in by_name:
                        logger.warning(
                            "Plugin %s depends on %s which is not installed",
                            name,
                            dep,
                        )
                        continue
                    visit(dep)
            in_stack.discard(name)
            visited.add(name)
            sorted_names.append(name)

        for name in by_name:
            visit(name)

        return [by_name[n] for n in sorted_names]

    # --- Loading individual plugins ---

    async def load(self, source: str) -> Plugin:
        """Load a plugin from a local path or GitHub URL."""
        if source.startswith(("http://", "https://")):
            logger.info("Loading plugin from URL: %s", source)
            path = self._fetch_from_github(source)
        else:
            logger.info("Loading plugin from path: %s", source)
            path = Path(source).expanduser().resolve()

        if not path.is_dir():
            raise PluginError(f"Plugin path is not a directory: {path}")

        plugin = self._load_from_path(path)
        self._validate_plugin(plugin)
        logger.info("Plugin loaded: %s v%s", plugin.metadata().name, plugin.metadata().version)
        return plugin

    def load_from_manifest(self, manifest: PluginManifest) -> Plugin:
        """Load a plugin whose manifest has already been parsed."""
        plugin = self._load_from_path(manifest.path)
        self._validate_plugin(plugin)
        logger.info("Plugin loaded: %s v%s", plugin.metadata().name, plugin.metadata().version)
        return plugin

    # --- Internal helpers ---

    @staticmethod
    def _parse_manifest(plugin_dir: Path, manifest_file: Path) -> PluginManifest:
        """Parse a plugin.yaml manifest file."""
        with open(manifest_file) as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict):
            raise PluginError(f"Invalid plugin.yaml (not a mapping): {manifest_file}")
        return PluginManifest(path=plugin_dir, raw=raw)

    def _load_from_path(self, path: Path) -> Plugin:
        """Load a plugin from a local directory.

        Expects the directory to contain a `plugin.py` with a
        `create_plugin() -> Plugin` function.

        The plugin directory is registered as a Python package so that
        relative imports (``from .module import ...``) work inside
        plugin code.
        """
        plugin_file = path / "plugin.py"
        if not plugin_file.exists():
            raise PluginError(f"No plugin.py found in {path}")

        # Sanitize directory name for use as a Python identifier
        pkg_name = f"gilbert_plugin_{path.name}".replace("-", "_")

        # Register the plugin directory as a package so relative imports work
        if pkg_name not in sys.modules:
            from types import ModuleType

            pkg = ModuleType(pkg_name)
            pkg.__path__ = [str(path)]
            pkg.__package__ = pkg_name
            pkg.__file__ = str(path / "__init__.py")
            sys.modules[pkg_name] = pkg

        module_name = f"{pkg_name}.plugin"
        spec = importlib.util.spec_from_file_location(
            module_name, plugin_file,
            submodule_search_locations=[],
        )
        if spec is None or spec.loader is None:
            raise PluginError(f"Could not load module spec from {plugin_file}")

        module = importlib.util.module_from_spec(spec)
        module.__package__ = pkg_name
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

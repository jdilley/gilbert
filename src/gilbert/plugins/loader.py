"""Plugin loader — discovers and loads plugins from directories, local paths, or GitHub URLs."""

import asyncio
import importlib.util
import logging
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from gilbert.interfaces.plugin import Plugin, PluginMeta

logger = logging.getLogger(__name__)

# Plugin name format — becomes a directory name and Python package suffix.
_VALID_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-]*$")

# Recognized archive suffixes (longest match wins).
_ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".tar.bz2", ".zip")


class PluginError(Exception):
    """Raised when a plugin fails to load or validate."""


@dataclass
class InstalledPluginInfo:
    """Result of a successful plugin install."""

    name: str
    version: str
    description: str
    source_url: str
    install_path: Path
    manifest: "PluginManifest"


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

    # --- Install / uninstall (runtime plugin management) ---

    async def install_from_url(
        self,
        url: str,
        install_dir: Path,
        *,
        force: bool = False,
    ) -> InstalledPluginInfo:
        """Fetch a plugin from a URL, validate it, and move it into ``install_dir``.

        ``url`` may be:

        - A GitHub repo URL: ``https://github.com/<owner>/<repo>(.git)?``
        - A GitHub tree/blob URL pointing at a subdirectory:
          ``https://github.com/<owner>/<repo>/tree/<ref>/<subpath>``
          (``/blob/<ref>/<file>`` is normalized to its parent directory)
        - An archive URL ending in ``.zip``, ``.tar.gz``/``.tgz``, or
          ``.tar.bz2``.

        Raises ``PluginError`` on any validation failure.  On success the
        plugin lives under ``install_dir/<name>/`` and an
        ``InstalledPluginInfo`` is returned.  The caller (typically
        ``PluginManagerService``) is responsible for actually loading the
        plugin into the running service manager.
        """
        install_dir = Path(install_dir).expanduser().resolve()
        install_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="gilbert-plugin-stage-") as stage:
            stage_path = Path(stage)
            fetched = await self._fetch_to(url, stage_path)
            self._validate_plugin_dir(fetched)
            manifest = self._parse_manifest(fetched, fetched / "plugin.yaml")

            # Sanity-load the plugin under a throwaway package name to make
            # sure create_plugin() works before we commit it to the install
            # directory.  Use a unique name so we don't pollute sys.modules
            # with the real package name we'll register later.
            self._test_load(fetched)

            target = install_dir / manifest.name
            if target.exists():
                if not force:
                    raise PluginError(
                        f"Plugin already installed: {manifest.name}",
                    )
                shutil.rmtree(target)

            # Move the staged directory into place. Use copytree because
            # the temp dir lives on a tempfs that may not be on the same
            # filesystem as install_dir.
            shutil.copytree(fetched, target)

        logger.info(
            "Plugin installed: %s v%s -> %s",
            manifest.name, manifest.version, target,
        )
        return InstalledPluginInfo(
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            source_url=url,
            install_path=target,
            manifest=PluginManifest(target, {
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "provides": manifest.provides,
                "requires": manifest.requires,
                "depends_on": manifest.depends_on,
                "config": manifest.config,
            }),
        )

    async def uninstall(self, name: str, install_dir: Path) -> None:
        """Remove an installed plugin's directory from ``install_dir``.

        Validates the name and refuses to delete anything outside
        ``install_dir`` to avoid path-traversal mishaps.
        """
        if not _VALID_NAME_RE.match(name):
            raise PluginError(f"Invalid plugin name: {name!r}")
        install_dir = Path(install_dir).expanduser().resolve()
        target = (install_dir / name).resolve()
        try:
            target.relative_to(install_dir)
        except ValueError as exc:
            raise PluginError(
                f"Refusing to uninstall outside install dir: {target}",
            ) from exc
        if not target.exists():
            raise PluginError(f"Plugin not installed: {name}")
        shutil.rmtree(target)
        logger.info("Plugin uninstalled: %s (removed %s)", name, target)

    # --- Internal: fetching ---

    async def _fetch_to(self, url: str, stage_path: Path) -> Path:
        """Dispatch ``url`` to the right fetch helper. Returns the directory
        containing ``plugin.yaml`` at the root.
        """
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https", "file"}:
            raise PluginError(f"Unsupported plugin URL scheme: {scheme!r}")

        # Archive URL takes precedence — even on GitHub, a release ZIP is
        # an archive, not a repo to clone.
        suffix = _archive_suffix(parsed.path)
        if suffix is not None:
            return await self._fetch_archive(url, stage_path, suffix)

        # GitHub URLs (with optional /tree/ or /blob/ subpath).
        host = parsed.netloc.lower()
        if host in {"github.com", "www.github.com"}:
            return await self._fetch_github(url, stage_path)

        raise PluginError(
            f"Unsupported plugin URL: {url!r} — must be a GitHub URL "
            "or end in .zip/.tar.gz/.tgz/.tar.bz2",
        )

    async def _fetch_archive(
        self,
        url: str,
        stage_path: Path,
        suffix: str,
    ) -> Path:
        """Download an archive and extract it into ``stage_path``.

        Returns the directory containing ``plugin.yaml`` at the root —
        unwrapping a single top-level directory if necessary (the GitHub
        zip convention).
        """
        archive_file = stage_path / f"download{suffix}"

        def _download_sync() -> None:
            with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as r:
                r.raise_for_status()
                with open(archive_file, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)

        try:
            await asyncio.to_thread(_download_sync)
        except httpx.HTTPError as exc:
            raise PluginError(f"Failed to download {url}: {exc}") from exc

        extract_dir = stage_path / "extracted"
        extract_dir.mkdir()

        try:
            if suffix == ".zip":
                _safe_extract_zip(archive_file, extract_dir)
            else:
                mode = {
                    ".tar.gz": "r:gz",
                    ".tgz": "r:gz",
                    ".tar.bz2": "r:bz2",
                }[suffix]
                _safe_extract_tar(archive_file, extract_dir, mode)
        except PluginError:
            raise
        except Exception as exc:
            raise PluginError(f"Failed to extract archive: {exc}") from exc

        return _unwrap_single_top_dir(extract_dir)

    async def _fetch_github(self, url: str, stage_path: Path) -> Path:
        """Clone a GitHub repository (optionally pointing at a subpath) into
        ``stage_path``.  Returns the directory containing the plugin.

        Recognizes ``https://github.com/<owner>/<repo>(.git)?`` as a
        whole-repo clone, and
        ``https://github.com/<owner>/<repo>/tree/<ref>/<subpath...>`` /
        ``https://github.com/<owner>/<repo>/blob/<ref>/<file>`` as a
        clone-then-walk-into-subdir.
        """
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            raise PluginError(f"Invalid GitHub URL: {url!r}")

        owner, repo = parts[0], parts[1]
        if repo.endswith(".git"):
            repo = repo[:-4]

        ref: str | None = None
        subpath: list[str] = []
        if len(parts) >= 4 and parts[2] in {"tree", "blob"}:
            ref = parts[3]
            subpath = parts[4:]
            # ``/blob/<ref>/<dir>/<file.ext>`` → strip filename suffix.
            if parts[2] == "blob" and subpath and "." in subpath[-1]:
                subpath = subpath[:-1]

        clone_url = f"https://github.com/{owner}/{repo}.git"
        clone_target = stage_path / "repo"

        def _clone_sync() -> None:
            cmd = ["git", "clone", "--depth=1"]
            if ref:
                cmd += ["--branch", ref]
            cmd += [clone_url, str(clone_target)]
            subprocess.run(cmd, check=True, capture_output=True)

        try:
            await asyncio.to_thread(_clone_sync)
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
            raise PluginError(
                f"git clone failed for {clone_url}: {stderr.strip() or exc}",
            ) from exc

        plugin_path = clone_target
        for segment in subpath:
            plugin_path = plugin_path / segment
        if not plugin_path.is_dir():
            raise PluginError(
                f"Subpath does not exist in repo: {'/'.join(subpath)}",
            )
        return plugin_path

    # --- Internal: validation & test-load ---

    @staticmethod
    def _validate_plugin_dir(path: Path) -> None:
        """Sanity checks on a freshly-fetched plugin directory.

        Raises ``PluginError`` if the directory does not look like a
        valid plugin.
        """
        if not path.is_dir():
            raise PluginError(f"Not a directory: {path}")
        if not (path / "plugin.yaml").is_file():
            raise PluginError(
                f"plugin.yaml not found at root of {path}. If you're "
                "installing from a GitHub URL, point it at the "
                "subdirectory containing plugin.yaml (use the /tree/ URL "
                "from the GitHub web UI).",
            )
        if not (path / "plugin.py").is_file():
            raise PluginError(f"plugin.py not found at root of {path}")

        # Parse manifest and validate name/version
        try:
            with open(path / "plugin.yaml") as f:
                raw = yaml.safe_load(f)
        except Exception as exc:
            raise PluginError(f"Failed to parse plugin.yaml: {exc}") from exc
        if not isinstance(raw, dict):
            raise PluginError("plugin.yaml is not a YAML mapping")
        name = raw.get("name", "")
        version = raw.get("version", "")
        if not name or not isinstance(name, str):
            raise PluginError("plugin.yaml missing required 'name'")
        if not _VALID_NAME_RE.match(name):
            raise PluginError(
                f"Invalid plugin name {name!r}: must match "
                "[a-zA-Z][a-zA-Z0-9_-]*",
            )
        if not version or not isinstance(version, str):
            raise PluginError("plugin.yaml missing required 'version'")

    def _test_load(self, path: Path) -> None:
        """Sanity-import the plugin under a throwaway package name.

        Verifies that ``plugin.py`` parses and that ``create_plugin()``
        returns a valid ``Plugin`` instance.  Uses a unique package name
        so that sys.modules is not polluted with the real name we will
        register later.
        """
        plugin_file = path / "plugin.py"
        pkg_name = f"gilbert_plugin_test_{uuid.uuid4().hex}"

        from types import ModuleType

        pkg = ModuleType(pkg_name)
        pkg.__path__ = [str(path)]
        pkg.__package__ = pkg_name
        pkg.__file__ = str(path / "__init__.py")
        sys.modules[pkg_name] = pkg

        module_name = f"{pkg_name}.plugin"
        try:
            spec = importlib.util.spec_from_file_location(
                module_name, plugin_file, submodule_search_locations=[],
            )
            if spec is None or spec.loader is None:
                raise PluginError(f"Could not load module spec from {plugin_file}")

            module = importlib.util.module_from_spec(spec)
            module.__package__ = pkg_name
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
            except Exception as exc:
                raise PluginError(f"plugin.py raised on import: {exc}") from exc

            create_fn = getattr(module, "create_plugin", None)
            if create_fn is None:
                raise PluginError(
                    f"Plugin at {path} does not define create_plugin()",
                )
            try:
                plugin = create_fn()
            except Exception as exc:
                raise PluginError(
                    f"create_plugin() raised: {exc}",
                ) from exc
            if not isinstance(plugin, Plugin):
                raise PluginError(
                    f"create_plugin() in {path} did not return a Plugin instance",
                )
            self._validate_plugin(plugin)
        finally:
            # Clear the throwaway package and any submodules from
            # sys.modules so a future real load gets a clean slate.
            for mod_name in list(sys.modules):
                if mod_name == pkg_name or mod_name.startswith(pkg_name + "."):
                    sys.modules.pop(mod_name, None)


# --- Module-level helpers ---


def _archive_suffix(path: str) -> str | None:
    """Return the matching archive suffix (longest first) or None."""
    lowered = path.lower()
    for suf in _ARCHIVE_SUFFIXES:
        if lowered.endswith(suf):
            return suf
    return None


def _safe_extract_zip(archive: Path, dest: Path) -> None:
    """Extract a zip archive into ``dest``, refusing path traversal."""
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            _check_member_path(info.filename)
        zf.extractall(dest)


def _safe_extract_tar(archive: Path, dest: Path, mode: str) -> None:
    """Extract a tar archive into ``dest``, refusing path traversal."""
    if mode == "r:gz":
        with tarfile.open(archive, "r:gz") as tf:
            _extract_tar_safely(tf, dest)
    elif mode == "r:bz2":
        with tarfile.open(archive, "r:bz2") as tf:
            _extract_tar_safely(tf, dest)
    else:
        raise PluginError(f"Unsupported tar mode: {mode}")


def _extract_tar_safely(tf: tarfile.TarFile, dest: Path) -> None:
    """Validate every member of an opened tarfile and extract into ``dest``."""
    for member in tf.getmembers():
        _check_member_path(member.name)
        if member.islnk() or member.issym():
            _check_member_path(member.linkname)
    # Python 3.12+ supports a built-in data filter that also rejects
    # absolute paths, .. components, links escaping the dest, and
    # device files.  Use it when available.
    try:
        tf.extractall(dest, filter="data")
    except TypeError:
        tf.extractall(dest)


def _check_member_path(name: str) -> None:
    """Reject archive entries that would escape the extract directory."""
    if not name:
        return
    posix = name.replace("\\", "/")
    if posix.startswith("/"):
        raise PluginError(f"Refusing absolute path in archive: {name}")
    parts = posix.split("/")
    if any(p == ".." for p in parts):
        raise PluginError(f"Refusing parent traversal in archive: {name}")


def _unwrap_single_top_dir(extract_dir: Path) -> Path:
    """If ``extract_dir`` contains exactly one subdirectory and no files,
    return that subdirectory.  Otherwise return ``extract_dir``.

    GitHub source archives (and many release zips) wrap their contents
    in a single top-level directory like ``project-1.2.3/``; this helper
    transparently strips it so ``plugin.yaml`` lands at the root.
    """
    children = list(extract_dir.iterdir())
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extract_dir

"""Tests for PluginLoader — directory scanning, manifest parsing, dependency sort, config collection."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from gilbert.interfaces.plugin import Plugin, PluginContext, PluginMeta
from gilbert.plugins.loader import PluginError, PluginLoader, PluginManifest

# --- Helpers ---


class DummyPlugin(Plugin):
    """Minimal plugin for testing."""

    def __init__(self, name: str = "test-plugin", version: str = "1.0.0") -> None:
        self._name = name
        self._version = version
        self.setup_called = False
        self.teardown_called = False
        self.context: PluginContext | None = None

    def metadata(self) -> PluginMeta:
        return PluginMeta(name=self._name, version=self._version)

    async def setup(self, context: PluginContext) -> None:
        self.setup_called = True
        self.context = context

    async def teardown(self) -> None:
        self.teardown_called = True


def _write_manifest(plugin_dir: Path, manifest: dict[str, Any]) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    with open(plugin_dir / "plugin.yaml", "w") as f:
        yaml.dump(manifest, f)


def _write_plugin_py(plugin_dir: Path, name: str = "test-plugin", version: str = "1.0.0") -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    code = f'''
from gilbert.interfaces.plugin import Plugin, PluginMeta, PluginContext

class _Plugin(Plugin):
    def metadata(self) -> PluginMeta:
        return PluginMeta(name="{name}", version="{version}")
    async def setup(self, context: PluginContext) -> None:
        pass
    async def teardown(self) -> None:
        pass

def create_plugin() -> Plugin:
    return _Plugin()
'''
    (plugin_dir / "plugin.py").write_text(code)


# --- Tests ---


class TestManifestParsing:
    """Tests for parsing plugin.yaml manifests."""

    def test_parse_full_manifest(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "my-plugin"
        _write_manifest(plugin_dir, {
            "name": "my-plugin",
            "version": "2.0.0",
            "description": "A cool plugin",
            "provides": ["cool_capability"],
            "requires": ["entity_storage"],
            "depends_on": ["other-plugin"],
            "config": {"poll_interval": 30, "enabled": True},
        })

        manifest = PluginLoader._parse_manifest(plugin_dir, plugin_dir / "plugin.yaml")

        assert manifest.name == "my-plugin"
        assert manifest.version == "2.0.0"
        assert manifest.description == "A cool plugin"
        assert manifest.provides == ["cool_capability"]
        assert manifest.requires == ["entity_storage"]
        assert manifest.depends_on == ["other-plugin"]
        assert manifest.config == {"poll_interval": 30, "enabled": True}

    def test_parse_minimal_manifest(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "simple"
        _write_manifest(plugin_dir, {"name": "simple", "version": "0.1.0"})

        manifest = PluginLoader._parse_manifest(plugin_dir, plugin_dir / "plugin.yaml")

        assert manifest.name == "simple"
        assert manifest.version == "0.1.0"
        assert manifest.provides == []
        assert manifest.requires == []
        assert manifest.depends_on == []
        assert manifest.config == {}

    def test_manifest_defaults_name_from_dir(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "dir-name"
        _write_manifest(plugin_dir, {"version": "1.0.0"})

        manifest = PluginLoader._parse_manifest(plugin_dir, plugin_dir / "plugin.yaml")

        assert manifest.name == "dir-name"

    def test_invalid_manifest_not_a_mapping(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "bad"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.yaml").write_text("- just a list")

        with pytest.raises(PluginError, match="not a mapping"):
            PluginLoader._parse_manifest(plugin_dir, plugin_dir / "plugin.yaml")

    def test_to_plugin_meta(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "meta-test"
        _write_manifest(plugin_dir, {
            "name": "meta-test",
            "version": "1.0.0",
            "provides": ["cap1"],
            "requires": ["cap2"],
            "depends_on": ["dep1"],
        })

        manifest = PluginLoader._parse_manifest(plugin_dir, plugin_dir / "plugin.yaml")
        meta = manifest.to_plugin_meta()

        assert isinstance(meta, PluginMeta)
        assert meta.name == "meta-test"
        assert meta.provides == ["cap1"]
        assert meta.requires == ["cap2"]
        assert meta.depends_on == ["dep1"]


class TestDirectoryScanning:
    """Tests for scanning plugin directories."""

    def test_scan_finds_plugins(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path / "plugin-a", {"name": "plugin-a", "version": "1.0.0"})
        _write_manifest(tmp_path / "plugin-b", {"name": "plugin-b", "version": "2.0.0"})

        loader = PluginLoader()
        manifests = loader.scan_directories([str(tmp_path)])

        names = {m.name for m in manifests}
        assert names == {"plugin-a", "plugin-b"}

    def test_scan_skips_dirs_without_manifest(self, tmp_path: Path) -> None:
        (tmp_path / "no-manifest").mkdir()
        _write_manifest(tmp_path / "has-manifest", {"name": "has-manifest", "version": "1.0.0"})

        loader = PluginLoader()
        manifests = loader.scan_directories([str(tmp_path)])

        assert len(manifests) == 1
        assert manifests[0].name == "has-manifest"

    def test_scan_skips_files(self, tmp_path: Path) -> None:
        (tmp_path / "not-a-dir.txt").write_text("hello")
        _write_manifest(tmp_path / "real-plugin", {"name": "real-plugin", "version": "1.0.0"})

        loader = PluginLoader()
        manifests = loader.scan_directories([str(tmp_path)])

        assert len(manifests) == 1

    def test_scan_nonexistent_directory_warns(self, tmp_path: Path) -> None:
        loader = PluginLoader()
        manifests = loader.scan_directories([str(tmp_path / "does-not-exist")])

        assert manifests == []

    def test_scan_multiple_directories(self, tmp_path: Path) -> None:
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        _write_manifest(dir1 / "plugin-x", {"name": "plugin-x", "version": "1.0.0"})
        _write_manifest(dir2 / "plugin-y", {"name": "plugin-y", "version": "1.0.0"})

        loader = PluginLoader()
        manifests = loader.scan_directories([str(dir1), str(dir2)])

        names = {m.name for m in manifests}
        assert names == {"plugin-x", "plugin-y"}


class TestConfigCollection:
    """Tests for collecting default configs from manifests."""

    def test_collects_configs(self, tmp_path: Path) -> None:
        m1 = PluginManifest(tmp_path / "a", {"name": "a", "version": "1.0.0", "config": {"x": 1}})
        m2 = PluginManifest(tmp_path / "b", {"name": "b", "version": "1.0.0", "config": {"y": 2}})
        m3 = PluginManifest(tmp_path / "c", {"name": "c", "version": "1.0.0"})

        loader = PluginLoader()
        defaults = loader.collect_default_configs([m1, m2, m3])

        assert defaults == {"a": {"x": 1}, "b": {"y": 2}}

    def test_empty_manifests(self) -> None:
        loader = PluginLoader()
        assert loader.collect_default_configs([]) == {}


class TestTopologicalSort:
    """Tests for plugin dependency ordering."""

    def test_no_dependencies(self, tmp_path: Path) -> None:
        m1 = PluginManifest(tmp_path / "a", {"name": "a", "version": "1.0.0"})
        m2 = PluginManifest(tmp_path / "b", {"name": "b", "version": "1.0.0"})

        loader = PluginLoader()
        sorted_m = loader.topological_sort([m1, m2])

        assert len(sorted_m) == 2

    def test_linear_dependency(self, tmp_path: Path) -> None:
        m1 = PluginManifest(tmp_path / "a", {"name": "a", "version": "1.0.0"})
        m2 = PluginManifest(tmp_path / "b", {"name": "b", "version": "1.0.0", "depends_on": ["a"]})
        m3 = PluginManifest(tmp_path / "c", {"name": "c", "version": "1.0.0", "depends_on": ["b"]})

        loader = PluginLoader()
        sorted_m = loader.topological_sort([m3, m1, m2])  # deliberately unsorted input

        names = [m.name for m in sorted_m]
        assert names.index("a") < names.index("b")
        assert names.index("b") < names.index("c")

    def test_circular_dependency_raises(self, tmp_path: Path) -> None:
        m1 = PluginManifest(tmp_path / "a", {"name": "a", "version": "1.0.0", "depends_on": ["b"]})
        m2 = PluginManifest(tmp_path / "b", {"name": "b", "version": "1.0.0", "depends_on": ["a"]})

        loader = PluginLoader()
        with pytest.raises(PluginError, match="Circular"):
            loader.topological_sort([m1, m2])

    def test_missing_dependency_warns_but_continues(self, tmp_path: Path) -> None:
        m1 = PluginManifest(tmp_path / "a", {"name": "a", "version": "1.0.0", "depends_on": ["nonexistent"]})

        loader = PluginLoader()
        sorted_m = loader.topological_sort([m1])

        assert len(sorted_m) == 1
        assert sorted_m[0].name == "a"

    def test_diamond_dependency(self, tmp_path: Path) -> None:
        #     a
        #    / \
        #   b   c
        #    \ /
        #     d
        m_a = PluginManifest(tmp_path / "a", {"name": "a", "version": "1.0.0"})
        m_b = PluginManifest(tmp_path / "b", {"name": "b", "version": "1.0.0", "depends_on": ["a"]})
        m_c = PluginManifest(tmp_path / "c", {"name": "c", "version": "1.0.0", "depends_on": ["a"]})
        m_d = PluginManifest(tmp_path / "d", {"name": "d", "version": "1.0.0", "depends_on": ["b", "c"]})

        loader = PluginLoader()
        sorted_m = loader.topological_sort([m_d, m_c, m_b, m_a])

        names = [m.name for m in sorted_m]
        assert names.index("a") < names.index("b")
        assert names.index("a") < names.index("c")
        assert names.index("b") < names.index("d")
        assert names.index("c") < names.index("d")


class TestPluginLoading:
    """Tests for loading plugin.py modules."""

    @pytest.mark.asyncio
    async def test_load_from_path(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "test-plugin"
        _write_plugin_py(plugin_dir, name="test-plugin", version="1.0.0")

        loader = PluginLoader()
        plugin = await loader.load(str(plugin_dir))

        assert plugin.metadata().name == "test-plugin"
        assert plugin.metadata().version == "1.0.0"

    @pytest.mark.asyncio
    async def test_load_missing_plugin_py(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "empty"
        plugin_dir.mkdir()

        loader = PluginLoader()
        with pytest.raises(PluginError, match="No plugin.py"):
            await loader.load(str(plugin_dir))

    @pytest.mark.asyncio
    async def test_load_missing_create_plugin(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "no-factory"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.py").write_text("x = 1")

        loader = PluginLoader()
        with pytest.raises(PluginError, match="does not define create_plugin"):
            await loader.load(str(plugin_dir))

    def test_load_from_manifest(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "mf-plugin"
        _write_manifest(plugin_dir, {"name": "mf-plugin", "version": "1.0.0"})
        _write_plugin_py(plugin_dir, name="mf-plugin", version="1.0.0")

        loader = PluginLoader()
        manifest = PluginManifest(plugin_dir, {"name": "mf-plugin", "version": "1.0.0"})
        plugin = loader.load_from_manifest(manifest)

        assert plugin.metadata().name == "mf-plugin"

    @pytest.mark.asyncio
    async def test_validation_rejects_empty_name(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "bad-meta"
        plugin_dir.mkdir()
        code = '''
from gilbert.interfaces.plugin import Plugin, PluginMeta, PluginContext

class _P(Plugin):
    def metadata(self): return PluginMeta(name="", version="1.0.0")
    async def setup(self, context): pass
    async def teardown(self): pass

def create_plugin(): return _P()
'''
        (plugin_dir / "plugin.py").write_text(code)

        loader = PluginLoader()
        with pytest.raises(PluginError, match="missing 'name'"):
            await loader.load(str(plugin_dir))

"""Tests for PluginLoader.install_from_url and the archive/validation helpers."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from gilbert.plugins.loader import (
    InstalledPluginInfo,
    PluginError,
    PluginLoader,
    _archive_suffix,
    _check_member_path,
    _safe_extract_tar,
    _safe_extract_zip,
    _unwrap_single_top_dir,
)

# --- Plugin dir builder helper ---


PLUGIN_PY = """
from gilbert.interfaces.plugin import Plugin, PluginMeta, PluginContext

class _P(Plugin):
    def metadata(self) -> PluginMeta:
        return PluginMeta(name="{name}", version="{version}")
    async def setup(self, context: PluginContext) -> None:
        pass
    async def teardown(self) -> None:
        pass

def create_plugin() -> Plugin:
    return _P()
"""


def _build_plugin_dir(parent: Path, name: str = "test-plugin", version: str = "1.0.0") -> Path:
    plugin_dir = parent / name
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        yaml.safe_dump(
            {
                "name": name,
                "version": version,
                "description": "a test plugin",
            }
        )
    )
    (plugin_dir / "plugin.py").write_text(PLUGIN_PY.format(name=name, version=version))
    return plugin_dir


def _build_zip(zip_path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def _build_tar_gz(tar_path: Path, files: dict[str, str]) -> None:
    with tarfile.open(tar_path, "w:gz") as tf:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


# ── Module-level helpers ─────────────────────────────────────────────


class TestArchiveSuffix:
    def test_zip(self) -> None:
        assert _archive_suffix("/foo/bar.zip") == ".zip"

    def test_tar_gz(self) -> None:
        assert _archive_suffix("/release-1.0.0.tar.gz") == ".tar.gz"

    def test_tgz(self) -> None:
        assert _archive_suffix("/x.tgz") == ".tgz"

    def test_tar_bz2(self) -> None:
        assert _archive_suffix("/x.tar.bz2") == ".tar.bz2"

    def test_unknown(self) -> None:
        assert _archive_suffix("/x.gz") is None
        assert _archive_suffix("/x.tar") is None
        assert _archive_suffix("/some/repo") is None

    def test_case_insensitive(self) -> None:
        assert _archive_suffix("/Foo.ZIP") == ".zip"


class TestCheckMemberPath:
    def test_normal_path(self) -> None:
        _check_member_path("plugin.yaml")
        _check_member_path("subdir/file.py")

    def test_absolute_rejected(self) -> None:
        with pytest.raises(PluginError, match="absolute path"):
            _check_member_path("/etc/passwd")

    def test_parent_traversal_rejected(self) -> None:
        with pytest.raises(PluginError, match="parent traversal"):
            _check_member_path("../etc/passwd")

    def test_nested_parent_traversal_rejected(self) -> None:
        with pytest.raises(PluginError, match="parent traversal"):
            _check_member_path("subdir/../../etc/passwd")

    def test_windows_separator_normalized(self) -> None:
        with pytest.raises(PluginError, match="parent traversal"):
            _check_member_path("..\\foo\\bar")


class TestUnwrapSingleTopDir:
    def test_unwraps(self, tmp_path: Path) -> None:
        wrap = tmp_path / "wrap"
        wrap.mkdir()
        inner = wrap / "project-1.0"
        inner.mkdir()
        (inner / "file.txt").write_text("hi")

        result = _unwrap_single_top_dir(wrap)
        assert result == inner

    def test_no_unwrap_when_multiple_children(self, tmp_path: Path) -> None:
        wrap = tmp_path / "wrap"
        wrap.mkdir()
        (wrap / "a").mkdir()
        (wrap / "b").mkdir()

        result = _unwrap_single_top_dir(wrap)
        assert result == wrap

    def test_no_unwrap_when_file_at_root(self, tmp_path: Path) -> None:
        wrap = tmp_path / "wrap"
        wrap.mkdir()
        (wrap / "plugin.yaml").write_text("name: foo")
        (wrap / "subdir").mkdir()

        result = _unwrap_single_top_dir(wrap)
        assert result == wrap


# ── Safe extraction ──────────────────────────────────────────────────


class TestSafeExtractZip:
    def test_extracts_normal_zip(self, tmp_path: Path) -> None:
        archive = tmp_path / "a.zip"
        _build_zip(archive, {"plugin.yaml": "name: x\nversion: 1.0.0\n", "plugin.py": "x = 1"})

        dest = tmp_path / "out"
        dest.mkdir()
        _safe_extract_zip(archive, dest)

        assert (dest / "plugin.yaml").exists()
        assert (dest / "plugin.py").exists()

    def test_rejects_absolute_path(self, tmp_path: Path) -> None:
        archive = tmp_path / "a.zip"
        _build_zip(archive, {"/etc/passwd": "x"})

        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(PluginError, match="absolute path"):
            _safe_extract_zip(archive, dest)

    def test_rejects_parent_traversal(self, tmp_path: Path) -> None:
        archive = tmp_path / "a.zip"
        _build_zip(archive, {"../escaped.txt": "x"})

        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(PluginError, match="parent traversal"):
            _safe_extract_zip(archive, dest)


class TestSafeExtractTar:
    def test_extracts_normal_tar_gz(self, tmp_path: Path) -> None:
        archive = tmp_path / "a.tar.gz"
        _build_tar_gz(archive, {"plugin.yaml": "name: x\nversion: 1.0.0\n", "plugin.py": "x = 1"})

        dest = tmp_path / "out"
        dest.mkdir()
        _safe_extract_tar(archive, dest, "r:gz")

        assert (dest / "plugin.yaml").exists()
        assert (dest / "plugin.py").exists()

    def test_rejects_parent_traversal(self, tmp_path: Path) -> None:
        archive = tmp_path / "a.tar.gz"
        _build_tar_gz(archive, {"../escaped.txt": "x"})

        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(PluginError, match="parent traversal"):
            _safe_extract_tar(archive, dest, "r:gz")


# ── _validate_plugin_dir ─────────────────────────────────────────────


class TestValidatePluginDir:
    def test_happy_path(self, tmp_path: Path) -> None:
        plugin_dir = _build_plugin_dir(tmp_path, name="ok-plugin")
        PluginLoader._validate_plugin_dir(plugin_dir)

    def test_missing_yaml(self, tmp_path: Path) -> None:
        d = tmp_path / "bad"
        d.mkdir()
        (d / "plugin.py").write_text("")
        with pytest.raises(PluginError, match="plugin.yaml not found"):
            PluginLoader._validate_plugin_dir(d)

    def test_missing_py(self, tmp_path: Path) -> None:
        d = tmp_path / "bad"
        d.mkdir()
        (d / "plugin.yaml").write_text("name: bad\nversion: 1.0.0\n")
        with pytest.raises(PluginError, match="plugin.py not found"):
            PluginLoader._validate_plugin_dir(d)

    def test_missing_name(self, tmp_path: Path) -> None:
        d = tmp_path / "bad"
        d.mkdir()
        (d / "plugin.yaml").write_text("version: 1.0.0\n")
        (d / "plugin.py").write_text("")
        with pytest.raises(PluginError, match="missing required 'name'"):
            PluginLoader._validate_plugin_dir(d)

    def test_missing_version(self, tmp_path: Path) -> None:
        d = tmp_path / "bad"
        d.mkdir()
        (d / "plugin.yaml").write_text("name: bad\n")
        (d / "plugin.py").write_text("")
        with pytest.raises(PluginError, match="missing required 'version'"):
            PluginLoader._validate_plugin_dir(d)

    def test_invalid_name(self, tmp_path: Path) -> None:
        d = tmp_path / "bad"
        d.mkdir()
        (d / "plugin.yaml").write_text("name: 'bad name'\nversion: 1.0.0\n")
        (d / "plugin.py").write_text("")
        with pytest.raises(PluginError, match="Invalid plugin name"):
            PluginLoader._validate_plugin_dir(d)


# ── _test_load (sanity import) ────────────────────────────────────────


class TestTestLoad:
    def test_loads_valid_plugin_without_polluting_sys_modules(self, tmp_path: Path) -> None:
        import sys

        plugin_dir = _build_plugin_dir(tmp_path, name="probe-plugin")
        loader = PluginLoader()

        before = set(sys.modules)
        loader._test_load(plugin_dir)
        after = set(sys.modules)

        # No new module survived under the throwaway prefix.
        new = after - before
        leaked = [m for m in new if m.startswith("gilbert_plugin_test_")]
        assert leaked == []

    def test_rejects_plugin_without_create_plugin(self, tmp_path: Path) -> None:
        d = tmp_path / "bad"
        d.mkdir()
        (d / "plugin.yaml").write_text("name: bad\nversion: 1.0.0\n")
        (d / "plugin.py").write_text("x = 1")

        loader = PluginLoader()
        with pytest.raises(PluginError, match="does not define create_plugin"):
            loader._test_load(d)


# ── install_from_url end-to-end ──────────────────────────────────────


class TestInstallFromUrl:
    @pytest.mark.asyncio
    async def test_install_from_zip(self, tmp_path: Path) -> None:
        # Build a zip containing a single top-level "wrapper-1.0/" directory
        # with the plugin inside, mimicking the GitHub source-zip convention.
        src = tmp_path / "src"
        plugin_dir = _build_plugin_dir(src, name="zipped-plugin", version="2.0.0")
        archive = tmp_path / "release.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            wrapper = "wrapper-1.0"
            for f in plugin_dir.rglob("*"):
                if f.is_file():
                    arcname = f"{wrapper}/{f.name}"
                    zf.write(f, arcname)

        install_dir = tmp_path / "installed"
        loader = PluginLoader()

        # Patch _fetch_archive's HTTP download to copy our local archive
        # into the requested staging path instead of going to the network.
        original_fetch = loader._fetch_archive

        async def fake_fetch_archive(url: str, stage_path: Path, suffix: str) -> Path:
            import shutil

            archive_file = stage_path / f"download{suffix}"
            shutil.copy(archive, archive_file)
            extract_dir = stage_path / "extracted"
            extract_dir.mkdir()
            _safe_extract_zip(archive_file, extract_dir)
            return _unwrap_single_top_dir(extract_dir)

        loader._fetch_archive = fake_fetch_archive  # type: ignore[method-assign]

        try:
            info = await loader.install_from_url(
                "https://example.com/release.zip",
                install_dir,
            )
        finally:
            loader._fetch_archive = original_fetch  # type: ignore[method-assign]

        assert isinstance(info, InstalledPluginInfo)
        assert info.name == "zipped-plugin"
        assert info.version == "2.0.0"
        assert info.install_path == (install_dir / "zipped-plugin").resolve()
        assert (info.install_path / "plugin.yaml").exists()
        assert (info.install_path / "plugin.py").exists()

    @pytest.mark.asyncio
    async def test_install_refuses_duplicate_without_force(self, tmp_path: Path) -> None:
        # Pre-create the install dir + a plugin directory that would collide.
        install_dir = tmp_path / "installed"
        install_dir.mkdir()
        (install_dir / "dupe-plugin").mkdir()

        # Build a plugin source the loader can fetch.
        src = tmp_path / "src"
        plugin_dir = _build_plugin_dir(src, name="dupe-plugin", version="1.0.0")

        loader = PluginLoader()

        async def fake_fetch_to(url: str, stage_path: Path) -> Path:
            import shutil

            target = stage_path / "fetched"
            shutil.copytree(plugin_dir, target)
            return target

        loader._fetch_to = fake_fetch_to  # type: ignore[method-assign]

        with pytest.raises(PluginError, match="already installed"):
            await loader.install_from_url(
                "https://example.com/anything.zip",
                install_dir,
            )

    @pytest.mark.asyncio
    async def test_install_force_overwrites(self, tmp_path: Path) -> None:
        install_dir = tmp_path / "installed"
        install_dir.mkdir()
        existing = install_dir / "force-plugin"
        existing.mkdir()
        (existing / "old-marker.txt").write_text("hi")

        src = tmp_path / "src"
        plugin_dir = _build_plugin_dir(src, name="force-plugin", version="2.0.0")

        loader = PluginLoader()

        async def fake_fetch_to(url: str, stage_path: Path) -> Path:
            import shutil

            target = stage_path / "fetched"
            shutil.copytree(plugin_dir, target)
            return target

        loader._fetch_to = fake_fetch_to  # type: ignore[method-assign]

        info = await loader.install_from_url(
            "https://example.com/anything.zip",
            install_dir,
            force=True,
        )

        assert info.name == "force-plugin"
        assert not (info.install_path / "old-marker.txt").exists()
        assert (info.install_path / "plugin.yaml").exists()


# ── uninstall ────────────────────────────────────────────────────────


class TestUninstall:
    @pytest.mark.asyncio
    async def test_uninstall_removes_directory(self, tmp_path: Path) -> None:
        install_dir = tmp_path / "installed"
        install_dir.mkdir()
        target = install_dir / "to-remove"
        target.mkdir()
        (target / "f.txt").write_text("x")

        loader = PluginLoader()
        await loader.uninstall("to-remove", install_dir)

        assert not target.exists()

    @pytest.mark.asyncio
    async def test_uninstall_invalid_name(self, tmp_path: Path) -> None:
        install_dir = tmp_path / "installed"
        install_dir.mkdir()

        loader = PluginLoader()
        with pytest.raises(PluginError, match="Invalid plugin name"):
            await loader.uninstall("../etc", install_dir)

    @pytest.mark.asyncio
    async def test_uninstall_missing_plugin(self, tmp_path: Path) -> None:
        install_dir = tmp_path / "installed"
        install_dir.mkdir()

        loader = PluginLoader()
        with pytest.raises(PluginError, match="not installed"):
            await loader.uninstall("ghost", install_dir)


# ── _fetch_to URL routing ────────────────────────────────────────────


class TestFetchTo:
    @pytest.mark.asyncio
    async def test_unsupported_scheme(self, tmp_path: Path) -> None:
        loader = PluginLoader()
        with pytest.raises(PluginError, match="Unsupported plugin URL scheme"):
            await loader._fetch_to("ftp://example.com/x.zip", tmp_path)

    @pytest.mark.asyncio
    async def test_unsupported_url(self, tmp_path: Path) -> None:
        loader = PluginLoader()
        with pytest.raises(PluginError, match="Unsupported plugin URL"):
            await loader._fetch_to("https://example.com/something", tmp_path)

    @pytest.mark.asyncio
    async def test_zip_routes_to_archive(self, tmp_path: Path) -> None:
        loader = PluginLoader()
        called: dict[str, Any] = {}

        async def fake_fetch_archive(url: str, stage_path: Path, suffix: str) -> Path:
            called["url"] = url
            called["suffix"] = suffix
            return tmp_path

        loader._fetch_archive = fake_fetch_archive  # type: ignore[method-assign]
        await loader._fetch_to("https://example.com/foo.tar.gz", tmp_path)

        assert called["url"] == "https://example.com/foo.tar.gz"
        assert called["suffix"] == ".tar.gz"

    @pytest.mark.asyncio
    async def test_github_routes_to_github(self, tmp_path: Path) -> None:
        loader = PluginLoader()
        called: dict[str, Any] = {}

        async def fake_fetch_github(url: str, stage_path: Path) -> Path:
            called["url"] = url
            return tmp_path

        loader._fetch_github = fake_fetch_github  # type: ignore[method-assign]
        await loader._fetch_to("https://github.com/foo/bar/tree/main/plugins/x", tmp_path)

        assert called["url"] == "https://github.com/foo/bar/tree/main/plugins/x"

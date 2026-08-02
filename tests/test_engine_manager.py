from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

import godot_game_test_lab.engine_manager as engine_manager
from godot_game_test_lab.engine_manager import (
    EngineInstallation,
    EngineLock,
    EngineProvisionError,
    HostSpec,
    _asset_names,
    _download,
    _find_editor_executable,
    _safe_extract_zip,
    _trusted_download_url,
    bootstrap_host,
    install_engine,
    list_installations,
    load_engine_lock,
    prepare_estate,
    select_engine_for_project,
)


def _lock() -> EngineLock:
    return EngineLock(
        schema_version="1.0",
        minimum_version="4.6.2",
        default_version="4.6.3",
        channels={"4.6": "4.6.3", "4.7": "4.7.1"},
        default_flavors=("standard", "mono"),
        install_export_templates=True,
        self_contained=True,
        release_repository="godotengine/godot-builds",
    )


def _write_zip(path: Path, members: dict[str, tuple[bytes, int]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, (content, mode) in members.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            archive.writestr(info, content)


def _write_offline_release(root: Path, version: str = "4.6.3") -> None:
    host = HostSpec("linux", "x86_64", "linux.x86_64", "")
    assets: list[str] = []
    for flavor in ("standard", "mono"):
        editor, templates = _asset_names(version, flavor, host)
        executable = f"Godot_v{version}-stable"
        if flavor == "mono":
            executable += "_mono"
        executable += "_linux_x86_64"
        script = f"#!/bin/sh\nprintf '%s\\n' '{version}.stable.official'\n".encode()
        _write_zip(
            root / editor,
            {
                executable: (script, stat.S_IFREG | 0o755),
                "GodotSharp/Api/README.txt": (b"fixture\n", stat.S_IFREG | 0o644),
            },
        )
        _write_zip(
            root / templates,
            {
                "templates/version.txt": (
                    f"{version}.stable\n".encode(),
                    stat.S_IFREG | 0o644,
                ),
                "templates/linux_debug.x86_64": (b"template\n", stat.S_IFREG | 0o755),
            },
        )
        assets.extend([editor, templates])
    lines = []
    for name in assets:
        digest = hashlib.sha512((root / name).read_bytes()).hexdigest()
        lines.append(f"{digest}  {name}")
    (root / "SHA512-SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _project(root: Path, *, branch: str = "4.6", csharp: bool = False) -> Path:
    root.mkdir(parents=True)
    (root / "project.godot").write_text(
        "config_version=5\n"
        "[application]\n"
        'config/name="Fixture"\n'
        'run/main_scene="res://main.tscn"\n'
        "[rendering]\n"
        f'config/features=PackedStringArray("{branch}")\n',
        encoding="utf-8",
    )
    (root / "main.tscn").write_text(
        '[gd_scene format=3]\n[node name="Main" type="Node"]\n',
        encoding="utf-8",
    )
    if csharp:
        (root / "Fixture.csproj").write_text("<Project />\n", encoding="utf-8")
    return root


def test_asset_names_cover_windows_and_linux_x64_and_arm64() -> None:
    cases = [
        (
            HostSpec("windows", "x86_64", "win64", ".exe"),
            "standard",
            "Godot_v4.6.3-stable_win64.exe.zip",
        ),
        (
            HostSpec("windows", "arm64", "windows.arm64", ".exe"),
            "mono",
            "Godot_v4.6.3-stable_mono_windows_arm64.zip",
        ),
        (
            HostSpec("linux", "x86_64", "linux.x86_64", ""),
            "mono",
            "Godot_v4.6.3-stable_mono_linux_x86_64.zip",
        ),
        (
            HostSpec("linux", "arm64", "linux.arm64", ""),
            "standard",
            "Godot_v4.6.3-stable_linux.arm64.zip",
        ),
    ]
    for host, flavor, expected in cases:
        editor, _templates = _asset_names("4.6.3", flavor, host)
        assert editor == expected


def test_download_redirect_allowlist_is_restricted_to_official_hosts() -> None:
    assert _trusted_download_url("https://github.com/godotengine/godot-builds")
    assert _trusted_download_url("https://release-assets.githubusercontent.com/file")
    assert _trusted_download_url("https://objects.githubusercontent.com/file")
    assert _trusted_download_url(
        "https://godot-releases.nbg1.your-objectstorage.com/4.6.3/file.zip"
    )
    assert not _trusted_download_url("https://attacker.your-objectstorage.com/file.zip")
    assert not _trusted_download_url("https://evil.githubusercontent.com/file")
    assert not _trusted_download_url("https://raw.githubusercontent.com/file")
    assert not _trusted_download_url("https://example.com/file.zip")
    assert not _trusted_download_url("http://github.com/godotengine/godot-builds")


def test_download_rejects_invalid_content_length(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class Response:
        headers = {"Content-Length": "not-a-number"}

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def geturl(self) -> str:
            return "https://release-assets.githubusercontent.com/file"

    monkeypatch.setattr(engine_manager.urllib.request, "urlopen", lambda *_a, **_k: Response())

    with pytest.raises(EngineProvisionError, match="invalid Content-Length"):
        _download(
            "https://github.com/godotengine/godot-builds/file",
            tmp_path / "download.zip",
            maximum=1024,
            retries=1,
        )


def test_engine_lock_rejects_cross_branch_and_cross_major_mappings(tmp_path: Path) -> None:
    value = {
        "schemaVersion": "1.0",
        "minimumVersion": "4.6.2",
        "defaultVersion": "4.7.1",
        "channels": {"4.6": "4.7.1"},
        "defaultFlavors": ["standard", "mono"],
        "installExportTemplates": True,
        "selfContained": True,
        "releaseRepository": "godotengine/godot-builds",
    }
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(EngineProvisionError, match="same release branch"):
        load_engine_lock(path)

    value["channels"] = {"4.6": "4.6.3", "5.0": "5.0.0"}
    value["defaultVersion"] = "4.6.3"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(EngineProvisionError, match="governed major version"):
        load_engine_lock(path)


def test_safe_extraction_rejects_traversal_symlink_encryption_and_collision(
    tmp_path: Path,
) -> None:
    traversal = tmp_path / "traversal.zip"
    _write_zip(traversal, {"../escape": (b"x", stat.S_IFREG | 0o644)})
    with pytest.raises(EngineProvisionError, match="Unsafe archive path"):
        _safe_extract_zip(traversal, tmp_path / "one")

    symlink = tmp_path / "symlink.zip"
    _write_zip(symlink, {"link": (b"target", stat.S_IFLNK | 0o777)})
    with pytest.raises(EngineProvisionError, match="symbolic link"):
        _safe_extract_zip(symlink, tmp_path / "two")

    collision = tmp_path / "collision.zip"
    _write_zip(
        collision,
        {
            "Folder/File.txt": (b"one", stat.S_IFREG | 0o644),
            "folder/file.TXT": (b"two", stat.S_IFREG | 0o644),
        },
    )
    with pytest.raises(EngineProvisionError, match="case-colliding"):
        _safe_extract_zip(collision, tmp_path / "three")


def test_offline_install_is_verified_self_contained_atomic_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "release"
    source.mkdir()
    _write_offline_release(source)
    monkeypatch.setattr(
        engine_manager,
        "detect_host",
        lambda: HostSpec("linux", "x86_64", "linux.x86_64", ""),
    )

    installation = install_engine(
        version="4.6.3",
        flavor="standard",
        root=tmp_path / "engines",
        source_dir=source,
        offline=True,
        lock=_lock(),
    )

    executable = Path(installation.executable)
    assert executable.is_file()
    assert (executable.parent / "._sc_").is_file()
    assert installation.executable_sha256 == hashlib.sha256(executable.read_bytes()).hexdigest()
    assert Path(installation.export_templates or "").joinpath("version.txt").is_file()
    receipt = json.loads(
        Path(installation.root).joinpath("engine-installation.json").read_text()
    )
    assert receipt["schema_version"] == "1.2"
    assert receipt["editor_sha512"]
    assert receipt["payload_sha256"]
    assert receipt["template_payload_sha256"]
    assert not list((tmp_path / "engines").glob(".*.staging-*"))

    reused = install_engine(
        version="4.6.3",
        flavor="standard",
        root=tmp_path / "engines",
        source_dir=source,
        offline=True,
        lock=_lock(),
    )
    assert reused.executable == installation.executable
    assert reused.installed_at == installation.installed_at
    assert list_installations(tmp_path / "engines")[0]["status"] == "ready"


def test_checksum_and_managed_payload_tampering_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "release"
    source.mkdir()
    _write_offline_release(source)
    monkeypatch.setattr(
        engine_manager,
        "detect_host",
        lambda: HostSpec("linux", "x86_64", "linux.x86_64", ""),
    )
    root = tmp_path / "engines"
    installed = install_engine(
        version="4.6.3",
        flavor="standard",
        root=root,
        source_dir=source,
        offline=True,
        lock=_lock(),
    )
    Path(installed.executable).write_text("#!/bin/sh\necho 4.6.3\n# tampered\n")
    assert list_installations(root)[0]["status"] == "invalid"

    receipt_path = Path(installed.root) / "engine-installation.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["root"] = str(tmp_path / "elsewhere")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    invalid = list_installations(root)[0]
    assert invalid["status"] == "invalid"
    assert "receipt directory" in invalid["error"]

    clean_source = tmp_path / "corrupt-release"
    clean_source.mkdir()
    _write_offline_release(clean_source)
    editor, _templates = _asset_names(
        "4.6.3", "standard", HostSpec("linux", "x86_64", "linux.x86_64", "")
    )
    (clean_source / editor).write_bytes((clean_source / editor).read_bytes() + b"bad")
    with pytest.raises(EngineProvisionError, match="SHA512 mismatch"):
        install_engine(
            version="4.6.3",
            flavor="standard",
            root=tmp_path / "corrupt-engines",
            source_dir=clean_source,
            offline=True,
            lock=_lock(),
        )


def test_project_selection_uses_compatible_maintenance_and_mono_for_csharp(
    tmp_path: Path,
) -> None:
    gdscript = _project(tmp_path / "gdscript", branch="4.6")
    csharp = _project(tmp_path / "csharp", branch="4.7", csharp=True)

    standard = select_engine_for_project(gdscript, lock=_lock())
    mono = select_engine_for_project(csharp, lock=_lock())

    assert (standard.version, standard.flavor) == ("4.6.3", "standard")
    assert (mono.version, mono.flavor) == ("4.7.1", "mono")



def test_project_selection_fails_closed_for_unmapped_branch_and_detects_csharp_feature(
    tmp_path: Path,
) -> None:
    unsupported = _project(tmp_path / "unsupported", branch="4.8")
    with pytest.raises(EngineProvisionError, match="unmapped Godot branch 4.8"):
        select_engine_for_project(unsupported, lock=_lock())

    csharp = _project(tmp_path / "feature-csharp", branch="4.6")
    project_file = csharp / "project.godot"
    project_file.write_text(
        project_file.read_text(encoding="utf-8").replace(
            'PackedStringArray("4.6")',
            'PackedStringArray("4.6", "C#")',
        ),
        encoding="utf-8",
    )
    selection = select_engine_for_project(csharp, lock=_lock())
    assert selection.flavor == "mono"
    assert selection.csharp is True


def test_offline_mirror_root_and_template_upgrade_are_supported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mirror_root = tmp_path / "mirror"
    source = mirror_root / "4.6.3-stable"
    source.mkdir(parents=True)
    _write_offline_release(source)
    monkeypatch.setattr(
        engine_manager,
        "detect_host",
        lambda: HostSpec("linux", "x86_64", "linux.x86_64", ""),
    )
    engine_root = tmp_path / "engines"

    initial = install_engine(
        version="4.6.3",
        flavor="standard",
        root=engine_root,
        install_templates=False,
        source_dir=mirror_root,
        offline=True,
        lock=_lock(),
    )
    assert initial.export_templates is None

    upgraded = install_engine(
        version="4.6.3",
        flavor="standard",
        root=engine_root,
        install_templates=True,
        source_dir=mirror_root,
        offline=True,
        lock=_lock(),
    )
    assert upgraded.export_templates is not None
    templates = Path(upgraded.export_templates)
    assert (templates / "version.txt").is_file()
    (templates / "linux_debug.x86_64").write_bytes(b"tampered\n")
    assert list_installations(engine_root)[0]["status"] == "invalid"


def test_bootstrap_installs_requested_flavors_without_assuming_standard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "release"
    source.mkdir()
    _write_offline_release(source)
    monkeypatch.setattr(
        engine_manager,
        "detect_host",
        lambda: HostSpec("linux", "x86_64", "linux.x86_64", ""),
    )

    payload = bootstrap_host(
        version="4.6.3",
        root=tmp_path / "engines",
        flavors=("mono",),
        source_dir=source,
        offline=True,
    )

    assert payload["status"] == "ready"
    assert payload["environment"]["GODOT_BIN"] is None
    assert payload["environment"]["GODOT_MONO_BIN"]


def test_prepare_estate_deduplicates_required_installations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    estate = tmp_path / "estate"
    _project(estate / "one", branch="4.6")
    _project(estate / "two", branch="4.6")
    _project(estate / "three", branch="4.7", csharp=True)
    calls: list[tuple[str, str]] = []

    def fake_install_engine(**kwargs) -> EngineInstallation:
        version = str(kwargs["version"])
        flavor = str(kwargs["flavor"])
        calls.append((version, flavor))
        root = tmp_path / f"{version}-{flavor}"
        return EngineInstallation(
            schema_version="1.1",
            version=version,
            flavor=flavor,
            platform="linux",
            architecture="x86_64",
            root=str(root),
            executable=str(root / "godot"),
            export_templates=None,
            editor_archive="editor.zip",
            editor_sha512="0" * 128,
            template_archive=None,
            template_sha512=None,
            template_payload_sha256=None,
            source="fixture",
            executable_sha256="0" * 64,
            payload_sha256="0" * 64,
            self_contained=True,
            installed_at="2026-08-01T00:00:00+00:00",
            verified_at="2026-08-01T00:00:00+00:00",
        )

    monkeypatch.setattr(engine_manager, "install_engine", fake_install_engine)

    report = prepare_estate(estate, root=tmp_path / "engines")

    assert report["status"] == "passed"
    assert report["projectCount"] == 3
    assert calls == [("4.6.3", "standard"), ("4.7.1", "mono")]


def test_engine_lock_is_packaged_and_canonical() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "src" / "godot_game_test_lab" / "godot-engine-lock.json"
    value = json.loads(path.read_text())
    assert value["minimumVersion"] == "4.6.2"
    assert value["defaultVersion"] == "4.6.3"
    assert value["channels"] == {"4.6": "4.6.3", "4.7": "4.7.1"}
    assert value["releaseRepository"] == "godotengine/godot-builds"


def test_linux_arm64_editor_executable_is_discovered(tmp_path: Path) -> None:
    executable = tmp_path / "Godot_v4.6.3-stable_linux.arm64"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")

    observed = _find_editor_executable(
        tmp_path,
        HostSpec("linux", "arm64", "linux.arm64", ""),
        "standard",
    )

    assert observed == executable
    assert observed.stat().st_mode & stat.S_IXUSR


def test_online_cache_self_heals_corrupt_manifest_and_asset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "release"
    source.mkdir()
    _write_offline_release(source)
    cache = tmp_path / "cache"
    cache.mkdir()
    asset_name = "Godot_v4.6.3-stable_linux.x86_64.zip"
    (cache / "SHA512-SUMS.txt").write_text("corrupt\n", encoding="utf-8")
    (cache / asset_name).write_bytes(b"corrupt")
    downloads: list[str] = []

    def fake_download(_url: str, destination: Path, **_kwargs) -> None:
        downloads.append(destination.name)
        destination.write_bytes((source / destination.name).read_bytes())

    monkeypatch.setattr(engine_manager, "_download", fake_download)

    asset, expected, _source = engine_manager._obtain_release_file(
        _lock().release_repository,
        "4.6.3",
        asset_name,
        cache,
        source_dir=None,
        offline=False,
    )

    assert asset == cache / asset_name
    assert expected == hashlib.sha512((source / asset_name).read_bytes()).hexdigest()
    assert downloads == ["SHA512-SUMS.txt", asset_name]


def test_explicit_engine_versions_must_stay_within_governed_major(tmp_path: Path) -> None:
    project = _project(tmp_path / "game", branch="4.6")

    with pytest.raises(EngineProvisionError, match="governed Godot major 4"):
        select_engine_for_project(project, version="5.0.0", lock=_lock())

    with pytest.raises(EngineProvisionError, match="governed Godot major 4"):
        install_engine(
            version="5.0.0",
            flavor="standard",
            root=tmp_path / "engines",
            lock=_lock(),
        )

    with pytest.raises(EngineProvisionError, match="governed Godot major 4"):
        engine_manager.mirror_release_assets(
            tmp_path / "mirror",
            versions=("5.0.0",),
            platforms=("linux-x86_64",),
            flavors=("standard",),
            include_templates=False,
            lock_path=None,
        )


def test_engine_paths_fail_closed_when_a_parent_is_a_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    project = _project(real / "game", branch="4.6")

    with pytest.raises(EngineProvisionError, match="symbolic link"):
        select_engine_for_project(linked / "game", lock=_lock())

    source = tmp_path / "release"
    source.mkdir()
    _write_offline_release(source)
    with pytest.raises(EngineProvisionError, match="symbolic link"):
        install_engine(
            version="4.6.3",
            flavor="standard",
            root=linked / "engines",
            source_dir=source,
            offline=True,
            lock=_lock(),
        )

    assert project.is_dir()

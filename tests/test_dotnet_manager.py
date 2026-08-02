from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

import godot_game_test_lab.dotnet_manager as dotnet_manager
from godot_game_test_lab.dotnet_manager import (
    DotNetHost,
    DotNetProvisionError,
    _safe_extract_zip,
    dotnet_environment,
    ensure_dotnet_sdk,
    list_dotnet_installations,
)


def _write_offline_sdk(root: Path, version: str = "8.0.999") -> None:
    archive_name = f"dotnet-sdk-{version}-linux-x64.zip"
    archive_path = root / archive_name
    script = f"#!/bin/sh\nprintf '%s\\n' '{version}'\n".encode()
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo("dotnet")
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        archive.writestr(info, script)
        info = zipfile.ZipInfo("sdk/fixture.txt")
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        archive.writestr(info, b"fixture\n")
    digest = hashlib.sha512(archive_path.read_bytes()).hexdigest()
    metadata = {
        "latest-sdk": version,
        "releases": [
            {
                "sdk": {
                    "version": version,
                    "files": [
                        {
                            "rid": "linux-x64",
                            "url": (
                                "https://builds.dotnet.microsoft.com/dotnet/Sdk/"
                                f"{version}/{archive_name}"
                            ),
                            "hash": digest,
                        }
                    ],
                }
            }
        ],
    }
    (root / "releases.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )


def test_offline_dotnet_install_is_verified_atomic_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "offline"
    source.mkdir()
    _write_offline_sdk(source)
    monkeypatch.setattr(
        dotnet_manager,
        "detect_dotnet_host",
        lambda: DotNetHost("linux", "x64", "linux-x64", "dotnet"),
    )

    installed = ensure_dotnet_sdk(
        root=tmp_path / "dotnet",
        source_dir=source,
        offline=True,
    )

    executable = Path(installed.executable)
    assert executable.is_file()
    assert installed.version == "8.0.999"
    assert installed.payload_sha256
    assert list_dotnet_installations(tmp_path / "dotnet")[0]["status"] == "ready"
    environment = dotnet_environment(tmp_path / "dotnet")
    assert environment["DOTNET_BIN"] == str(executable)
    assert environment["DOTNET_ROOT"] == installed.root
    assert environment["DOTNET_MULTILEVEL_LOOKUP"] == "0"
    assert environment["DOTNET_NOLOGO"] == "1"
    assert environment["DOTNET_CLI_HOME"].endswith("cli-home")
    assert environment["NUGET_PACKAGES"].endswith("nuget-packages")

    reused = ensure_dotnet_sdk(
        root=tmp_path / "dotnet",
        source_dir=source,
        offline=True,
    )
    assert reused.installed_at == installed.installed_at
    assert not list((tmp_path / "dotnet").rglob("*.staging-*"))


def test_dotnet_payload_and_archive_tampering_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "offline"
    source.mkdir()
    _write_offline_sdk(source)
    monkeypatch.setattr(
        dotnet_manager,
        "detect_dotnet_host",
        lambda: DotNetHost("linux", "x64", "linux-x64", "dotnet"),
    )
    root = tmp_path / "dotnet"
    installed = ensure_dotnet_sdk(root=root, source_dir=source, offline=True)
    Path(installed.executable).write_text("#!/bin/sh\necho tampered\n", encoding="utf-8")
    assert list_dotnet_installations(root)[0]["status"] == "invalid"

    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    _write_offline_sdk(corrupt)
    archive = next(corrupt.glob("dotnet-sdk-*.zip"))
    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(DotNetProvisionError, match="SHA512 mismatch"):
        ensure_dotnet_sdk(
            root=tmp_path / "corrupt-root",
            source_dir=corrupt,
            offline=True,
        )


def test_dotnet_zip_rejects_traversal_links_encryption_and_portability(
    tmp_path: Path,
) -> None:
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape", b"x")
    with pytest.raises(DotNetProvisionError, match="Unsafe"):
        _safe_extract_zip(traversal, tmp_path / "one")

    symlink = tmp_path / "symlink.zip"
    with zipfile.ZipFile(symlink, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, b"target")
    with pytest.raises(DotNetProvisionError, match="symbolic link"):
        _safe_extract_zip(symlink, tmp_path / "two")

    collision = tmp_path / "collision.zip"
    with zipfile.ZipFile(collision, "w") as archive:
        archive.writestr("Folder/File.txt", b"one")
        archive.writestr("folder/file.TXT", b"two")
    with pytest.raises(DotNetProvisionError, match="colliding"):
        _safe_extract_zip(collision, tmp_path / "three")

    reserved = tmp_path / "reserved.zip"
    with zipfile.ZipFile(reserved, "w") as archive:
        archive.writestr("CON/file.txt", b"x")
    with pytest.raises(DotNetProvisionError, match="Unsafe"):
        _safe_extract_zip(reserved, tmp_path / "four")


def test_dotnet_zip_rejects_unicode_normalization_collisions(tmp_path: Path) -> None:
    collision = tmp_path / "unicode-collision.zip"
    with zipfile.ZipFile(collision, "w") as archive:
        archive.writestr("caf\u00e9/file.txt", b"one")
        archive.writestr("cafe\u0301/file.txt", b"two")

    with pytest.raises(DotNetProvisionError, match="colliding"):
        _safe_extract_zip(collision, tmp_path / "unicode-output")


def test_dotnet_current_receipt_symlink_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "offline"
    source.mkdir()
    _write_offline_sdk(source)
    monkeypatch.setattr(
        dotnet_manager,
        "detect_dotnet_host",
        lambda: DotNetHost("linux", "x64", "linux-x64", "dotnet"),
    )
    root = tmp_path / "dotnet"
    root.mkdir()
    target = tmp_path / "outside.json"
    target.write_text("{}\n", encoding="utf-8")
    current = root / "current-8.0-linux-x64.json"
    current.symlink_to(target)

    with pytest.raises(DotNetProvisionError, match="may not be a symlink"):
        ensure_dotnet_sdk(root=root, source_dir=source, offline=True)


def test_dotnet_online_metadata_cache_self_heals(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "official"
    source.mkdir()
    _write_offline_sdk(source)
    monkeypatch.setattr(
        dotnet_manager,
        "detect_dotnet_host",
        lambda: DotNetHost("linux", "x64", "linux-x64", "dotnet"),
    )
    root = tmp_path / "dotnet"
    cache = root / ".downloads"
    cache.mkdir(parents=True)
    (cache / "releases.json").write_text("not-json\n", encoding="utf-8")
    downloads: list[str] = []

    def fake_download(url: str, destination: Path, maximum: int, retries: int = 3) -> None:
        del maximum, retries
        downloads.append(destination.name)
        if destination.name == "releases.json":
            destination.write_bytes((source / "releases.json").read_bytes())
        else:
            destination.write_bytes((source / destination.name).read_bytes())

    monkeypatch.setattr(dotnet_manager, "_download", fake_download)

    installed = ensure_dotnet_sdk(root=root)

    assert installed.version == "8.0.999"
    assert downloads[0] == "releases.json"
    assert any(name.startswith("dotnet-sdk-") for name in downloads)


def test_dotnet_receipt_host_identity_tampering_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "offline"
    source.mkdir()
    _write_offline_sdk(source)
    monkeypatch.setattr(
        dotnet_manager,
        "detect_dotnet_host",
        lambda: DotNetHost("linux", "x64", "linux-x64", "dotnet"),
    )
    root = tmp_path / "dotnet"
    installed = ensure_dotnet_sdk(root=root, source_dir=source, offline=True)
    receipt_path = Path(installed.root) / "dotnet-installation.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["rid"] = "win-x64"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    records = list_dotnet_installations(root)

    assert records[0]["status"] == "invalid"
    assert "host identity" in records[0]["error"]

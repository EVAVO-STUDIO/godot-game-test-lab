from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from urllib.parse import urlparse

_VERSION_RE = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
_FEATURE_VERSION_RE = re.compile(r'"(?P<branch>\d+\.\d+)"')
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 3 * 1024**3
_MAX_EXTRACTED_BYTES = 8 * 1024**3
_MAX_ARCHIVE_MEMBERS = 100_000
_MAX_MEMBER_BYTES = 3 * 1024**3
_MIN_FREE_BYTES_NO_TEMPLATES = 2 * 1024**3
_MIN_FREE_BYTES_WITH_TEMPLATES = 6 * 1024**3
_LOCK_STALE_SECONDS = 2 * 60 * 60
_RELEASE_ROOT = "https://github.com/{repository}/releases/download"
_ALLOWED_RELEASE_REPOSITORY = "godotengine/godot-builds"


class EngineProvisionError(RuntimeError):
    """Raised when a managed Godot installation cannot be trusted or completed."""


@dataclass(frozen=True, slots=True)
class HostSpec:
    platform: str
    architecture: str
    asset_platform: str
    executable_suffix: str


@dataclass(frozen=True, slots=True)
class EngineSelection:
    version: str
    flavor: str
    project_branch: str | None
    csharp: bool
    reason: str


@dataclass(frozen=True, slots=True)
class EngineInstallation:
    schema_version: str
    version: str
    flavor: str
    platform: str
    architecture: str
    root: str
    executable: str
    export_templates: str | None
    editor_archive: str
    editor_sha512: str
    template_archive: str | None
    template_sha512: str | None
    template_payload_sha256: str | None
    source: str
    executable_sha256: str
    payload_sha256: str
    self_contained: bool
    installed_at: str
    verified_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EngineLock:
    schema_version: str
    minimum_version: str
    default_version: str
    channels: dict[str, str]
    default_flavors: tuple[str, ...]
    install_export_templates: bool
    self_contained: bool
    release_repository: str


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _reject_symlink_components(path: Path, label: str) -> Path:
    absolute = _absolute_path(path)
    for component in (absolute, *absolute.parents):
        try:
            if component.exists() and component.is_symlink():
                raise EngineProvisionError(
                    f"{label} may not traverse a symbolic link: {component}"
                )
        except OSError as error:
            raise EngineProvisionError(f"Could not inspect {label}: {component}") from error
    return absolute


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(value.strip())
    if match is None:
        raise EngineProvisionError(
            f"Godot version must be a stable major.minor.patch value: {value!r}"
        )
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def _require_governed_major(
    version: str,
    governed: EngineLock,
    label: str = "Godot version",
) -> tuple[int, int, int]:
    observed = _version_tuple(version)
    required = _version_tuple(governed.minimum_version)
    if observed[0] != required[0]:
        raise EngineProvisionError(
            f"{label} {version} must stay within governed Godot major {required[0]}"
        )
    return observed


def load_engine_lock(path: Path | None = None) -> EngineLock:
    if path is None:
        source = resources.files("godot_game_test_lab").joinpath("godot-engine-lock.json")
        text = source.read_text(encoding="utf-8")
    else:
        requested = _reject_symlink_components(path, "Engine lock")
        candidate = requested.resolve(strict=True)
        if not candidate.is_file():
            raise EngineProvisionError("Engine lock must be a regular file")
        if candidate.stat().st_size > _MAX_MANIFEST_BYTES:
            raise EngineProvisionError("Engine lock exceeds the bounded size limit")
        text = candidate.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise EngineProvisionError("Engine lock is not valid JSON") from error
    if not isinstance(value, dict) or value.get("schemaVersion") != "1.0":
        raise EngineProvisionError("Unsupported engine lock schema")
    channels = value.get("channels")
    flavors = value.get("defaultFlavors")
    if not isinstance(channels, dict) or not channels:
        raise EngineProvisionError("Engine lock channels must be a non-empty object")
    if not isinstance(flavors, list) or not flavors:
        raise EngineProvisionError("Engine lock defaultFlavors must be a non-empty array")
    minimum = str(value.get("minimumVersion", ""))
    default = str(value.get("defaultVersion", ""))
    minimum_tuple = _version_tuple(minimum)
    default_tuple = _version_tuple(default)
    normalized_channels: dict[str, str] = {}
    for branch, version in channels.items():
        if not isinstance(branch, str) or re.fullmatch(r"\d+\.\d+", branch) is None:
            raise EngineProvisionError(f"Invalid Godot channel branch: {branch!r}")
        if not isinstance(version, str):
            raise EngineProvisionError(f"Invalid Godot channel version for {branch}")
        version_tuple = _version_tuple(version)
        expected_branch = f"{version_tuple[0]}.{version_tuple[1]}"
        if branch != expected_branch:
            raise EngineProvisionError(
                f"Godot channel {branch} must map to the same release branch; "
                f"observed {version}"
            )
        if version_tuple[0] != minimum_tuple[0]:
            raise EngineProvisionError(
                "Managed Godot channels must stay within the governed major version"
            )
        if version_tuple < minimum_tuple:
            raise EngineProvisionError(
                f"Godot channel {branch} is below minimumVersion {minimum}"
            )
        normalized_channels[branch] = version
    if f"{minimum_tuple[0]}.{minimum_tuple[1]}" not in normalized_channels:
        raise EngineProvisionError("Engine lock must govern the minimumVersion branch")
    normalized_flavors = tuple(str(item) for item in flavors)
    if any(item not in {"standard", "mono"} for item in normalized_flavors):
        raise EngineProvisionError("Engine lock contains an unsupported flavor")
    if len(normalized_flavors) != len(set(normalized_flavors)):
        raise EngineProvisionError("Engine lock defaultFlavors contains duplicates")
    repository = str(value.get("releaseRepository", _ALLOWED_RELEASE_REPOSITORY))
    if default_tuple < minimum_tuple:
        raise EngineProvisionError("Engine lock defaultVersion is below minimumVersion")
    if default not in normalized_channels.values():
        raise EngineProvisionError("Engine lock defaultVersion must be a governed channel")
    if repository != _ALLOWED_RELEASE_REPOSITORY:
        raise EngineProvisionError(
            "Managed engines must use the official godotengine/godot-builds repository"
        )
    return EngineLock(
        schema_version="1.0",
        minimum_version=minimum,
        default_version=default,
        channels=normalized_channels,
        default_flavors=normalized_flavors,
        install_export_templates=bool(value.get("installExportTemplates", True)),
        self_contained=bool(value.get("selfContained", True)),
        release_repository=repository,
    )


def detect_host() -> HostSpec:
    system = platform.system().casefold()
    machine = platform.machine().casefold()
    architecture_aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86_64": "x86_64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }
    architecture = architecture_aliases.get(machine)
    if architecture is None:
        raise EngineProvisionError(
            "Managed Godot binaries support x86_64 and arm64 hosts; "
            f"observed {machine or 'unknown'}"
        )
    if system == "windows":
        asset_platform = "win64" if architecture == "x86_64" else "windows.arm64"
        return HostSpec("windows", architecture, asset_platform, ".exe")
    if system == "linux":
        return HostSpec("linux", architecture, f"linux.{architecture}", "")
    raise EngineProvisionError(
        "Managed Godot installation supports Windows and Linux; "
        f"observed {system or 'unknown'}"
    )


def default_engine_root() -> Path:
    configured = os.environ.get("EVAVO_GODOT_HOME", "").strip()
    if configured:
        return _absolute_path(Path(configured))
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        if local:
            return _absolute_path(
                Path(local) / "EVAVO" / "GodotGameTestLab" / "engines"
            )
        return _absolute_path(
            Path.home()
            / "AppData"
            / "Local"
            / "EVAVO"
            / "GodotGameTestLab"
            / "engines"
        )
    cache = os.environ.get("XDG_CACHE_HOME", "").strip()
    base = Path(cache).expanduser() if cache else Path.home() / ".cache"
    return _absolute_path(base / "evavo" / "godot-game-test-lab" / "engines")


def _bounded_project_text(project_root: Path) -> str:
    project_file = project_root / "project.godot"
    if project_file.is_symlink() or not project_file.is_file():
        raise EngineProvisionError(
            f"Project does not contain a regular project.godot: {project_root}"
        )
    if project_file.stat().st_size > 4 * 1024 * 1024:
        raise EngineProvisionError("project.godot exceeds the bounded size limit")
    try:
        return project_file.read_text(encoding="utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise EngineProvisionError("project.godot is not valid UTF-8") from error


def _project_branch(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip().startswith("config/features"):
            matches = [match.group("branch") for match in _FEATURE_VERSION_RE.finditer(line)]
            version_matches = [value for value in matches if re.fullmatch(r"\d+\.\d+", value)]
            if version_matches:
                return max(version_matches, key=lambda value: tuple(map(int, value.split("."))))
    return None


def _project_has_csharp(project_root: Path, project_text: str = "") -> bool:
    if re.search(r'config/features\s*=.*"C#"', project_text):
        return True
    ignored = {".git", ".godot", ".mono", "bin", "obj", "artifacts", "reports"}
    inspected = 0
    for current, directories, files in os.walk(project_root, topdown=True, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name not in ignored and not (Path(current) / name).is_symlink()
        )
        files.sort()
        inspected += len(directories) + len(files)
        if inspected > 500_000:
            raise EngineProvisionError("C# project discovery exceeded the bounded entry limit")
        if any(name.casefold().endswith((".cs", ".csproj")) for name in files):
            return True
    return False


def select_engine_for_project(
    project_root: Path,
    *,
    version: str | None = None,
    flavor: str = "auto",
    lock: EngineLock | None = None,
) -> EngineSelection:
    governed = lock or load_engine_lock()
    requested_root = _reject_symlink_components(project_root, "Godot project root")
    root = requested_root.resolve(strict=True)
    text = _bounded_project_text(root)
    branch = _project_branch(text)
    csharp = _project_has_csharp(root, text)
    if flavor == "auto":
        resolved_flavor = "mono" if csharp else "standard"
    elif flavor in {"standard", "mono"}:
        resolved_flavor = flavor
    else:
        raise EngineProvisionError("Engine flavor must be auto, standard, or mono")
    if csharp and resolved_flavor != "mono":
        raise EngineProvisionError("C# projects require the Godot .NET/Mono editor")
    if version:
        resolved_version = version.strip()
        reason = "explicit version"
    elif branch:
        if branch not in governed.channels:
            raise EngineProvisionError(
                f"Project requires unmapped Godot branch {branch}; "
                "update godot-engine-lock.json or pass an explicit stable version"
            )
        resolved_version = governed.channels[branch]
        reason = f"project feature branch {branch}"
    else:
        resolved_version = governed.default_version
        reason = "governed default version"
    resolved_tuple = _require_governed_major(
        resolved_version, governed, "Selected Godot version"
    )
    if branch:
        project_branch = tuple(int(part) for part in branch.split("."))
        if resolved_tuple[:2] < project_branch:
            raise EngineProvisionError(
                f"Godot {resolved_version} is older than project feature branch {branch}"
            )
    if resolved_tuple < _version_tuple(governed.minimum_version):
        raise EngineProvisionError(
            f"Godot {resolved_version} is below the governed minimum {governed.minimum_version}"
        )
    return EngineSelection(
        version=resolved_version,
        flavor=resolved_flavor,
        project_branch=branch,
        csharp=csharp,
        reason=reason,
    )


def _asset_names(version: str, flavor: str, host: HostSpec) -> tuple[str, str]:
    _version_tuple(version)
    if flavor not in {"standard", "mono"}:
        raise EngineProvisionError(f"Unsupported Godot flavor: {flavor}")
    mono = "_mono" if flavor == "mono" else ""
    if host.platform == "windows":
        if host.architecture == "x86_64":
            platform_token = "win64"
        else:
            platform_token = "windows_arm64"
        editor = f"Godot_v{version}-stable{mono}_{platform_token}"
        if flavor == "standard":
            editor += ".exe"
        editor += ".zip"
    elif flavor == "standard":
        editor = f"Godot_v{version}-stable_linux.{host.architecture}.zip"
    else:
        editor = f"Godot_v{version}-stable_mono_linux_{host.architecture}.zip"
    template = f"Godot_v{version}-stable{mono}_export_templates.tpz"
    return editor, template


def _installation_name(version: str, flavor: str, host: HostSpec) -> str:
    mono = "_mono" if flavor == "mono" else ""
    return f"Godot_v{version}-stable{mono}_{host.asset_platform}"


def _release_url(repository: str, version: str, filename: str) -> str:
    root = _RELEASE_ROOT.format(repository=repository)
    return f"{root}/{version}-stable/{filename}"


def _trusted_download_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme.casefold() != "https":
        return False
    host = (parsed.hostname or "").casefold()
    official_object_storage = (
        host.startswith("godot-releases.")
        and host.endswith(".your-objectstorage.com")
    )
    official_github_hosts = {
        "github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
        "github-releases.githubusercontent.com",
    }
    return (
        host in official_github_hosts
        or official_object_storage
        or host == "downloads.godotengine.org"
    )


def _hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha512(path: Path) -> str:
    return _hash_file(path, "sha512")


def _sha256(path: Path) -> str:
    return _hash_file(path, "sha256")


def _parse_checksum_manifest(text: str, filename: str) -> str:
    matches: list[str] = []
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{128})\s+\*?(.+)", line.strip())
        if match and match.group(2) == filename:
            matches.append(match.group(1).lower())
    if len(matches) != 1:
        raise EngineProvisionError(
            f"Official SHA512-SUMS.txt must contain exactly one entry for {filename}"
        )
    return matches[0]


def _read_bounded_text(path: Path, maximum: int = _MAX_MANIFEST_BYTES) -> str:
    if path.is_symlink() or not path.is_file():
        raise EngineProvisionError(f"Expected a regular file: {path}")
    if path.stat().st_size > maximum:
        raise EngineProvisionError(f"File exceeds bounded size limit: {path.name}")
    return path.read_text(encoding="utf-8", errors="strict")


def _copy_stream(source: BinaryIO, destination: Path, maximum: int) -> int:
    total = 0
    with destination.open("xb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise EngineProvisionError(
                    f"Download exceeds bounded byte limit: {destination.name}"
                )
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    return total


def _download(url: str, destination: Path, *, maximum: int, retries: int = 3) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    nonce = f"{os.getpid()}-{time.monotonic_ns()}"
    temporary = destination.with_name(f"{destination.name}.part-{nonce}")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "EVAVO-Godot-Game-Test-Lab/0.7.0"},
    )
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                if not _trusted_download_url(response.geturl()):
                    raise EngineProvisionError(
                        "Godot download redirected to an untrusted host: "
                        f"{response.geturl()}"
                    )
                length = response.headers.get("Content-Length")
                if length is not None:
                    normalized_length = length.strip()
                    if not normalized_length.isdigit():
                        raise EngineProvisionError(
                            f"Remote file has an invalid Content-Length: {url}"
                        )
                    declared_length = int(normalized_length)
                    if declared_length > maximum:
                        raise EngineProvisionError(f"Remote file is too large: {url}")
                _copy_stream(response, temporary, maximum)
            temporary.replace(destination)
            return
        except (OSError, urllib.error.URLError, EngineProvisionError) as error:
            last_error = error
            temporary.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(min(2**attempt, 8))
    raise EngineProvisionError(f"Could not download {url}: {last_error}") from last_error


def _obtain_release_file(
    repository: str,
    version: str,
    filename: str,
    download_root: Path,
    *,
    source_dir: Path | None,
    offline: bool,
) -> tuple[Path, str, str]:
    download_root.mkdir(parents=True, exist_ok=True)
    manifest_name = "SHA512-SUMS.txt"
    if source_dir is not None:
        requested_source = _reject_symlink_components(
            source_dir, "Offline source directory"
        )
        source = requested_source.resolve(strict=True)
        if not source.is_dir():
            raise EngineProvisionError("Offline source must be a regular directory")
        version_source = source / f"{version}-stable"
        if version_source.is_dir() and not version_source.is_symlink():
            source = version_source.resolve(strict=True)
        manifest_path = source / manifest_name
        asset_path = source / filename
        source_label = f"offline:{source}"
        manifest = _read_bounded_text(manifest_path)
        expected = _parse_checksum_manifest(manifest, filename)
        if asset_path.is_symlink() or not asset_path.is_file():
            raise EngineProvisionError(f"Godot release asset is missing: {asset_path}")
        if asset_path.stat().st_size > _MAX_ARCHIVE_BYTES:
            raise EngineProvisionError(
                f"Godot release asset exceeds byte limit: {filename}"
            )
        observed = _sha512(asset_path)
        if observed != expected:
            raise EngineProvisionError(
                f"SHA512 mismatch for {filename}: expected {expected}, "
                f"observed {observed}"
            )
        return asset_path, expected, source_label

    manifest_path = download_root / manifest_name
    asset_path = download_root / filename
    source_label = _release_url(repository, version, filename)
    for attempt in range(2):
        if not manifest_path.exists():
            if offline:
                raise EngineProvisionError(
                    "Offline mode requires a cached SHA512-SUMS.txt"
                )
            _download(
                _release_url(repository, version, manifest_name),
                manifest_path,
                maximum=_MAX_MANIFEST_BYTES,
            )
        try:
            manifest = _read_bounded_text(manifest_path)
            expected = _parse_checksum_manifest(manifest, filename)
        except (EngineProvisionError, UnicodeError):
            if offline or attempt > 0:
                raise
            manifest_path.unlink(missing_ok=True)
            asset_path.unlink(missing_ok=True)
            continue
        if not asset_path.exists():
            if offline:
                raise EngineProvisionError(
                    f"Offline mode requires cached asset: {filename}"
                )
            _download(
                _release_url(repository, version, filename),
                asset_path,
                maximum=_MAX_ARCHIVE_BYTES,
            )
        if asset_path.is_symlink() or not asset_path.is_file():
            error = EngineProvisionError(
                f"Godot release asset is missing: {asset_path}"
            )
        elif asset_path.stat().st_size > _MAX_ARCHIVE_BYTES:
            error = EngineProvisionError(
                f"Godot release asset exceeds byte limit: {filename}"
            )
        else:
            observed = _sha512(asset_path)
            if observed == expected:
                return asset_path, expected, source_label
            error = EngineProvisionError(
                f"SHA512 mismatch for {filename}: expected {expected}, "
                f"observed {observed}"
            )
        if offline or attempt > 0:
            raise error
        asset_path.unlink(missing_ok=True)
    raise EngineProvisionError(
        f"Could not obtain verified Godot release asset: {filename}"
    )


def _safe_member_path(name: str) -> PurePosixPath:
    if "\x00" in name:
        raise EngineProvisionError("Archive member contains a NUL byte")
    normalized = unicodedata.normalize("NFC", name.replace("\\", "/"))
    if len(normalized.encode("utf-8")) > 2048:
        raise EngineProvisionError("Archive member path exceeds the bounded limit")
    pure = PurePosixPath(normalized)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or ":" in pure.parts[0]
    ):
        raise EngineProvisionError(f"Unsafe archive path: {name}")
    return pure


def _safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    observed: set[str] = set()
    total = 0
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > _MAX_ARCHIVE_MEMBERS:
            raise EngineProvisionError("Archive member count exceeds the bounded limit")
        for info in infos:
            pure = _safe_member_path(info.filename)
            if info.flag_bits & 0x1:
                raise EngineProvisionError(
                    f"Encrypted archive members are unsupported: {info.filename}"
                )
            identity = unicodedata.normalize("NFC", "/".join(pure.parts)).casefold()
            if identity in observed:
                raise EngineProvisionError(
                    "Archive contains a duplicate, case-colliding, or "
                    f"Unicode-colliding path: {info.filename}"
                )
            observed.add(identity)
            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise EngineProvisionError(f"Archive contains a symbolic link: {info.filename}")
            file_type = stat.S_IFMT(unix_mode)
            if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise EngineProvisionError(
                    f"Archive contains an unsupported special file: {info.filename}"
                )
            if info.file_size < 0 or info.file_size > _MAX_MEMBER_BYTES:
                raise EngineProvisionError(f"Archive member exceeds byte limit: {info.filename}")
            total += info.file_size
            if total > _MAX_EXTRACTED_BYTES:
                raise EngineProvisionError("Archive expanded size exceeds the bounded limit")
            target = destination.joinpath(*pure.parts)
            resolved_parent = target.parent.resolve(strict=False)
            if destination.resolve(strict=True) not in [resolved_parent, *resolved_parent.parents]:
                raise EngineProvisionError(f"Archive path escapes destination: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source:
                _copy_stream(source, target, _MAX_MEMBER_BYTES)
            if unix_mode & stat.S_IXUSR:
                target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _find_editor_executable(root: Path, host: HostSpec, flavor: str) -> Path:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        name = path.name.casefold()
        if not name.startswith("godot_v"):
            continue
        if host.platform == "windows" and path.suffix.casefold() != ".exe":
            continue
        if host.platform == "linux":
            expected_suffixes = (
                ("linux.x86_64", "linux_x86_64")
                if host.architecture == "x86_64"
                else ("linux.arm64", "linux_arm64")
            )
            if not name.endswith(expected_suffixes):
                continue
        if flavor == "mono" and "mono" not in name:
            continue
        if flavor == "standard" and "mono" in name:
            continue
        candidates.append(path)
    if not candidates:
        raise EngineProvisionError("The Godot editor executable was not found after extraction")
    candidates.sort(
        key=lambda path: (
            "console" in path.name.casefold(),
            -len(path.relative_to(root).parts),
            path.name.casefold(),
        ),
        reverse=True,
    )
    executable = candidates[0]
    if host.platform == "linux":
        executable.chmod(executable.stat().st_mode | 0o755)
    return executable


def _payload_root(extracted: Path, executable: Path) -> Path:
    relative = executable.relative_to(extracted)
    if len(relative.parts) > 1:
        first = extracted / relative.parts[0]
        siblings = [entry for entry in extracted.iterdir()]
        if len(siblings) == 1 and first.is_dir() and not first.is_symlink():
            return first
    return extracted


def _copy_payload(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for entry in source.iterdir():
        target = destination / entry.name
        if entry.is_symlink():
            raise EngineProvisionError("Extracted payload unexpectedly contains a symbolic link")
        if entry.is_dir():
            shutil.copytree(entry, target, symlinks=False)
        elif entry.is_file():
            shutil.copy2(entry, target)
        else:
            raise EngineProvisionError(f"Unsupported extracted payload entry: {entry}")


def _install_templates(archive: Path, installation_root: Path, version: str) -> Path:
    temporary = (
        installation_root.parent
        / f".{installation_root.name}-templates-{os.getpid()}"
    )
    destination = (
        installation_root
        / "editor_data"
        / "export_templates"
        / f"{version}.stable"
    )
    staging = destination.with_name(destination.name + ".staging")
    shutil.rmtree(temporary, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)
    try:
        _safe_extract_zip(archive, temporary)
        template_candidates = [
            path
            for path in temporary.rglob("templates")
            if path.is_dir() and not path.is_symlink()
        ]
        if len(template_candidates) != 1:
            raise EngineProvisionError(
                "Export template archive must contain exactly one templates directory"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(template_candidates[0], staging, symlinks=False)
        version_file = staging / "version.txt"
        if not version_file.is_file() or version_file.is_symlink():
            raise EngineProvisionError("Export templates are missing version.txt")
        expected = f"{version}.stable"
        observed = version_file.read_text(encoding="utf-8", errors="strict").strip()
        if observed != expected:
            raise EngineProvisionError(
                "Export template version mismatch: "
                f"expected {expected}, observed {observed}"
            )
        if destination.exists():
            shutil.rmtree(destination)
        staging.replace(destination)
        return destination
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)


@contextmanager
def _exclusive_lock(path: Path, timeout_seconds: int = 600) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "pid": os.getpid(),
                        "createdAt": datetime.now(UTC).isoformat(),
                        "epoch": time.time(),
                    },
                    handle,
                )
            break
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                age = 0
            if age > _LOCK_STALE_SECONDS:
                path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise EngineProvisionError(
                    f"Timed out waiting for engine installation lock: {path}"
                ) from None
            time.sleep(0.25)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _directory_sha256(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise EngineProvisionError(f"Expected a regular directory for hashing: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink():
            raise EngineProvisionError(f"Managed directory contains a symlink: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise EngineProvisionError(f"Managed directory contains a special file: {path}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _payload_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    excluded_names = {"._sc_", "_sc_", "engine-installation.json"}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink():
            raise EngineProvisionError(f"Managed engine payload contains a symlink: {path}")
        relative = path.relative_to(root)
        if not relative.parts or relative.parts[0] == "editor_data":
            continue
        if path.name in excluded_names:
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            raise EngineProvisionError(f"Managed engine payload contains a special file: {path}")
        encoded = relative.as_posix().encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _metadata_path(root: Path) -> Path:
    return root / "engine-installation.json"


def _load_installation(path: Path) -> EngineInstallation:
    try:
        value = json.loads(_read_bounded_text(path))
        installation = EngineInstallation(
            schema_version=str(value["schema_version"]),
            version=str(value["version"]),
            flavor=str(value["flavor"]),
            platform=str(value["platform"]),
            architecture=str(value["architecture"]),
            root=str(value["root"]),
            executable=str(value["executable"]),
            export_templates=value.get("export_templates"),
            editor_archive=str(value["editor_archive"]),
            editor_sha512=str(value["editor_sha512"]),
            template_archive=value.get("template_archive"),
            template_sha512=value.get("template_sha512"),
            template_payload_sha256=value.get("template_payload_sha256"),
            source=str(value["source"]),
            executable_sha256=str(value.get("executable_sha256", "")),
            payload_sha256=str(value["payload_sha256"]),
            self_contained=bool(value["self_contained"]),
            installed_at=str(value["installed_at"]),
            verified_at=str(value["verified_at"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise EngineProvisionError(f"Managed engine metadata is invalid: {path}") from error
    if installation.schema_version not in {"1.1", "1.2"}:
        raise EngineProvisionError(
            f"Unsupported managed engine metadata schema: {installation.schema_version}"
        )
    if installation.flavor not in {"standard", "mono"}:
        raise EngineProvisionError("Managed engine metadata contains an invalid flavor")
    if installation.platform not in {"windows", "linux"}:
        raise EngineProvisionError("Managed engine metadata contains an invalid platform")
    if installation.architecture not in {"x86_64", "arm64"}:
        raise EngineProvisionError("Managed engine metadata contains an invalid architecture")
    metadata_root = path.parent.resolve(strict=True)
    declared_root = Path(installation.root).expanduser().resolve(strict=False)
    if declared_root != metadata_root:
        raise EngineProvisionError(
            "Managed engine metadata root does not match its receipt directory"
        )
    executable = Path(installation.executable).expanduser().resolve(strict=True)
    try:
        executable.relative_to(metadata_root)
    except ValueError as error:
        raise EngineProvisionError(
            "Managed engine metadata executable escapes its receipt directory"
        ) from error
    if installation.export_templates:
        templates = Path(installation.export_templates).expanduser().resolve(strict=True)
        try:
            templates.relative_to(metadata_root)
        except ValueError as error:
            raise EngineProvisionError(
                "Managed engine metadata templates escape its receipt directory"
            ) from error
    return installation


def _verify_executable(executable: Path, version: str) -> str:
    if executable.is_symlink() or not executable.is_file():
        raise EngineProvisionError(f"Managed Godot executable is missing: {executable}")
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise EngineProvisionError(f"Managed Godot --version failed: {error}") from error
    output = f"{result.stdout}\n{result.stderr}".strip()
    if result.returncode != 0 or version not in output:
        raise EngineProvisionError(
            f"Managed Godot identity mismatch for {executable}: {output or 'no output'}"
        )
    return output


def verify_installation(installation: EngineInstallation) -> EngineInstallation:
    raw_executable = Path(installation.executable).expanduser()
    raw_root = Path(installation.root).expanduser()
    if raw_executable.is_symlink() or raw_root.is_symlink():
        raise EngineProvisionError("Managed engine root and executable may not be symlinks")
    executable = raw_executable.resolve(strict=True)
    root = raw_root.resolve(strict=True)
    if root not in [executable.parent, *executable.parents]:
        raise EngineProvisionError("Managed executable escapes its installation root")
    _verify_executable(executable, installation.version)
    observed_executable = _sha256(executable)
    if (
        installation.executable_sha256
        and observed_executable != installation.executable_sha256
    ):
        raise EngineProvisionError(
            "Managed Godot executable integrity mismatch: "
            f"expected {installation.executable_sha256}, observed {observed_executable}"
        )
    observed_payload = _payload_sha256(root)
    if observed_payload != installation.payload_sha256:
        raise EngineProvisionError(
            "Managed Godot payload integrity mismatch: "
            f"expected {installation.payload_sha256}, observed {observed_payload}"
        )
    if installation.self_contained:
        marker = executable.parent / (
            "_sc_" if installation.platform == "windows" else "._sc_"
        )
        if marker.is_symlink() or not marker.is_file():
            raise EngineProvisionError("Managed Godot self-contained marker is missing")
    if installation.export_templates:
        raw_templates = Path(installation.export_templates).expanduser()
        if raw_templates.is_symlink():
            raise EngineProvisionError("Managed export templates may not be a symlink")
        templates = raw_templates.resolve(strict=True)
        try:
            templates.relative_to(root)
        except ValueError as error:
            raise EngineProvisionError(
                "Managed export templates escape the installation root"
            ) from error
        if not templates.is_dir() or not (templates / "version.txt").is_file():
            raise EngineProvisionError("Managed Godot export templates are incomplete")
        observed_templates = _directory_sha256(templates)
        if installation.template_payload_sha256:
            if observed_templates != installation.template_payload_sha256:
                raise EngineProvisionError(
                    "Managed export template integrity mismatch: "
                    f"expected {installation.template_payload_sha256}, "
                    f"observed {observed_templates}"
                )
        elif installation.schema_version == "1.2":
            raise EngineProvisionError("Managed export template receipt is incomplete")
    return EngineInstallation(
        **{
            **installation.to_dict(),
            "verified_at": datetime.now(UTC).isoformat(),
        }
    )


def install_engine(
    *,
    version: str,
    flavor: str,
    root: Path | None = None,
    install_templates: bool = True,
    source_dir: Path | None = None,
    offline: bool = False,
    force: bool = False,
    lock: EngineLock | None = None,
) -> EngineInstallation:
    governed = lock or load_engine_lock()
    version_tuple = _require_governed_major(version, governed)
    if version_tuple < _version_tuple(governed.minimum_version):
        raise EngineProvisionError(
            f"Godot {version} is below the governed minimum {governed.minimum_version}"
        )
    if flavor not in {"standard", "mono"}:
        raise EngineProvisionError("Engine flavor must be standard or mono")
    host = detect_host()
    requested_engine_root = _reject_symlink_components(
        root or default_engine_root(), "Managed engine root"
    )
    requested_engine_root.mkdir(parents=True, exist_ok=True)
    engine_root = requested_engine_root.resolve(strict=True)
    if not engine_root.is_dir():
        raise EngineProvisionError("Managed engine root must be a regular directory")
    editor_archive, template_archive = _asset_names(version, flavor, host)
    installation_root = engine_root / _installation_name(version, flavor, host)
    lock_path = engine_root / ".locks" / f"{installation_root.name}.lock"
    with _exclusive_lock(lock_path):
        metadata = _metadata_path(installation_root)
        if metadata.is_file() and not force:
            try:
                existing = verify_installation(_load_installation(metadata))
                if not install_templates or existing.export_templates:
                    return existing
            except (EngineProvisionError, OSError):
                # A corrupt or partial managed installation is replaced atomically below.
                pass
        usage = shutil.disk_usage(engine_root)
        required_free = (
            _MIN_FREE_BYTES_WITH_TEMPLATES
            if install_templates
            else _MIN_FREE_BYTES_NO_TEMPLATES
        )
        if usage.free < required_free:
            required_gib = required_free // 1024**3
            raise EngineProvisionError(
                "Managed engine root has insufficient free disk space; "
                f"at least {required_gib} GiB is required for this installation"
            )
        download_root = engine_root / ".downloads" / f"{version}-stable"
        editor_path, editor_digest, editor_source = _obtain_release_file(
            governed.release_repository,
            version,
            editor_archive,
            download_root,
            source_dir=source_dir,
            offline=offline,
        )
        template_path: Path | None = None
        template_digest: str | None = None
        template_source: str | None = None
        if install_templates:
            template_path, template_digest, template_source = _obtain_release_file(
                governed.release_repository,
                version,
                template_archive,
                download_root,
                source_dir=source_dir,
                offline=offline,
            )
        parent = installation_root.parent
        staging = parent / f".{installation_root.name}.staging-{os.getpid()}"
        extracted = parent / f".{installation_root.name}.extract-{os.getpid()}"
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(extracted, ignore_errors=True)
        try:
            _safe_extract_zip(editor_path, extracted)
            extracted_executable = _find_editor_executable(extracted, host, flavor)
            payload = _payload_root(extracted, extracted_executable)
            _copy_payload(payload, staging)
            executable = _find_editor_executable(staging, host, flavor)
            marker = executable.parent / ("_sc_" if host.platform == "windows" else "._sc_")
            marker.write_text("# EVAVO managed self-contained Godot editor\n", encoding="utf-8")
            templates: Path | None = None
            if template_path is not None:
                templates = _install_templates(template_path, executable.parent, version)
            _verify_executable(executable, version)
            payload_digest = _payload_sha256(staging)
            installed_at = datetime.now(UTC).isoformat()
            receipt = EngineInstallation(
                schema_version="1.2",
                version=version,
                flavor=flavor,
                platform=host.platform,
                architecture=host.architecture,
                root=str(installation_root),
                executable=str(installation_root / executable.relative_to(staging)),
                export_templates=(
                    str(installation_root / templates.relative_to(staging))
                    if templates is not None
                    else None
                ),
                editor_archive=editor_archive,
                editor_sha512=editor_digest,
                template_archive=template_archive if template_path is not None else None,
                template_sha512=template_digest,
                template_payload_sha256=(
                    _directory_sha256(templates) if templates is not None else None
                ),
                source=template_source or editor_source,
                executable_sha256=_sha256(executable),
                payload_sha256=payload_digest,
                self_contained=True,
                installed_at=installed_at,
                verified_at=installed_at,
            )
            metadata_staging = staging / "engine-installation.json"
            metadata_staging.write_text(
                json.dumps(receipt.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            if installation_root.exists():
                backup = parent / f".{installation_root.name}.old-{os.getpid()}"
                shutil.rmtree(backup, ignore_errors=True)
                installation_root.replace(backup)
                try:
                    staging.replace(installation_root)
                except Exception:
                    backup.replace(installation_root)
                    raise
                shutil.rmtree(backup, ignore_errors=True)
            else:
                staging.replace(installation_root)
            return verify_installation(_load_installation(_metadata_path(installation_root)))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(extracted, ignore_errors=True)


def ensure_project_engine(
    project_root: Path,
    *,
    version: str | None = None,
    flavor: str = "auto",
    root: Path | None = None,
    install_templates: bool | None = None,
    source_dir: Path | None = None,
    offline: bool = False,
    force: bool = False,
    lock_path: Path | None = None,
) -> tuple[EngineSelection, EngineInstallation]:
    governed = load_engine_lock(lock_path)
    selection = select_engine_for_project(
        project_root,
        version=version,
        flavor=flavor,
        lock=governed,
    )
    installation = install_engine(
        version=selection.version,
        flavor=selection.flavor,
        root=root,
        install_templates=(
            governed.install_export_templates
            if install_templates is None
            else install_templates
        ),
        source_dir=source_dir,
        offline=offline,
        force=force,
        lock=governed,
    )
    return selection, installation


def list_installations(root: Path | None = None) -> list[dict[str, Any]]:
    requested = _reject_symlink_components(
        root or default_engine_root(), "Managed engine root"
    )
    if not requested.exists():
        return []
    engine_root = requested.resolve(strict=True)
    if not engine_root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for metadata in sorted(engine_root.glob("Godot_*/engine-installation.json")):
        try:
            installation = _load_installation(metadata)
            verified = verify_installation(installation)
            records.append({**verified.to_dict(), "status": "ready"})
        except (EngineProvisionError, OSError) as error:
            records.append(
                {
                    "status": "invalid",
                    "metadata": str(metadata),
                    "error": str(error),
                }
            )
    return records


def bootstrap_host(
    *,
    version: str | None = None,
    root: Path | None = None,
    flavors: tuple[str, ...] | None = None,
    install_templates: bool = True,
    source_dir: Path | None = None,
    offline: bool = False,
    force: bool = False,
    lock_path: Path | None = None,
) -> dict[str, Any]:
    governed = load_engine_lock(lock_path)
    resolved_version = version or governed.default_version
    requested_flavors = flavors or governed.default_flavors
    installations = [
        install_engine(
            version=resolved_version,
            flavor=flavor,
            root=root,
            install_templates=install_templates,
            source_dir=source_dir,
            offline=offline,
            force=force,
            lock=governed,
        ).to_dict()
        for flavor in requested_flavors
    ]
    return {
        "schemaVersion": "1.0",
        "status": "ready",
        "engineRoot": str((root or default_engine_root()).resolve(strict=False)),
        "defaultVersion": resolved_version,
        "installations": installations,
        "environment": {
            "EVAVO_GODOT_HOME": str((root or default_engine_root()).resolve(strict=False)),
            "GODOT_BIN": next(
                (
                    item["executable"]
                    for item in installations
                    if item["flavor"] == "standard"
                ),
                None,
            ),
            "GODOT_MONO_BIN": next(
                (
                    item["executable"]
                    for item in installations
                    if item["flavor"] == "mono"
                ),
                None,
            ),
        },
    }


def _candidate_projects(root: Path, maximum_projects: int = 256) -> list[Path]:
    requested_path = _reject_symlink_components(root, "Estate root")
    requested = requested_path.resolve(strict=True)
    if requested.is_file():
        if requested.name != "project.godot":
            raise EngineProvisionError("Estate preparation expects a directory or project.godot")
        return [requested.parent]
    if not requested.is_dir() or requested.is_symlink():
        raise EngineProvisionError("Estate root must be a regular directory")
    direct = requested / "project.godot"
    if direct.is_file() and not direct.is_symlink():
        return [requested]
    ignored = {
        ".git",
        ".godot",
        ".idea",
        ".mono",
        ".pytest_cache",
        ".ruff_cache",
        ".vs",
        ".vscode",
        "artifacts",
        "bin",
        "build",
        "dist",
        "node_modules",
        "obj",
        "reports",
        "test-results",
    }
    projects: list[Path] = []
    inspected = 0
    for current, directories, files in os.walk(requested, topdown=True, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name not in ignored and not (Path(current) / name).is_symlink()
        )
        files.sort()
        inspected += len(directories) + len(files)
        if inspected > 1_000_000:
            raise EngineProvisionError(
                "Estate discovery exceeded the bounded filesystem entry limit"
            )
        if "project.godot" not in files:
            continue
        project_file = Path(current) / "project.godot"
        if project_file.is_file() and not project_file.is_symlink():
            projects.append(project_file.parent.resolve(strict=True))
            directories.clear()
        if len(projects) > maximum_projects:
            raise EngineProvisionError(
                f"Estate discovery exceeded the {maximum_projects}-project limit"
            )
    return sorted(set(projects), key=lambda item: str(item).casefold())


def prepare_estate(
    target_root: Path,
    *,
    root: Path | None = None,
    install_templates: bool = True,
    source_dir: Path | None = None,
    offline: bool = False,
    force: bool = False,
    lock_path: Path | None = None,
    maximum_projects: int = 256,
) -> dict[str, Any]:
    governed = load_engine_lock(lock_path)
    projects = _candidate_projects(target_root, maximum_projects=maximum_projects)
    selections: list[dict[str, Any]] = []
    requirements: dict[tuple[str, str], EngineSelection] = {}
    failures: list[dict[str, str]] = []
    for project in projects:
        try:
            selection = select_engine_for_project(project, lock=governed)
        except (EngineProvisionError, OSError) as error:
            failures.append({"projectRoot": str(project), "error": str(error)})
            continue
        requirements[(selection.version, selection.flavor)] = selection
        selections.append(
            {
                "projectRoot": str(project),
                "version": selection.version,
                "flavor": selection.flavor,
                "projectBranch": selection.project_branch,
                "csharp": selection.csharp,
                "reason": selection.reason,
            }
        )
    installations: list[dict[str, Any]] = []
    for version, flavor in sorted(requirements):
        try:
            installation = install_engine(
                version=version,
                flavor=flavor,
                root=root,
                install_templates=install_templates,
                source_dir=source_dir,
                offline=offline,
                force=force,
                lock=governed,
            )
            installations.append({"status": "ready", **installation.to_dict()})
        except (EngineProvisionError, OSError) as error:
            failures.append(
                {
                    "requirement": f"{version}:{flavor}",
                    "error": str(error),
                }
            )
    return {
        "schemaVersion": "1.0",
        "status": "passed" if projects and not failures else "failed",
        "estateRoot": str(target_root.expanduser().resolve(strict=True)),
        "engineRoot": str((root or default_engine_root()).resolve(strict=False)),
        "projectCount": len(projects),
        "projects": selections,
        "installations": installations,
        "failures": failures,
    }


def mirror_release_assets(
    destination: Path,
    *,
    versions: tuple[str, ...] | None = None,
    platforms: tuple[str, ...] = ("windows-x86_64", "linux-x86_64"),
    flavors: tuple[str, ...] = ("standard", "mono"),
    include_templates: bool = True,
    lock_path: Path | None = None,
) -> dict[str, Any]:
    governed = load_engine_lock(lock_path)
    requested_versions = versions or tuple(sorted(set(governed.channels.values())))
    requested_platforms = tuple(dict.fromkeys(platforms))
    requested_flavors = tuple(dict.fromkeys(flavors))
    platform_specs = {
        "windows-x86_64": HostSpec("windows", "x86_64", "win64", ".exe"),
        "windows-arm64": HostSpec("windows", "arm64", "windows.arm64", ".exe"),
        "linux-x86_64": HostSpec("linux", "x86_64", "linux.x86_64", ""),
        "linux-arm64": HostSpec("linux", "arm64", "linux.arm64", ""),
    }
    if any(value not in platform_specs for value in requested_platforms):
        raise EngineProvisionError("Mirror platforms must be Windows/Linux x86_64 or arm64")
    if any(value not in {"standard", "mono"} for value in requested_flavors):
        raise EngineProvisionError("Mirror flavors must contain standard and/or mono")
    requested_root = _reject_symlink_components(destination, "Mirror destination")
    requested_root.mkdir(parents=True, exist_ok=True)
    root = requested_root.resolve(strict=True)
    if not root.is_dir():
        raise EngineProvisionError("Mirror destination must be a regular directory")
    records: list[dict[str, Any]] = []
    for version in requested_versions:
        version_tuple = _require_governed_major(version, governed, "Mirror Godot version")
        if version_tuple < _version_tuple(governed.minimum_version):
            raise EngineProvisionError(f"Mirror version is below minimum: {version}")
        version_root = root / f"{version}-stable"
        for platform_name in requested_platforms:
            host = platform_specs[platform_name]
            for flavor in requested_flavors:
                editor, template = _asset_names(version, flavor, host)
                editor_path, editor_sha, editor_source = _obtain_release_file(
                    governed.release_repository,
                    version,
                    editor,
                    version_root,
                    source_dir=None,
                    offline=False,
                )
                record: dict[str, Any] = {
                    "version": version,
                    "platform": platform_name,
                    "flavor": flavor,
                    "editor": editor_path.name,
                    "editorSha512": editor_sha,
                    "source": editor_source,
                }
                if include_templates:
                    template_path, template_sha, _template_source = _obtain_release_file(
                        governed.release_repository,
                        version,
                        template,
                        version_root,
                        source_dir=None,
                        offline=False,
                    )
                    record["templates"] = template_path.name
                    record["templatesSha512"] = template_sha
                records.append(record)
    receipt = {
        "schemaVersion": "1.0",
        "status": "ready",
        "mirrorRoot": str(root),
        "versions": list(requested_versions),
        "platforms": list(requested_platforms),
        "flavors": list(requested_flavors),
        "assets": records,
        "createdAt": datetime.now(UTC).isoformat(),
    }
    (root / "godot-engine-mirror.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return receipt

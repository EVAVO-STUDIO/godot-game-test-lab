from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from urllib.parse import urlparse

_DOTNET_CHANNEL = "8.0"
_METADATA_URL = (
    "https://dotnetcli.blob.core.windows.net/dotnet/"
    "release-metadata/8.0/releases.json"
)
_MAX_METADATA_BYTES = 16 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 3 * 1024**3
_MAX_EXTRACTED_BYTES = 10 * 1024**3
_MAX_MEMBER_BYTES = 3 * 1024**3
_MAX_MEMBERS = 250_000
_LOCK_STALE_SECONDS = 2 * 60 * 60
_VERSION_RE = re.compile(r"^8\.[0-9]+\.[0-9]+$")
_HASH_RE = re.compile(r"^[0-9a-fA-F]{128}$")
_WINDOWS_RESERVED_NAMES = {
    "aux", "clock$", "con", "nul", "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_WINDOWS_INVALID = set('<>:"|?*')


class DotNetProvisionError(RuntimeError):
    """Raised when a managed .NET SDK cannot be safely selected or installed."""


@dataclass(frozen=True, slots=True)
class DotNetHost:
    platform: str
    architecture: str
    rid: str
    executable_name: str


@dataclass(frozen=True, slots=True)
class DotNetInstallation:
    schema_version: str
    channel: str
    version: str
    platform: str
    architecture: str
    rid: str
    root: str
    executable: str
    archive: str
    archive_sha512: str
    source_url: str
    payload_sha256: str
    installed_at: str
    verified_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_dotnet_host() -> DotNetHost:
    system = platform.system().casefold()
    machine = platform.machine().casefold()
    architecture = {
        "amd64": "x64",
        "x64": "x64",
        "x86_64": "x64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine)
    if architecture is None:
        raise DotNetProvisionError(
            "Managed .NET supports x86_64 and arm64; "
            f"observed {machine or 'unknown'}"
        )
    if system == "windows":
        return DotNetHost("windows", architecture, f"win-{architecture}", "dotnet.exe")
    if system == "linux":
        return DotNetHost("linux", architecture, f"linux-{architecture}", "dotnet")
    raise DotNetProvisionError(
        "Managed .NET installation supports Windows and Linux; "
        f"observed {system or 'unknown'}"
    )


def default_dotnet_root(engine_root: Path | None = None) -> Path:
    configured = os.environ.get("EVAVO_DOTNET_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    if engine_root is not None:
        return (engine_root.expanduser().resolve(strict=False).parent / "dotnet").resolve(
            strict=False
        )
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return (base / "EVAVO" / "GodotGameTestLab" / "dotnet").resolve(strict=False)
    cache = os.environ.get("XDG_CACHE_HOME", "").strip()
    base = Path(cache).expanduser() if cache else Path.home() / ".cache"
    return (base / "evavo" / "godot-game-test-lab" / "dotnet").resolve(strict=False)


def _trusted_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").casefold()
    return host in {
        "builds.dotnet.microsoft.com",
        "download.visualstudio.microsoft.com",
        "dotnetcli.azureedge.net",
        "dotnetcli.blob.core.windows.net",
    }


def _hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_stream(source: BinaryIO, destination: Path, maximum: int) -> None:
    total = 0
    with destination.open("xb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise DotNetProvisionError(
                    f"Download exceeds the bounded byte limit: {destination.name}"
                )
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())


def _download(url: str, destination: Path, maximum: int, retries: int = 3) -> None:
    if not _trusted_url(url):
        raise DotNetProvisionError(f"Untrusted .NET download URL: {url}")
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
                if not _trusted_url(response.geturl()):
                    raise DotNetProvisionError(
                        f".NET download redirected to an untrusted host: {response.geturl()}"
                    )
                length = response.headers.get("Content-Length")
                try:
                    declared_length = int(length) if length else None
                except ValueError as error:
                    raise DotNetProvisionError(
                        f"Remote file declared an invalid Content-Length: {url}"
                    ) from error
                if declared_length is not None and declared_length > maximum:
                    raise DotNetProvisionError(f"Remote file is too large: {url}")
                _copy_stream(response, temporary, maximum)
            temporary.replace(destination)
            return
        except (OSError, urllib.error.URLError, DotNetProvisionError) as error:
            last_error = error
            temporary.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(min(2**attempt, 8))
    raise DotNetProvisionError(f"Could not download {url}: {last_error}") from last_error


def _read_json(path: Path, maximum: int = _MAX_METADATA_BYTES) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise DotNetProvisionError(f"Expected a regular JSON file: {path}")
    if path.stat().st_size > maximum:
        raise DotNetProvisionError(f"JSON file exceeds the bounded size limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DotNetProvisionError(f"Could not parse .NET metadata: {error}") from error
    if not isinstance(value, dict):
        raise DotNetProvisionError(".NET metadata root must be an object")
    return value


def _safe_path(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    if "\x00" in normalized or len(normalized.encode("utf-8")) > 2048:
        raise DotNetProvisionError("Unsafe .NET archive path")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or not pure.parts:
        raise DotNetProvisionError(f"Unsafe .NET archive path: {name}")
    safe_parts: list[str] = []
    for part in pure.parts:
        normalized_part = unicodedata.normalize("NFC", part)
        stem = normalized_part.split(".", 1)[0].casefold()
        if (
            normalized_part in {"", ".", ".."}
            or normalized_part.endswith((" ", "."))
            or any(ord(character) < 32 for character in normalized_part)
            or any(character in _WINDOWS_INVALID for character in normalized_part)
            or stem in _WINDOWS_RESERVED_NAMES
        ):
            raise DotNetProvisionError(f"Unsafe .NET archive path: {name}")
        safe_parts.append(normalized_part)
    return PurePosixPath(*safe_parts)


def _safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    total = 0
    observed: set[str] = set()
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > _MAX_MEMBERS:
            raise DotNetProvisionError(".NET archive member limit exceeded")
        for info in infos:
            if info.flag_bits & 0x1:
                raise DotNetProvisionError(
                    f".NET archive contains an encrypted member: {info.filename}"
                )
            pure = _safe_path(info.filename)
            identity = "/".join(pure.parts).casefold()
            if identity in observed:
                raise DotNetProvisionError(
                    f".NET archive contains a colliding path: {info.filename}"
                )
            observed.add(identity)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise DotNetProvisionError(
                    f".NET archive contains a symbolic link: {info.filename}"
                )
            file_type = stat.S_IFMT(mode)
            if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise DotNetProvisionError(
                    f".NET archive contains a special file: {info.filename}"
                )
            if info.file_size < 0 or info.file_size > _MAX_MEMBER_BYTES:
                raise DotNetProvisionError(
                    f".NET archive member exceeds its byte limit: {info.filename}"
                )
            total += info.file_size
            if total > _MAX_EXTRACTED_BYTES:
                raise DotNetProvisionError(".NET archive expanded-size limit exceeded")
            target = destination.joinpath(*pure.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source:
                _copy_stream(source, target, _MAX_MEMBER_BYTES)
            if mode & stat.S_IXUSR:
                target.chmod(target.stat().st_mode | 0o755)


def _safe_extract_tar(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    total = 0
    observed: set[str] = set()
    with tarfile.open(archive_path, mode="r:*") as archive:
        members = archive.getmembers()
        if len(members) > _MAX_MEMBERS:
            raise DotNetProvisionError(".NET archive member limit exceeded")
        for member in members:
            pure = _safe_path(member.name)
            identity = "/".join(pure.parts).casefold()
            if identity in observed:
                raise DotNetProvisionError(
                    f".NET archive contains a colliding path: {member.name}"
                )
            observed.add(identity)
            if member.issym() or member.islnk() or member.isdev():
                raise DotNetProvisionError(
                    f".NET archive contains a link or device: {member.name}"
                )
            if not (member.isfile() or member.isdir()):
                raise DotNetProvisionError(
                    f".NET archive contains a special member: {member.name}"
                )
            if member.size < 0 or member.size > _MAX_MEMBER_BYTES:
                raise DotNetProvisionError(
                    f".NET archive member exceeds its byte limit: {member.name}"
                )
            total += member.size
            if total > _MAX_EXTRACTED_BYTES:
                raise DotNetProvisionError(".NET archive expanded-size limit exceeded")
            target = destination.joinpath(*pure.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise DotNetProvisionError(f"Could not read .NET member: {member.name}")
            with source:
                _copy_stream(source, target, _MAX_MEMBER_BYTES)
            if member.mode & stat.S_IXUSR:
                target.chmod(target.stat().st_mode | 0o755)


@contextmanager
def _exclusive_lock(path: Path, timeout_seconds: int = 600) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(1, timeout_seconds)
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "pid": os.getpid(),
                            "createdAt": datetime.now(UTC).isoformat(),
                        }
                    )
                )
            break
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                continue
            if age > _LOCK_STALE_SECONDS:
                path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise DotNetProvisionError(
                    f"Timed out waiting for .NET install lock: {path}"
                ) from None
            time.sleep(0.2)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _select_asset(metadata: dict[str, Any], host: DotNetHost) -> tuple[str, str, str]:
    version = str(metadata.get("latest-sdk", ""))
    if _VERSION_RE.fullmatch(version) is None:
        raise DotNetProvisionError(".NET metadata did not provide a stable latest-sdk")
    selected: dict[str, Any] | None = None
    releases = metadata.get("releases")
    if not isinstance(releases, list):
        raise DotNetProvisionError(".NET metadata releases must be an array")
    for release in releases:
        if not isinstance(release, dict):
            continue
        candidates: list[dict[str, Any]] = []
        sdk = release.get("sdk")
        if isinstance(sdk, dict):
            candidates.append(sdk)
        sdks = release.get("sdks")
        if isinstance(sdks, list):
            candidates.extend(value for value in sdks if isinstance(value, dict))
        for candidate in candidates:
            if str(candidate.get("version")) != version:
                continue
            files = candidate.get("files")
            if not isinstance(files, list):
                continue
            selected = next(
                (
                    value
                    for value in files
                    if isinstance(value, dict) and value.get("rid") == host.rid
                ),
                None,
            )
            if selected is not None:
                break
        if selected is not None:
            break
    if selected is None:
        raise DotNetProvisionError(f"No .NET SDK {version} asset exists for {host.rid}")
    url = str(selected.get("url", ""))
    digest = str(selected.get("hash", "")).casefold()
    if not _trusted_url(url) or _HASH_RE.fullmatch(digest) is None:
        raise DotNetProvisionError(".NET metadata selected an untrusted or unhashed asset")
    return version, url, digest


def _payload_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix().casefold()):
        if path.is_symlink():
            raise DotNetProvisionError(f"Managed .NET payload contains a symlink: {path}")
        if path.is_dir() or path.name == "dotnet-installation.json":
            continue
        if not path.is_file():
            raise DotNetProvisionError(f"Managed .NET payload contains a special file: {path}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _load_installation(path: Path) -> DotNetInstallation:
    value = _read_json(path)
    try:
        return DotNetInstallation(**value)
    except TypeError as error:
        raise DotNetProvisionError(f"Managed .NET receipt is invalid: {path}") from error


def _dotnet_process_environment(root: Path) -> dict[str, str]:
    return {
        **os.environ,
        "DOTNET_ROOT": str(root),
        "DOTNET_MULTILEVEL_LOOKUP": "0",
        "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "NUGET_XMLDOC_MODE": "skip",
    }


def verify_dotnet_installation(installation: DotNetInstallation) -> DotNetInstallation:
    if installation.schema_version != "1.0" or installation.channel != _DOTNET_CHANNEL:
        raise DotNetProvisionError("Managed .NET receipt identity is unsupported")
    if _VERSION_RE.fullmatch(installation.version) is None:
        raise DotNetProvisionError("Managed .NET receipt contains an invalid SDK version")
    platform_prefix = "win" if installation.platform == "windows" else installation.platform
    expected_rid = f"{platform_prefix}-{installation.architecture}"
    if (
        installation.platform not in {"windows", "linux"}
        or installation.architecture not in {"x64", "arm64"}
        or installation.rid != expected_rid
    ):
        raise DotNetProvisionError("Managed .NET receipt host identity is invalid")
    raw_root = Path(installation.root)
    raw_executable = Path(installation.executable)
    if raw_root.is_symlink() or raw_executable.is_symlink():
        raise DotNetProvisionError("Managed .NET installation may not use symbolic links")
    root = raw_root.resolve(strict=True)
    executable = raw_executable.resolve(strict=True)
    if not root.is_dir() or not executable.is_file():
        raise DotNetProvisionError("Managed .NET receipt paths are not regular files")
    if root not in [executable.parent, *executable.parents]:
        raise DotNetProvisionError("Managed .NET executable escapes its installation root")
    if _payload_hash(root) != installation.payload_sha256:
        raise DotNetProvisionError("Managed .NET payload integrity mismatch")
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
            env=_dotnet_process_environment(root),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DotNetProvisionError(f"Managed .NET version probe failed: {error}") from error
    if result.returncode != 0 or result.stdout.strip() != installation.version:
        raise DotNetProvisionError(
            "Managed .NET identity mismatch: "
            f"expected {installation.version}, observed "
            f"{result.stdout.strip() or result.stderr.strip()}"
        )
    return DotNetInstallation(
        **{**installation.to_dict(), "verified_at": datetime.now(UTC).isoformat()}
    )



def _load_release_metadata(
    metadata_path: Path,
    *,
    offline: bool,
    managed_cache: bool,
) -> dict[str, Any]:
    for attempt in range(2):
        if not metadata_path.exists():
            if offline:
                raise DotNetProvisionError(
                    "Offline mode requires cached .NET releases.json"
                )
            _download(_METADATA_URL, metadata_path, _MAX_METADATA_BYTES)
        try:
            return _read_json(metadata_path)
        except DotNetProvisionError:
            if offline or not managed_cache or attempt > 0:
                raise
            metadata_path.unlink(missing_ok=True)
    raise DotNetProvisionError("Could not load .NET release metadata")


def ensure_dotnet_sdk(
    *,
    root: Path | None = None,
    engine_root: Path | None = None,
    source_dir: Path | None = None,
    offline: bool = False,
    force: bool = False,
) -> DotNetInstallation:
    host = detect_dotnet_host()
    sdk_root = (root or default_dotnet_root(engine_root)).expanduser().resolve(strict=False)
    sdk_root.mkdir(parents=True, exist_ok=True)
    if sdk_root.is_symlink() or not sdk_root.is_dir():
        raise DotNetProvisionError("Managed .NET root must be a regular directory")
    current = sdk_root / f"current-{_DOTNET_CHANNEL}-{host.rid}.json"
    if current.is_symlink():
        raise DotNetProvisionError("Managed .NET current receipt may not be a symlink")
    if current.is_file() and not force:
        try:
            return verify_dotnet_installation(_load_installation(current))
        except (DotNetProvisionError, OSError):
            pass
    with _exclusive_lock(sdk_root / ".locks" / f"install-{host.rid}.lock"):
        if current.is_file() and not force:
            try:
                return verify_dotnet_installation(_load_installation(current))
            except (DotNetProvisionError, OSError):
                pass
        cache = sdk_root / ".downloads"
        cache.mkdir(parents=True, exist_ok=True)
        source: Path | None = None
        if source_dir is not None:
            source = source_dir.expanduser().resolve(strict=True)
            if source.is_symlink() or not source.is_dir():
                raise DotNetProvisionError("Offline .NET source must be a regular directory")
            metadata_path = source / "releases.json"
        else:
            metadata_path = cache / "releases.json"
        metadata = _load_release_metadata(
            metadata_path,
            offline=offline,
            managed_cache=source is None,
        )
        version, url, expected = _select_asset(metadata, host)
        asset_name = Path(urlparse(url).path).name
        if not asset_name or len(asset_name) > 240:
            raise DotNetProvisionError(".NET metadata selected an invalid archive name")
        archive_root = source if source is not None else cache
        archive = archive_root / asset_name
        if archive.exists() and _hash_file(archive, "sha512") != expected:
            if source_dir is not None or offline:
                raise DotNetProvisionError(f"SHA512 mismatch for offline .NET asset: {archive}")
            archive.unlink()
        if not archive.exists():
            if offline:
                raise DotNetProvisionError(f"Offline mode requires cached .NET asset: {asset_name}")
            _download(url, archive, _MAX_ARCHIVE_BYTES)
        observed = _hash_file(archive, "sha512")
        if observed != expected:
            archive.unlink(missing_ok=True)
            raise DotNetProvisionError(
                f"SHA512 mismatch for .NET asset: expected {expected}, observed {observed}"
            )
        destination = sdk_root / version / host.rid
        required_free = max(1024**3, archive.stat().st_size * 4)
        if shutil.disk_usage(sdk_root).free < required_free:
            raise DotNetProvisionError(
                f"Managed .NET installation requires at least {required_free} free bytes"
            )
        parent = destination.parent
        nonce = f"{os.getpid()}-{time.monotonic_ns()}"
        staging = parent / f".{destination.name}.staging-{nonce}"
        extracted = parent / f".{destination.name}.extract-{nonce}"
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(extracted, ignore_errors=True)
        try:
            if archive.suffix.casefold() == ".zip":
                _safe_extract_zip(archive, extracted)
            else:
                _safe_extract_tar(archive, extracted)
            payload = extracted
            children = list(extracted.iterdir())
            if len(children) == 1 and children[0].is_dir():
                payload = children[0]
            shutil.copytree(payload, staging, symlinks=False)
            executable = staging / host.executable_name
            if not executable.is_file() or executable.is_symlink():
                raise DotNetProvisionError(".NET SDK archive did not contain the dotnet host")
            if host.platform == "linux":
                executable.chmod(executable.stat().st_mode | 0o755)
            result = subprocess.run(
                [str(executable), "--version"],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
                env=_dotnet_process_environment(staging),
            )
            if result.returncode != 0 or result.stdout.strip() != version:
                raise DotNetProvisionError(
                    f"Installed .NET SDK failed its version probe: {result.stderr.strip()}"
                )
            installed_at = datetime.now(UTC).isoformat()
            receipt = DotNetInstallation(
                schema_version="1.0",
                channel=_DOTNET_CHANNEL,
                version=version,
                platform=host.platform,
                architecture=host.architecture,
                rid=host.rid,
                root=str(destination),
                executable=str(destination / host.executable_name),
                archive=asset_name,
                archive_sha512=expected,
                source_url=url,
                payload_sha256=_payload_hash(staging),
                installed_at=installed_at,
                verified_at=installed_at,
            )
            (staging / "dotnet-installation.json").write_text(
                json.dumps(receipt.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            if destination.exists():
                backup = parent / f".{destination.name}.old-{nonce}"
                shutil.rmtree(backup, ignore_errors=True)
                destination.replace(backup)
                try:
                    staging.replace(destination)
                except Exception:
                    backup.replace(destination)
                    raise
                shutil.rmtree(backup, ignore_errors=True)
            else:
                staging.replace(destination)
            installed = verify_dotnet_installation(
                _load_installation(destination / "dotnet-installation.json")
            )
            current_temporary = current.with_name(f"{current.name}.tmp-{nonce}")
            current_temporary.write_text(
                json.dumps(installed.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            current_temporary.replace(current)
            return installed
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(extracted, ignore_errors=True)


def list_dotnet_installations(root: Path | None = None) -> list[dict[str, Any]]:
    sdk_root = (root or default_dotnet_root()).expanduser().resolve(strict=False)
    if not sdk_root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for receipt in sorted(sdk_root.glob("*/*/dotnet-installation.json")):
        try:
            installation = verify_dotnet_installation(_load_installation(receipt))
            records.append({"status": "ready", **installation.to_dict()})
        except (DotNetProvisionError, OSError) as error:
            records.append({"status": "invalid", "receipt": str(receipt), "error": str(error)})
    return records


def dotnet_environment(
    root: Path | None = None,
    *,
    engine_root: Path | None = None,
) -> dict[str, str | None]:
    installations = [
        value
        for value in list_dotnet_installations(root or default_dotnet_root(engine_root))
        if value.get("status") == "ready"
    ]
    installations.sort(
        key=lambda value: tuple(int(part) for part in str(value["version"]).split(".")[:3]),
        reverse=True,
    )
    managed_path = (root or default_dotnet_root(engine_root)).expanduser().resolve(
        strict=False
    )
    managed_root = str(managed_path)
    values: dict[str, str | None] = {
        "EVAVO_DOTNET_HOME": managed_root,
        "DOTNET_MULTILEVEL_LOOKUP": "0",
        "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_NOLOGO": "1",
        "DOTNET_CLI_HOME": str(managed_path / "cli-home"),
        "NUGET_PACKAGES": str(managed_path / "nuget-packages"),
        "NUGET_XMLDOC_MODE": "skip",
    }
    if not installations:
        return values
    installation = installations[0]
    values.update(
        {
            "DOTNET_BIN": str(installation["executable"]),
            "DOTNET_ROOT": str(installation["root"]),
        }
    )
    return values


def mirror_dotnet_assets(
    destination: Path,
    *,
    rids: tuple[str, ...] = ("win-x64", "linux-x64"),
) -> dict[str, Any]:
    mirror_root = destination.expanduser().resolve(strict=False)
    mirror_root.mkdir(parents=True, exist_ok=True)
    if mirror_root.is_symlink() or not mirror_root.is_dir():
        raise DotNetProvisionError(".NET mirror destination must be a regular directory")
    metadata_path = mirror_root / "releases.json"
    _download(_METADATA_URL, metadata_path, _MAX_METADATA_BYTES)
    metadata = _read_json(metadata_path)
    host_map = {
        "win-x64": DotNetHost("windows", "x64", "win-x64", "dotnet.exe"),
        "win-arm64": DotNetHost("windows", "arm64", "win-arm64", "dotnet.exe"),
        "linux-x64": DotNetHost("linux", "x64", "linux-x64", "dotnet"),
        "linux-arm64": DotNetHost("linux", "arm64", "linux-arm64", "dotnet"),
    }
    if not rids or len(rids) != len(set(rids)):
        raise DotNetProvisionError(".NET mirror RIDs must be non-empty and unique")
    assets: list[dict[str, str]] = []
    for rid in rids:
        host = host_map.get(rid)
        if host is None:
            raise DotNetProvisionError(f"Unsupported .NET mirror RID: {rid}")
        version, url, expected = _select_asset(metadata, host)
        name = Path(urlparse(url).path).name
        archive = mirror_root / name
        for attempt in range(2):
            if not archive.exists():
                _download(url, archive, _MAX_ARCHIVE_BYTES)
            observed = _hash_file(archive, "sha512")
            if observed == expected:
                break
            archive.unlink(missing_ok=True)
            if attempt > 0:
                raise DotNetProvisionError(
                    f"SHA512 mismatch while mirroring .NET asset {name}"
                )
        assets.append(
            {
                "rid": rid,
                "version": version,
                "file": name,
                "sha512": expected,
                "sourceUrl": url,
            }
        )
    report = {
        "schemaVersion": "1.0",
        "status": "ready",
        "channel": _DOTNET_CHANNEL,
        "mirrorRoot": str(mirror_root),
        "assets": assets,
    }
    (mirror_root / "dotnet-mirror.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "DotNetHost",
    "DotNetInstallation",
    "DotNetProvisionError",
    "default_dotnet_root",
    "detect_dotnet_host",
    "dotnet_environment",
    "ensure_dotnet_sdk",
    "list_dotnet_installations",
    "mirror_dotnet_assets",
    "verify_dotnet_installation",
]

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .strict_json import StrictJsonError, load_strict_json_object

MAX_PATH_BYTES = 512
MAX_GIT_STATUS_ENTRIES = 200
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
HEX_40 = re.compile(r"^[0-9a-f]{40}$")


class AssetAuditError(RuntimeError):
    """Raised when an asset-audit authority boundary cannot be established."""


@dataclass(frozen=True)
class StableFile:
    path: Path
    size_bytes: int
    sha256: str
    payload: bytes | None = None


@dataclass(frozen=True)
class GitState:
    available: bool
    git_root: str | None
    project_subpath: str | None
    target_sha: str | None
    dirty: bool | None
    status_count: int
    status_sample: tuple[str, ...]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "gitRoot": self.git_root,
            "projectSubpath": self.project_subpath,
            "targetSha": self.target_sha,
            "dirty": self.dirty,
            "statusCount": self.status_count,
            "statusSample": list(self.status_sample),
            "error": self.error,
        }


def is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def paths_overlap(left: Path, right: Path) -> bool:
    return is_within(left, right) or is_within(right, left)


def _has_reparse_attribute(value: os.stat_result) -> bool:
    attributes = getattr(value, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(marker and attributes & marker)


def reject_link_components(path: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path.expanduser())))
    components = (absolute, *absolute.parents)
    for component in components:
        try:
            if not component.exists() and not component.is_symlink():
                continue
            info = component.lstat()
        except OSError as error:
            raise AssetAuditError(f"Could not inspect {label}: {component}") from error
        if stat.S_ISLNK(info.st_mode) or _has_reparse_attribute(info):
            raise AssetAuditError(f"{label} may not traverse a link or reparse point: {component}")
    return absolute


def normalize_relative_path(value: Any, *, label: str = "asset path") -> str:
    if not isinstance(value, str):
        raise AssetAuditError(f"{label} must be a string")
    if value != value.strip():
        raise AssetAuditError(f"{label} may not contain leading or trailing whitespace")
    candidate = unicodedata.normalize("NFC", value.replace("\\", "/"))
    if (
        not candidate
        or candidate.startswith("/")
        or ":" in candidate
        or "\x00" in candidate
        or re.match(r"^[A-Za-z]:", candidate)
    ):
        raise AssetAuditError(f"{label} must be a traversal-free relative path")
    if len(candidate.encode("utf-8")) > MAX_PATH_BYTES:
        raise AssetAuditError(f"{label} exceeds the {MAX_PATH_BYTES}-byte limit")
    parts = PurePosixPath(candidate).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise AssetAuditError(f"{label} must be a traversal-free relative path")
    for part in parts:
        if part.endswith((" ", ".")):
            raise AssetAuditError(f"{label} contains a Windows-ambiguous segment: {part!r}")
        stem = part.split(".", 1)[0].upper()
        if stem in WINDOWS_RESERVED_NAMES:
            raise AssetAuditError(f"{label} contains a Windows device-name segment: {part!r}")
        if any(ord(character) < 32 for character in part):
            raise AssetAuditError(f"{label} contains a control character")
    return PurePosixPath(*parts).as_posix()


def portable_path_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def resolve_directory(path: Path, label: str) -> Path:
    requested = reject_link_components(path, label)
    try:
        resolved = requested.resolve(strict=True)
    except OSError as error:
        raise AssetAuditError(f"{label} does not exist: {requested}") from error
    if not resolved.is_dir():
        raise AssetAuditError(f"{label} must be a directory: {resolved}")
    return resolved


def resolve_regular_file(path: Path, label: str) -> Path:
    requested = reject_link_components(path, label)
    try:
        resolved = requested.resolve(strict=True)
    except OSError as error:
        raise AssetAuditError(f"{label} does not exist: {requested}") from error
    if not resolved.is_file() or resolved.is_symlink():
        raise AssetAuditError(f"{label} must be a regular file: {resolved}")
    return resolved


def resolve_project_file(project: Path, relative: str) -> Path:
    normalized = normalize_relative_path(relative)
    requested = reject_link_components(
        project.joinpath(*PurePosixPath(normalized).parts),
        f"Asset path {normalized}",
    )
    try:
        resolved = requested.resolve(strict=True)
    except OSError as error:
        raise AssetAuditError(f"Asset file is missing: {normalized}") from error
    if not is_within(resolved, project):
        raise AssetAuditError(f"Asset path resolves outside the project: {normalized}")
    if not resolved.is_file() or resolved.is_symlink():
        raise AssetAuditError(f"Asset path is not a regular in-project file: {normalized}")
    return resolved


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def read_stable_regular_file(
    path: Path,
    *,
    maximum_bytes: int,
    retain_payload: bool = False,
) -> StableFile:
    if maximum_bytes < 1:
        raise AssetAuditError("maximum_bytes must be positive")
    source = resolve_regular_file(path, "Asset file")
    try:
        path_before = source.lstat()
    except OSError as error:
        raise AssetAuditError(f"Asset file is unavailable: {source}") from error
    if not stat.S_ISREG(path_before.st_mode) or _has_reparse_attribute(path_before):
        raise AssetAuditError(f"Asset file must be regular and non-reparse: {source}")
    if path_before.st_size > maximum_bytes:
        raise AssetAuditError(
            f"Asset file exceeds the bounded {maximum_bytes}-byte limit: {source}"
        )

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as error:
        raise AssetAuditError(f"Asset file could not be opened: {source}") from error

    digest = hashlib.sha256()
    chunks: list[bytes] | None = [] if retain_payload else None
    bytes_read = 0
    try:
        opened_before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_before.st_mode)
            or _has_reparse_attribute(opened_before)
            or not os.path.samestat(path_before, opened_before)
        ):
            raise AssetAuditError("Asset path changed before it was opened")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > maximum_bytes:
                raise AssetAuditError(
                    f"Asset file exceeds the bounded {maximum_bytes}-byte limit"
                )
            digest.update(chunk)
            if chunks is not None:
                chunks.append(chunk)
        opened_after = os.fstat(descriptor)
    except OSError as error:
        raise AssetAuditError(f"Asset file could not be read: {source}") from error
    finally:
        os.close(descriptor)

    try:
        path_after = source.lstat()
    except OSError as error:
        raise AssetAuditError("Asset path changed while it was read") from error
    if (
        not os.path.samestat(opened_before, opened_after)
        or not os.path.samestat(opened_after, path_after)
        or _stat_signature(path_before) != _stat_signature(path_after)
        or _stat_signature(opened_before) != _stat_signature(opened_after)
        or bytes_read != opened_after.st_size
    ):
        raise AssetAuditError("Asset file changed while it was read")
    payload = b"".join(chunks) if chunks is not None else None
    return StableFile(
        path=source,
        size_bytes=bytes_read,
        sha256=digest.hexdigest(),
        payload=payload,
    )


def inventory_art_files(
    project: Path,
    *,
    extensions: frozenset[str],
    ignored_directories: frozenset[str],
    maximum_files: int,
) -> dict[str, Path]:
    if maximum_files < 1:
        raise AssetAuditError("maximum_files must be positive")
    inventory: dict[str, Path] = {}
    identities: dict[str, str] = {}
    ignored = {name.casefold() for name in ignored_directories}
    files_seen = 0
    stack = [project]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        except OSError as error:
            raise AssetAuditError(f"Could not inventory project directory: {directory}") from error
        for entry in entries:
            if entry.name.casefold() in ignored:
                continue
            try:
                info = entry.lstat()
            except OSError as error:
                raise AssetAuditError(f"Could not inspect project entry: {entry}") from error
            if stat.S_ISLNK(info.st_mode) or _has_reparse_attribute(info):
                raise AssetAuditError(
                    "Project inventory traverses a link or reparse point: "
                    f"{entry}"
                )
            if stat.S_ISDIR(info.st_mode):
                stack.append(entry)
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            files_seen += 1
            if files_seen > maximum_files:
                raise AssetAuditError(
                    f"Project exceeds the bounded {maximum_files}-file inventory limit"
                )
            if entry.suffix.lower() not in extensions:
                continue
            relative = normalize_relative_path(
                entry.relative_to(project).as_posix(),
                label="Current project asset path",
            )
            identity = portable_path_key(relative)
            previous = identities.get(identity)
            if previous is not None and previous != relative:
                raise AssetAuditError(
                    "Project contains case-insensitive or Unicode-normalized asset collision: "
                    f"{previous!r} and {relative!r}"
                )
            identities[identity] = relative
            inventory[relative] = entry
    return dict(sorted(inventory.items()))


def _git_text(root: Path, arguments: list[str], label: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AssetAuditError(f"{label} could not run") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise AssetAuditError(f"{label} failed: {detail or 'git returned an error'}")
    return result.stdout.strip()


def read_git_state(project: Path) -> GitState:
    try:
        git_root = resolve_directory(
            Path(_git_text(project, ["rev-parse", "--show-toplevel"], "Resolve target Git root")),
            "Target Git root",
        )
        project_subpath = project.relative_to(git_root).as_posix() or "."
        target_sha = _git_text(git_root, ["rev-parse", "HEAD"], "Read target SHA").lower()
        if not HEX_40.fullmatch(target_sha):
            raise AssetAuditError("Target Git SHA is not a lowercase 40-character digest")
        status = _git_text(
            git_root,
            ["status", "--porcelain=v1", "--untracked-files=all"],
            "Read target status",
        )
        lines = tuple(line for line in status.splitlines() if line)
        return GitState(
            available=True,
            git_root=str(git_root),
            project_subpath=project_subpath,
            target_sha=target_sha,
            dirty=bool(lines),
            status_count=len(lines),
            status_sample=lines[:MAX_GIT_STATUS_ENTRIES],
        )
    except AssetAuditError as error:
        return GitState(
            available=False,
            git_root=None,
            project_subpath=None,
            target_sha=None,
            dirty=None,
            status_count=0,
            status_sample=(),
            error=str(error),
        )


def default_lab_root() -> Path:
    source = Path(__file__).resolve()
    for parent in source.parents:
        project = parent / "pyproject.toml"
        if project.is_file():
            return parent
    return source.parent


def default_evidence_root() -> Path:
    configured = os.environ.get("EVAVO_GODOT_LAB_EVIDENCE_ROOT", "").strip()
    if configured:
        return Path(configured)
    if os.name == "nt":
        return Path(r"C:\GodotLabEvidence")
    return Path.home() / ".local" / "share" / "EVAVO" / "GodotLabEvidence"


def _prepare_evidence_root(candidate: Path, protected_roots: tuple[Path, ...]) -> Path:
    if not candidate.is_absolute():
        raise AssetAuditError("Evidence root must be an absolute path")
    requested = reject_link_components(candidate, "Asset-audit evidence root")
    for protected in protected_roots:
        if paths_overlap(requested, protected):
            raise AssetAuditError(
                "Asset-audit evidence root must remain disjoint from source roots"
            )
    requested.mkdir(parents=True, exist_ok=True)
    resolved = resolve_directory(requested, "Asset-audit evidence root")
    for protected in protected_roots:
        if paths_overlap(resolved, protected):
            raise AssetAuditError(
                "Resolved asset-audit evidence root overlaps a source root"
            )
    return resolved


def _existing_report_is_replaceable(path: Path) -> bool:
    try:
        value, _ = load_strict_json_object(path, maximum_bytes=64 * 1024 * 1024)
    except (StrictJsonError, OSError, ValueError):
        return False
    return (
        value.get("tool") == "godot-game-test-lab"
        and value.get("check") == "art-studio-asset-audit"
        and value.get("schemaVersion") in {"1.0", "1.1"}
    )


def write_evidence_json(
    value: dict[str, Any],
    *,
    output: Path,
    evidence_root: Path,
    protected_roots: tuple[Path, ...],
    replace: bool = False,
) -> Path:
    root = _prepare_evidence_root(evidence_root, protected_roots)
    destination = output.expanduser()
    if not destination.is_absolute():
        destination = root / destination
    destination = Path(os.path.abspath(os.fspath(destination)))
    reject_link_components(destination, "Asset-audit output")
    if destination == root or not is_within(destination, root):
        raise AssetAuditError("Asset-audit output must remain strictly beneath EvidenceRoot")
    parent = destination.parent
    reject_link_components(parent, "Asset-audit output parent")
    if not is_within(parent, root):
        raise AssetAuditError("Asset-audit output parent must remain beneath EvidenceRoot")
    parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = resolve_directory(parent, "Asset-audit output parent")
    if not is_within(resolved_parent, root):
        raise AssetAuditError("Resolved asset-audit output parent escaped EvidenceRoot")

    replace_identity: os.stat_result | None = None
    if destination.exists():
        existing = resolve_regular_file(destination, "Existing asset-audit output")
        if not replace:
            raise AssetAuditError(f"Asset-audit output already exists: {existing}")
        replace_identity = existing.lstat()
        if not _existing_report_is_replaceable(existing):
            raise AssetAuditError(
                "Existing output is not a prior Godot Lab asset-audit report; refusing overwrite"
            )
        after_admission = existing.lstat()
        if (
            not os.path.samestat(replace_identity, after_admission)
            or _stat_signature(replace_identity) != _stat_signature(after_admission)
        ):
            raise AssetAuditError(
                "Existing asset-audit output changed during replacement admission"
            )
        replace_identity = after_admission

    content = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    encoded = content.encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.tmp-",
            dir=resolved_parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        reject_link_components(temporary_path, "Temporary asset-audit output")
        if replace:
            if replace_identity is None:
                raise AssetAuditError(
                    "Replacement was requested without an admitted existing report"
                )
            current_identity = destination.lstat()
            if (
                not os.path.samestat(replace_identity, current_identity)
                or _stat_signature(replace_identity) != _stat_signature(current_identity)
            ):
                raise AssetAuditError(
                    "Existing asset-audit output changed before atomic replacement"
                )
            os.replace(temporary_path, destination)
            temporary_path = None
        else:
            try:
                os.link(temporary_path, destination)
            except FileExistsError as error:
                raise AssetAuditError(
                    f"Asset-audit output already exists: {destination}"
                ) from error
            except OSError:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                flags |= getattr(os, "O_BINARY", 0)
                descriptor = os.open(destination, flags, 0o600)
                try:
                    view = memoryview(encoded)
                    while view:
                        written = os.write(descriptor, view)
                        if written < 1:
                            raise AssetAuditError(
                                "Asset-audit output write made no progress"
                            )
                        view = view[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            temporary_path.unlink(missing_ok=True)
            temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    final = resolve_regular_file(destination, "Written asset-audit output")
    if not is_within(final, root):
        raise AssetAuditError("Written asset-audit output escaped EvidenceRoot")
    return final

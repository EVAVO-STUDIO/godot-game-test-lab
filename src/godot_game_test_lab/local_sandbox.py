from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from . import __version__
from .engine_manager import EngineProvisionError, load_engine_lock

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_MEMORY_RE = re.compile(r"^[1-9][0-9]*(?:[kKmMgG])?$")
_MAX_PROCESS_OUTPUT = 16 * 1024 * 1024
_MAX_PROFILE_BYTES = 4 * 1024 * 1024
_MAX_ARTIFACT_FILES = 100_000
_MAX_ARTIFACT_BYTES = 50 * 1024**3


class SandboxError(RuntimeError):
    """Raised when a local Docker sandbox request is unsafe or cannot run."""


@dataclass(frozen=True, slots=True)
class ProcessReceipt:
    command: list[str]
    exit_code: int
    timed_out: bool
    duration_seconds: float
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SandboxProfile:
    source_path: str
    normalized_path: str
    schema_version: str
    project_subpath: str
    minimum_godot_version: str
    engine_version: str
    engine_flavor: str
    visual_scene: str
    visual_frames: int
    visual_fps: int
    visual_width: int
    visual_height: int
    rendering_method: str
    visual_arguments_json: str
    export_preset: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def _reject_symlink_components(path: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path.expanduser())))
    for component in (absolute, *absolute.parents):
        try:
            if component.exists() and component.is_symlink():
                raise SandboxError(f"{label} may not traverse a symbolic link: {component}")
        except OSError as error:
            raise SandboxError(f"Could not inspect {label}: {component}") from error
    return absolute


def _safe_mount_path(path: Path, label: str) -> str:
    value = str(path)
    if not value or any(character in value for character in ("\x00", "\r", "\n", ",")):
        raise SandboxError(f"{label} contains a character unsupported by Docker --mount")
    return value


def _bounded_output(value: bytes, maximum: int = _MAX_PROCESS_OUTPUT) -> str:
    if len(value) <= maximum:
        return value.decode("utf-8", errors="replace")
    head = maximum // 2
    tail = maximum - head
    omitted = len(value) - maximum
    payload = (
        value[:head]
        + f"\n[godot-lab output truncated: {omitted} byte(s) omitted]\n".encode()
        + value[-tail:]
    )
    return payload.decode("utf-8", errors="replace")


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        try:
            process.terminate()
        except OSError:
            return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            try:
                process.kill()
            except OSError:
                pass


def _read_bounded_stream(handle: BinaryIO, maximum: int) -> str:
    handle.flush()
    size = handle.seek(0, os.SEEK_END)
    handle.seek(0)
    if size <= maximum:
        payload = handle.read(maximum + 1)
    else:
        head = maximum // 2
        tail = maximum - head
        first = handle.read(head)
        handle.seek(max(0, size - tail))
        last = handle.read(tail)
        omitted = max(0, size - len(first) - len(last))
        payload = (
            first
            + f"\n[godot-lab output truncated: {omitted} byte(s) omitted]\n".encode()
            + last
        )
    return payload.decode("utf-8", errors="replace")


def _run_process(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    stdout_file: Path | None = None,
    stderr_file: Path | None = None,
    maximum_output_bytes: int = _MAX_PROCESS_OUTPUT,
) -> ProcessReceipt:
    if maximum_output_bytes < 1024:
        raise SandboxError("maximum_output_bytes must be at least 1024")
    started = time.monotonic()
    output_handle: BinaryIO | None = None
    error_handle: BinaryIO | None = None
    shared_output = False
    output_is_temporary = stdout_file is None
    error_is_temporary = stderr_file is None
    try:
        if stdout_file is not None:
            stdout_file.parent.mkdir(parents=True, exist_ok=True)
            output_handle = stdout_file.open("wb")
        else:
            output_handle = tempfile.TemporaryFile(mode="w+b")
        if stderr_file is not None:
            stderr_file.parent.mkdir(parents=True, exist_ok=True)
            if stdout_file is not None and stderr_file.resolve() == stdout_file.resolve():
                shared_output = True
                error_is_temporary = False
            else:
                error_handle = stderr_file.open("wb")
        else:
            error_handle = tempfile.TemporaryFile(mode="w+b")
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=output_handle,
            stderr=(subprocess.STDOUT if shared_output else error_handle),
            start_new_session=os.name != "nt",
        )
        try:
            process.wait(timeout=timeout_seconds)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_tree(process)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(process)
        stdout = (
            _read_bounded_stream(output_handle, maximum_output_bytes)
            if output_is_temporary
            else ""
        )
        stderr = (
            _read_bounded_stream(error_handle, maximum_output_bytes)
            if error_is_temporary and error_handle is not None
            else ""
        )
        return ProcessReceipt(
            command=list(command),
            exit_code=int(process.returncode if process.returncode is not None else -1),
            timed_out=timed_out,
            duration_seconds=round(time.monotonic() - started, 3),
            stdout=stdout,
            stderr=stderr,
        )
    except OSError as error:
        raise SandboxError(f"Could not start command {command[0]!r}: {error}") from error
    finally:
        if output_handle is not None:
            output_handle.close()
        if error_handle is not None:
            error_handle.close()


def _git_text(root: Path, arguments: Sequence[str], timeout_seconds: int = 30) -> str:
    result = _run_process(
        ["git", "-C", str(root), *arguments],
        cwd=root,
        timeout_seconds=timeout_seconds,
    )
    if result.timed_out or result.exit_code != 0:
        output = (result.stderr or result.stdout).strip()
        raise SandboxError(f"Git command failed: {' '.join(arguments)}: {output}")
    return result.stdout.strip()


def _validate_sha(value: str, label: str) -> str:
    if _SHA_RE.fullmatch(value) is None:
        raise SandboxError(f"{label} must be a lowercase 40-character commit SHA")
    return value


def _resolve_git_root(candidate: Path, label: str) -> Path:
    requested_path = _reject_symlink_components(candidate, label)
    requested = requested_path.resolve(strict=True)
    if not requested.is_dir():
        raise SandboxError(f"{label} must be a regular directory")
    observed = Path(_git_text(requested, ["rev-parse", "--show-toplevel"])).resolve(
        strict=True
    )
    if observed != requested:
        raise SandboxError(f"{label} must be the Git repository root: {observed}")
    return requested


def _require_clean_exact_checkout(
    root: Path,
    label: str,
    expected_sha: str | None,
) -> str:
    observed = _validate_sha(_git_text(root, ["rev-parse", "HEAD"]), f"{label} SHA")
    if expected_sha is not None and observed != _validate_sha(
        expected_sha, f"expected {label} SHA"
    ):
        raise SandboxError(f"{label} HEAD {observed} does not match {expected_sha}")
    status = _git_text(root, ["status", "--porcelain=v1", "--untracked-files=all"])
    if status:
        sample = "; ".join(status.splitlines()[:12])
        raise SandboxError(f"{label} must be clean for exact-SHA sandbox evidence: {sample}")
    staged = _git_text(root, ["ls-files", "--stage"])
    gitlinks = [line for line in staged.splitlines() if line.startswith("160000 ")]
    if gitlinks:
        raise SandboxError(
            f"{label} contains Git submodules; local sandbox runs fail closed until "
            "submodule SHAs are separately materialized and attested"
        )
    return observed


def _allowed_target_roots(values: Sequence[Path] | None) -> tuple[Path, ...]:
    roots: list[Path] = []
    requested = list(values or [])
    configured = os.environ.get("EVAVO_GODOT_LAB_ALLOWED_ROOTS", "").strip()
    if not requested and configured:
        requested = [Path(value) for value in configured.split(os.pathsep) if value.strip()]
    for item in requested:
        requested_root = _reject_symlink_components(item, "Allowed target root")
        resolved = requested_root.resolve(strict=True)
        if not resolved.is_dir():
            raise SandboxError(f"Allowed target root must be a regular directory: {item}")
        roots.append(resolved)
    return tuple(roots)


def _resolve_target(
    candidate: Path,
    allowed_roots: Sequence[Path] | None,
) -> Path:
    target = _resolve_git_root(candidate, "Target repository")
    roots = _allowed_target_roots(allowed_roots)
    if roots and not any(_is_within(target, root) for root in roots):
        raise SandboxError(
            f"Target repository is outside the configured allowed roots: {target}"
        )
    return target


def _resolve_profile(target: Path, value: Path) -> Path:
    requested = value.expanduser()
    candidate = requested if requested.is_absolute() else target / requested
    safe_candidate = _reject_symlink_components(candidate, "Sandbox profile")
    profile = safe_candidate.resolve(strict=True)
    if not profile.is_file() or not _is_within(profile, target):
        raise SandboxError("Sandbox profile must be a regular file inside the target repository")
    relative = profile.relative_to(target).as_posix()
    _git_text(target, ["ls-files", "--error-unmatch", "--", relative])
    if profile.stat().st_size > _MAX_PROFILE_BYTES:
        raise SandboxError("Sandbox profile exceeds the bounded JSON size limit")
    return profile


def _resolve_external_artifacts(
    candidate: Path,
    *,
    lab_root: Path,
    target_root: Path,
    allowed_root: Path | None = None,
) -> Path:
    requested = candidate.expanduser()

    configured = os.environ.get("EVAVO_GODOT_LAB_EVIDENCE_ROOT", "").strip()
    requested_root = allowed_root or (Path(configured) if configured else None)
    resolved_allowed: Path | None = None
    if requested_root is not None:
        allowed_candidate = _reject_symlink_components(
            requested_root, "Allowed sandbox artifact root"
        )
        resolved_allowed = allowed_candidate.resolve(strict=True)
        if not resolved_allowed.is_dir():
            raise SandboxError("Allowed sandbox artifact root must be a regular directory")
        absolute = _reject_symlink_components(
            requested if requested.is_absolute() else resolved_allowed / requested,
            "Sandbox artifacts",
        )
        try:
            relative = absolute.relative_to(resolved_allowed)
        except ValueError as error:
            raise SandboxError(
                f"Sandbox artifacts must remain beneath the allowed root: {resolved_allowed}"
            ) from error
        cursor = resolved_allowed
        for part in relative.parent.parts:
            cursor = cursor / part
            if cursor.exists() and cursor.is_symlink():
                raise SandboxError(
                    f"Sandbox artifact parent may not traverse a symbolic link: {cursor}"
                )
        requested = absolute

    requested = _reject_symlink_components(requested, "Sandbox artifacts")
    requested.parent.mkdir(parents=True, exist_ok=True)
    parent = _reject_symlink_components(
        requested.parent, "Sandbox artifact parent"
    ).resolve(strict=True)
    if not parent.is_dir():
        raise SandboxError("Sandbox artifact parent must be a regular directory")
    artifacts = (parent / requested.name).resolve(strict=False)
    if artifacts.exists():
        if artifacts.is_symlink() or not artifacts.is_dir():
            raise SandboxError("Sandbox artifacts must be a regular directory")
        if any(artifacts.iterdir()):
            raise SandboxError("Sandbox artifact directory must be new or empty")
    if _is_within(artifacts, lab_root) or _is_within(artifacts, target_root):
        raise SandboxError("Sandbox artifacts must remain outside Lab and target checkouts")
    if resolved_allowed is not None and not _is_within(artifacts, resolved_allowed):
        raise SandboxError(
            f"Sandbox artifacts must remain beneath the allowed root: {resolved_allowed}"
        )
    artifacts.mkdir(parents=False, exist_ok=True)
    return artifacts.resolve(strict=True)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SandboxError(f"Could not read normalized sandbox profile: {error}") from error
    if not isinstance(value, dict):
        raise SandboxError("Normalized sandbox profile root must be an object")
    return value


def _detect_csharp(project_root: Path) -> bool:
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
            raise SandboxError("C# sandbox discovery exceeded the bounded entry limit")
        if any(name.casefold().endswith((".cs", ".csproj")) for name in files):
            return True
    return False


def _select_sandbox_engine_version(minimum: str) -> str:
    if _VERSION_RE.fullmatch(minimum) is None:
        raise SandboxError("Normalized minimumGodotVersion is invalid")
    governed = load_engine_lock()
    minimum_tuple = tuple(map(int, minimum.split(".")))
    governed_minimum = tuple(map(int, governed.minimum_version.split(".")))
    if minimum_tuple < governed_minimum:
        raise SandboxError(
            f"Sandbox Godot {minimum} is below the governed minimum "
            f"{governed.minimum_version}"
        )
    branch = ".".join(minimum.split(".")[:2])
    selected = governed.channels.get(branch)
    if selected is None:
        raise SandboxError(
            f"Sandbox profile requires unmapped Godot branch {branch}; "
            "update godot-engine-lock.json"
        )
    if tuple(map(int, selected.split("."))) < minimum_tuple:
        raise SandboxError(
            f"Governed Godot {selected} is older than the profile minimum {minimum}"
        )
    return selected


def _normalize_profile(
    *,
    lab_root: Path,
    target_root: Path,
    profile_path: Path,
    work_root: Path,
    expected_project_subpath: str | None,
) -> SandboxProfile:
    normalizer = lab_root / "scripts" / "read_linux_sandbox_profile.py"
    if normalizer.is_symlink() or not normalizer.is_file():
        raise SandboxError(f"Linux sandbox profile normalizer is missing: {normalizer}")
    normalized = work_root / "profile.normalized.json"
    github_output = work_root / "profile.outputs"
    result = _run_process(
        [
            sys.executable,
            str(normalizer),
            "--profile",
            str(profile_path),
            "--github-output",
            str(github_output),
            "--output",
            str(normalized),
        ],
        cwd=lab_root,
        timeout_seconds=60,
    )
    if result.timed_out or result.exit_code != 0:
        raise SandboxError(
            "Linux sandbox profile normalization failed: "
            + (result.stderr or result.stdout).strip()
        )
    value = _read_json_object(normalized)
    schema = str(value.get("schemaVersion", ""))
    project_subpath = str(value.get("projectSubpath", "."))
    pure = PurePosixPath(project_subpath)
    if (
        not project_subpath
        or pure.is_absolute()
        or any(part in {"", ".."} for part in pure.parts)
    ):
        raise SandboxError("Normalized projectSubpath is unsafe")
    if expected_project_subpath is not None:
        expected = expected_project_subpath.replace("\\", "/").strip() or "."
        if expected != project_subpath:
            raise SandboxError(
                f"Profile projectSubpath {project_subpath!r} does not match "
                f"the requested projectSubpath {expected!r}"
            )
    project_root = (target_root / Path(*pure.parts)).resolve(strict=True)
    if not project_root.is_dir() or not _is_within(project_root, target_root):
        raise SandboxError("Normalized projectSubpath does not identify a target directory")
    project_file = project_root / "project.godot"
    if project_file.is_symlink() or not project_file.is_file():
        raise SandboxError("Normalized projectSubpath does not contain project.godot")
    minimum = str(value.get("minimumGodotVersion", ""))
    selected_version = _select_sandbox_engine_version(minimum)
    requested_flavor = str(value.get("engineFlavor", "auto"))
    csharp = _detect_csharp(project_root)
    if requested_flavor == "auto":
        flavor = "mono" if csharp else "standard"
    elif requested_flavor in {"standard", "mono"}:
        flavor = requested_flavor
    else:
        raise SandboxError("Normalized engineFlavor must be auto, standard, or mono")
    if csharp and flavor != "mono":
        raise SandboxError("C# sandbox projects require engineFlavor=mono or auto")
    visual = value.get("visual", {})
    export = value.get("export", {})
    if not isinstance(visual, dict) or not isinstance(export, dict):
        raise SandboxError("Normalized visual and export values must be objects")
    arguments = visual.get("userArguments", [])
    if not isinstance(arguments, list) or any(not isinstance(item, str) for item in arguments):
        raise SandboxError("Normalized visual.userArguments must be an array of strings")
    return SandboxProfile(
        source_path=str(profile_path),
        normalized_path=str(normalized),
        schema_version=schema,
        project_subpath=project_subpath,
        minimum_godot_version=minimum,
        engine_version=selected_version,
        engine_flavor=flavor,
        visual_scene=str(visual.get("scene", "")),
        visual_frames=int(visual.get("frames", 0)),
        visual_fps=int(visual.get("fps", 30)),
        visual_width=int(visual.get("width", 1280)),
        visual_height=int(visual.get("height", 720)),
        rendering_method=str(visual.get("renderingMethod", "gl_compatibility")),
        visual_arguments_json=json.dumps(arguments, separators=(",", ":")),
        export_preset=str(export.get("preset", "")),
    )


def _docker_binary(value: str) -> str:
    if not value.strip() or any(character in value for character in ("\x00", "\r", "\n")):
        raise SandboxError("Docker executable is invalid")
    resolved = shutil.which(value) if not Path(value).is_absolute() else value
    if not resolved:
        raise SandboxError(
            "Docker was not found. Install Docker Desktop on Windows or Docker Engine on Linux."
        )
    return str(Path(resolved).resolve(strict=True))


def docker_status(docker: str = "docker") -> dict[str, Any]:
    executable = _docker_binary(docker)
    version = _run_process(
        [executable, "version", "--format", "{{json .}}"],
        cwd=Path.cwd(),
        timeout_seconds=30,
    )
    info = _run_process(
        [executable, "info", "--format", "{{.OSType}}"],
        cwd=Path.cwd(),
        timeout_seconds=30,
    )
    ready = (
        not version.timed_out
        and version.exit_code == 0
        and not info.timed_out
        and info.exit_code == 0
        and info.stdout.strip() == "linux"
    )
    images: list[dict[str, Any]] = []
    if ready:
        listed = _run_process(
            [
                executable,
                "image",
                "ls",
                "--filter",
                "label=org.evavo.godot-lab=true",
                "--format",
                "{{json .}}",
            ],
            cwd=Path.cwd(),
            timeout_seconds=30,
        )
        if listed.exit_code == 0:
            for line in listed.stdout.splitlines()[:256]:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    images.append(item)
    return {
        "schemaVersion": "1.0",
        "status": "ready" if ready else "blocked",
        "docker": executable,
        "linuxContainers": info.stdout.strip() == "linux",
        "version": version.to_dict(),
        "info": info.to_dict(),
        "images": images,
    }


def _resolve_lab_root(candidate: Path | None) -> Path:
    root = candidate or Path(os.environ.get("EVAVO_GODOT_LAB_ROOT", "").strip() or Path.cwd())
    resolved = _resolve_git_root(root, "Lab repository")
    required = [
        resolved / "containers" / "linux-sandbox" / "Dockerfile",
        resolved / "scripts" / "linux-sandbox-entrypoint.sh",
        resolved / "scripts" / "read_linux_sandbox_profile.py",
    ]
    if any(path.is_symlink() or not path.is_file() for path in required):
        raise SandboxError("Lab repository is missing the Linux sandbox source contract")
    return resolved


def _governed_version(value: str | None) -> str:
    lock = load_engine_lock()
    version = value or lock.default_version
    if version not in lock.channels.values():
        raise SandboxError(
            f"Sandbox images may use only governed Godot releases: "
            f"{', '.join(sorted(set(lock.channels.values())))}"
        )
    return version


def _image_tag(version: str, flavor: str, lab_sha: str) -> str:
    return f"evavo-godot-lab:{version}-{flavor}-{lab_sha[:12]}"


def _expected_image_labels(version: str, flavor: str, lab_sha: str) -> dict[str, str]:
    return {
        "org.evavo.godot-lab": "true",
        "org.evavo.godot-lab.version": __version__,
        "org.evavo.godot.version": version,
        "org.evavo.godot.flavor": flavor,
        "org.evavo.lab.sha": lab_sha,
    }


def _inspect_image(
    executable: str, image: str, *, cwd: Path
) -> dict[str, Any] | None:
    result = _run_process(
        [executable, "image", "inspect", image],
        cwd=cwd,
        timeout_seconds=30,
    )
    if result.timed_out or result.exit_code != 0:
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SandboxError(f"Docker returned invalid image metadata for {image}") from error
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise SandboxError(f"Docker returned ambiguous image metadata for {image}")
    return value[0]


def _image_labels_match(
    metadata: dict[str, Any], expected: dict[str, str]
) -> bool:
    config = metadata.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if not isinstance(labels, dict):
        return False
    return all(str(labels.get(key, "")) == value for key, value in expected.items())


def _image_receipt(
    *,
    image: str,
    version: str,
    flavor: str,
    lab_sha: str,
    metadata: dict[str, Any],
    reused: bool,
) -> dict[str, Any]:
    return {
        "schemaVersion": "1.1",
        "status": "ready",
        "reused": reused,
        "image": image,
        "imageId": metadata.get("Id"),
        "godotVersion": version,
        "engineFlavor": flavor,
        "labSha": lab_sha,
        "labels": _expected_image_labels(version, flavor, lab_sha),
    }


def build_sandbox_image(
    *,
    lab_root: Path,
    lab_sha: str,
    version: str,
    flavor: str,
    docker: str = "docker",
    rebuild: bool = False,
    timeout_seconds: int = 1800,
    log_path: Path | None = None,
) -> dict[str, Any]:
    if flavor not in {"standard", "mono"}:
        raise SandboxError("Sandbox image flavor must be standard or mono")
    version = _governed_version(version)
    executable = _docker_binary(docker)
    status = docker_status(executable)
    if status["status"] != "ready":
        raise SandboxError("Docker must be running with Linux containers enabled")
    image = _image_tag(version, flavor, lab_sha)
    expected_labels = _expected_image_labels(version, flavor, lab_sha)
    metadata = _inspect_image(executable, image, cwd=lab_root)
    if metadata is not None and not rebuild and _image_labels_match(
        metadata, expected_labels
    ):
        return _image_receipt(
            image=image,
            version=version,
            flavor=flavor,
            lab_sha=lab_sha,
            metadata=metadata,
            reused=True,
        )
    command = [
        executable,
        "build",
        "--pull",
        "--build-arg",
        f"GODOT_VERSION={version}",
        "--build-arg",
        f"GODOT_FLAVOR={flavor}",
        "--label",
        "org.evavo.godot-lab=true",
        "--label",
        f"org.evavo.godot-lab.version={__version__}",
        "--label",
        f"org.evavo.godot.version={version}",
        "--label",
        f"org.evavo.godot.flavor={flavor}",
        "--label",
        f"org.evavo.lab.sha={lab_sha}",
        "--tag",
        image,
        "--file",
        str(lab_root / "containers" / "linux-sandbox" / "Dockerfile"),
    ]
    if rebuild:
        command.append("--no-cache")
    command.append(str(lab_root))
    result = _run_process(
        command,
        cwd=lab_root,
        timeout_seconds=timeout_seconds,
        stdout_file=log_path,
        stderr_file=log_path,
    )
    if result.timed_out or result.exit_code != 0:
        raise SandboxError(
            f"Docker could not build the checksum-verified Godot image; "
            f"inspect {log_path or 'the Docker build output'}"
        )
    metadata = _inspect_image(executable, image, cwd=lab_root)
    if metadata is None or not _image_labels_match(metadata, expected_labels):
        raise SandboxError(
            "Built Docker image did not retain the exact Lab/Godot identity labels"
        )
    receipt = _image_receipt(
        image=image,
        version=version,
        flavor=flavor,
        lab_sha=lab_sha,
        metadata=metadata,
        reused=False,
    )
    receipt["build"] = result.to_dict()
    receipt["log"] = str(log_path) if log_path else None
    return receipt


def _docker_run_command(
    *,
    docker: str,
    container_name: str,
    image: str,
    target: Path,
    normalized_profile: Path,
    work_root: Path,
    artifacts: Path,
    target_name: str,
    target_sha: str,
    lab_sha: str,
    profile: SandboxProfile,
    timeout_seconds: int,
    boot_frames: int,
    cpus: float,
    memory: str,
    memory_swap: str,
    pids_limit: int,
    nofile_limit: int,
    shm_size: str,
) -> list[str]:
    return [
        docker,
        "run",
        "--rm",
        "--name",
        container_name,
        "--stop-timeout",
        "10",
        "--user",
        "10001:10001",
        "--ipc",
        "private",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        str(pids_limit),
        "--cpus",
        str(cpus),
        "--memory",
        memory,
        "--memory-swap",
        memory_swap,
        "--ulimit",
        f"nofile={nofile_limit}:{nofile_limit}",
        "--ulimit",
        "core=0",
        "--shm-size",
        shm_size,
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=1g,mode=1777",
        "--tmpfs",
        "/home/godotlab:rw,nosuid,nodev,size=2g,mode=0700,uid=10001,gid=10001",
        "--mount",
        "type=bind,source=" + _safe_mount_path(target, "Target repository")
        + ",target=/workspace/source,readonly",
        "--mount",
        "type=bind,source="
        + _safe_mount_path(normalized_profile, "Normalized profile")
        + ",target=/workspace/profile.normalized.json,readonly",
        "--mount",
        "type=bind,source=" + _safe_mount_path(work_root, "Sandbox work root")
        + ",target=/workspace/work",
        "--mount",
        "type=bind,source=" + _safe_mount_path(artifacts, "Sandbox artifacts")
        + ",target=/artifacts",
        "--env",
        f"EVAVO_TARGET_REPOSITORY={target_name}",
        "--env",
        f"EVAVO_TARGET_SHA={target_sha}",
        "--env",
        f"EVAVO_LAB_SHA={lab_sha}",
        "--env",
        "EVAVO_PROFILE_PATH=/workspace/profile.normalized.json",
        "--env",
        f"EVAVO_PROJECT_SUBPATH={profile.project_subpath}",
        "--env",
        f"EVAVO_MINIMUM_GODOT_VERSION={profile.minimum_godot_version}",
        "--env",
        f"EVAVO_TIMEOUT_SECONDS={timeout_seconds}",
        "--env",
        f"EVAVO_BOOT_FRAMES={boot_frames}",
        "--env",
        f"EVAVO_VISUAL_SCENE={profile.visual_scene}",
        "--env",
        f"EVAVO_VISUAL_FRAMES={profile.visual_frames}",
        "--env",
        f"EVAVO_VISUAL_FPS={profile.visual_fps}",
        "--env",
        f"EVAVO_VISUAL_WIDTH={profile.visual_width}",
        "--env",
        f"EVAVO_VISUAL_HEIGHT={profile.visual_height}",
        "--env",
        f"EVAVO_RENDERING_METHOD={profile.rendering_method}",
        "--env",
        f"EVAVO_VISUAL_ARGUMENTS_JSON={profile.visual_arguments_json}",
        "--env",
        f"EVAVO_EXPORT_PRESET={profile.export_preset}",
        image,
    ]


def _artifact_usage(root: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for current, directories, names in os.walk(root, topdown=True, followlinks=False):
        directories[:] = [
            name for name in directories if not (Path(current) / name).is_symlink()
        ]
        for name in names:
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                raise SandboxError(f"Sandbox evidence contains an unsafe entry: {path}")
            files += 1
            total += path.stat().st_size
            if files > _MAX_ARTIFACT_FILES or total > _MAX_ARTIFACT_BYTES:
                raise SandboxError("Sandbox evidence exceeded the retained artifact limit")
    return files, total


def run_local_sandbox(
    *,
    lab_root: Path,
    target_root: Path,
    profile_path: Path,
    artifacts_root: Path,
    expected_lab_sha: str | None = None,
    expected_target_sha: str | None = None,
    expected_project_subpath: str | None = None,
    allowed_target_roots: Sequence[Path] | None = None,
    allowed_artifact_root: Path | None = None,
    docker: str = "docker",
    timeout_seconds: int = 2700,
    boot_frames: int = 30,
    cpus: float = 4.0,
    memory: str = "10g",
    memory_swap: str = "10g",
    pids_limit: int = 1024,
    nofile_limit: int = 4096,
    shm_size: str = "1g",
    rebuild_image: bool = False,
    remove_image: bool = False,
) -> dict[str, Any]:
    if not 60 <= timeout_seconds <= 7200:
        raise SandboxError("Sandbox timeout must be between 60 and 7200 seconds")
    if not 0 <= boot_frames <= 3600:
        raise SandboxError("Sandbox boot frames must be between 0 and 3600")
    if not 0.5 <= cpus <= 64:
        raise SandboxError("Sandbox CPUs must be between 0.5 and 64")
    if not 64 <= pids_limit <= 8192:
        raise SandboxError("Sandbox PID limit must be between 64 and 8192")
    if not 1024 <= nofile_limit <= 65536:
        raise SandboxError("Sandbox nofile limit must be between 1024 and 65536")
    if _MEMORY_RE.fullmatch(memory) is None or _MEMORY_RE.fullmatch(memory_swap) is None:
        raise SandboxError("Sandbox memory values must use Docker byte syntax such as 10g")
    if _MEMORY_RE.fullmatch(shm_size) is None:
        raise SandboxError("Sandbox shared-memory size is invalid")
    lab = _resolve_lab_root(lab_root)
    target = _resolve_target(target_root, allowed_target_roots)
    if lab == target or _is_within(lab, target) or _is_within(target, lab):
        raise SandboxError("Lab and target repositories must be separate checkouts")
    lab_sha = _require_clean_exact_checkout(lab, "Lab repository", expected_lab_sha)
    target_sha = _require_clean_exact_checkout(
        target, "Target repository", expected_target_sha
    )
    profile = _resolve_profile(target, profile_path)
    artifacts = _resolve_external_artifacts(
        artifacts_root,
        lab_root=lab,
        target_root=target,
        allowed_root=allowed_artifact_root,
    )
    temporary = Path(tempfile.mkdtemp(prefix="evavo-godot-sandbox-"))
    normalized_profile: SandboxProfile | None = None
    container_name = f"evavo-godot-{uuid.uuid4().hex[:16]}"
    executable: str | None = None
    started = datetime.now(UTC)
    dispatch_path = artifacts / "local-sandbox-dispatch.json"
    result: ProcessReceipt | None = None
    image_result: dict[str, Any] | None = None
    status = "blocked"
    error: str | None = None
    try:
        executable = _docker_binary(docker)
        normalized_profile = _normalize_profile(
            lab_root=lab,
            target_root=target,
            profile_path=profile,
            work_root=temporary,
            expected_project_subpath=expected_project_subpath,
        )
        build_log = artifacts / "docker-build.log"
        image_result = build_sandbox_image(
            lab_root=lab,
            lab_sha=lab_sha,
            version=normalized_profile.engine_version,
            flavor=normalized_profile.engine_flavor,
            docker=executable,
            rebuild=rebuild_image,
            timeout_seconds=min(timeout_seconds, 3600),
            log_path=build_log,
        )
        image = str(image_result["image"])
        work_mount = temporary / "project"
        work_mount.mkdir(parents=True, exist_ok=True)
        normalized = Path(normalized_profile.normalized_path)
        if os.name != "nt":
            os.chmod(artifacts, 0o777)
            os.chmod(work_mount, 0o777)
        command = _docker_run_command(
            docker=executable,
            container_name=container_name,
            image=image,
            target=target,
            normalized_profile=normalized,
            work_root=work_mount,
            artifacts=artifacts,
            target_name=target.name,
            target_sha=target_sha,
            lab_sha=lab_sha,
            profile=normalized_profile,
            timeout_seconds=timeout_seconds,
            boot_frames=boot_frames,
            cpus=cpus,
            memory=memory,
            memory_swap=memory_swap,
            pids_limit=pids_limit,
            nofile_limit=nofile_limit,
            shm_size=shm_size,
        )
        dispatch = {
            "schemaVersion": "1.0",
            "status": "running",
            "startedAt": started.isoformat(),
            "labRoot": str(lab),
            "labSha": lab_sha,
            "targetRoot": str(target),
            "targetSha": target_sha,
            "profile": normalized_profile.to_dict(),
            "image": image_result,
            "container": container_name,
            "limits": {
                "timeoutSeconds": timeout_seconds,
                "bootFrames": boot_frames,
                "cpus": cpus,
                "memory": memory,
                "memorySwap": memory_swap,
                "pids": pids_limit,
                "nofile": nofile_limit,
                "shmSize": shm_size,
            },
        }
        dispatch_path.write_text(_canonical_json(dispatch), encoding="utf-8")
        result = _run_process(
            command,
            cwd=lab,
            timeout_seconds=timeout_seconds,
            stdout_file=artifacts / "docker-run.stdout.log",
            stderr_file=artifacts / "docker-run.stderr.log",
        )
        status = "passed" if not result.timed_out and result.exit_code == 0 else "failed"
    except (SandboxError, EngineProvisionError, FileNotFoundError, OSError, ValueError) as exc:
        error = str(exc)
        status = "blocked"
    finally:
        if executable is not None:
            try:
                _run_process(
                    [executable, "rm", "-f", container_name],
                    cwd=lab,
                    timeout_seconds=30,
                )
            except SandboxError:
                pass
        try:
            final_target_sha = _git_text(target, ["rev-parse", "HEAD"])
            final_status = _git_text(
                target, ["status", "--porcelain=v1", "--untracked-files=all"]
            )
            target_unchanged = final_target_sha == target_sha and not final_status
        except SandboxError:
            target_unchanged = False
        if not target_unchanged:
            status = "failed"
            error = error or "Sandbox execution changed or obscured the target checkout"
        try:
            files, bytes_used = _artifact_usage(artifacts)
        except SandboxError as usage_error:
            files, bytes_used = (0, 0)
            status = "failed"
            error = error or str(usage_error)
        summary = {
            "schemaVersion": "1.0",
            "status": status,
            "startedAt": started.isoformat(),
            "finishedAt": datetime.now(UTC).isoformat(),
            "labRoot": str(lab),
            "labSha": lab_sha,
            "targetRoot": str(target),
            "targetSha": target_sha,
            "targetUnchanged": target_unchanged,
            "artifacts": str(artifacts),
            "artifactFileCount": files,
            "artifactBytes": bytes_used,
            "profile": normalized_profile.to_dict() if normalized_profile else None,
            "image": image_result,
            "container": container_name,
            "process": result.to_dict() if result else None,
            "error": error,
            "truthBoundaries": [
                "The source mount was read-only and the container had no network.",
                "The Linux lane uses Xvfb and Mesa software rendering, "
                "not native Windows GPU evidence.",
                "Synthetic input does not certify physical controller behavior or human game feel.",
            ],
        }
        (artifacts / "local-sandbox-summary.json").write_text(
            _canonical_json(summary), encoding="utf-8"
        )
        if (
            executable is not None
            and remove_image
            and image_result
            and image_result.get("image")
        ):
            try:
                _run_process(
                    [executable, "image", "rm", str(image_result["image"])],
                    cwd=lab,
                    timeout_seconds=120,
                )
            except SandboxError:
                pass
        shutil.rmtree(temporary, ignore_errors=True)
    return summary


def add_sandbox_parser(subparsers: argparse._SubParsersAction) -> None:
    sandbox = subparsers.add_parser(
        "sandbox",
        help="Build or run the checksum-verified no-network Linux Godot sandbox.",
    )
    commands = sandbox.add_subparsers(dest="sandbox_command", required=True)

    status = commands.add_parser("status", help="Check Docker Linux-container readiness.")
    status.add_argument("--docker", default="docker")
    status.add_argument("--output", type=Path)

    image = commands.add_parser("image", help="Build or verify a governed Godot sandbox image.")
    image.add_argument("--lab-root", type=Path)
    image.add_argument("--version")
    image.add_argument("--flavor", choices=("standard", "mono"), default="standard")
    image.add_argument("--docker", default="docker")
    image.add_argument("--expected-lab-sha")
    image.add_argument("--rebuild", action="store_true")
    image.add_argument("--timeout", type=int, default=1800)
    image.add_argument("--log", type=Path)
    image.add_argument("--output", type=Path)

    run = commands.add_parser(
        "run",
        help="Run an external clean Git repository inside the isolated Linux sandbox.",
    )
    run.add_argument("target", type=Path)
    run.add_argument("--lab-root", type=Path)
    run.add_argument("--profile", type=Path, default=Path(".evavo/godot-lab-linux.json"))
    run.add_argument("--artifacts", type=Path, required=True)
    run.add_argument("--allowed-root", type=Path, action="append", default=[])
    run.add_argument("--allowed-artifact-root", type=Path)
    run.add_argument("--expected-lab-sha")
    run.add_argument("--expected-target-sha")
    run.add_argument("--project-subpath")
    run.add_argument("--docker", default="docker")
    run.add_argument("--timeout", type=int, default=2700)
    run.add_argument("--boot-frames", type=int, default=30)
    run.add_argument("--cpus", type=float, default=4.0)
    run.add_argument("--memory", default="10g")
    run.add_argument("--memory-swap", default="10g")
    run.add_argument("--pids-limit", type=int, default=1024)
    run.add_argument("--nofile-limit", type=int, default=4096)
    run.add_argument("--shm-size", default="1g")
    run.add_argument("--rebuild-image", action="store_true")
    run.add_argument("--remove-image", action="store_true")
    run.add_argument("--output", type=Path)


def _write_result(value: object, output: Path | None) -> None:
    text = _canonical_json(value)
    if output is not None:
        destination = output.expanduser().resolve(strict=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    print(text, end="")


def run_sandbox_command(args: argparse.Namespace) -> int:
    try:
        command = args.sandbox_command
        if command == "status":
            value = docker_status(args.docker)
        elif command == "image":
            lab = _resolve_lab_root(args.lab_root)
            sha = _require_clean_exact_checkout(
                lab, "Lab repository", args.expected_lab_sha
            )
            value = build_sandbox_image(
                lab_root=lab,
                lab_sha=sha,
                version=_governed_version(args.version),
                flavor=args.flavor,
                docker=args.docker,
                rebuild=args.rebuild,
                timeout_seconds=args.timeout,
                log_path=args.log,
            )
        elif command == "run":
            value = run_local_sandbox(
                lab_root=_resolve_lab_root(args.lab_root),
                target_root=args.target,
                profile_path=args.profile,
                artifacts_root=args.artifacts,
                expected_lab_sha=args.expected_lab_sha,
                expected_target_sha=args.expected_target_sha,
                expected_project_subpath=args.project_subpath,
                allowed_target_roots=args.allowed_root,
                allowed_artifact_root=args.allowed_artifact_root,
                docker=args.docker,
                timeout_seconds=args.timeout,
                boot_frames=args.boot_frames,
                cpus=args.cpus,
                memory=args.memory,
                memory_swap=args.memory_swap,
                pids_limit=args.pids_limit,
                nofile_limit=args.nofile_limit,
                shm_size=args.shm_size,
                rebuild_image=args.rebuild_image,
                remove_image=args.remove_image,
            )
        else:
            raise SandboxError(f"Unsupported sandbox command: {command}")
    except (SandboxError, EngineProvisionError, FileNotFoundError, OSError, ValueError) as error:
        value = {"status": "blocked", "error": str(error)}
    _write_result(value, args.output)
    return 0 if value.get("status") in {"ready", "passed"} else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="godot-lab-sandbox")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_sandbox_parser(subparsers)
    arguments = ["sandbox", *(list(argv) if argv is not None else sys.argv[1:])]
    args = parser.parse_args(arguments)
    return run_sandbox_command(args)


if __name__ == "__main__":
    raise SystemExit(main())

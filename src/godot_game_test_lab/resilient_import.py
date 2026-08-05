#!/usr/bin/env python3
"""Run exact Godot Forward+ and Compatibility import passes with bounded evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

MAX_TIMEOUT_SECONDS = 7_200
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
_VERSION_RE = re.compile(r"(?P<version>\d+\.\d+\.\d+)")
_RENDERERS = {
    "forward_plus": ("--rendering-method", "forward_plus"),
    "compatibility": (
        "--rendering-method",
        "gl_compatibility",
        "--rendering-driver",
        "opengl3",
    ),
}


class ResilientImportError(RuntimeError):
    """Raised when a governed import precondition or pass fails."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _read_bounded(path: Path, maximum: int) -> str:
    data = path.read_bytes()
    if len(data) <= maximum:
        return data.decode("utf-8", errors="replace")
    return (
        data[:maximum].decode("utf-8", errors="replace")
        + f"\n[TRUNCATED {len(data) - maximum} BYTES]\n"
    )


def _run_bounded(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    evidence_root: Path,
    identity: str,
    timeout_seconds: int,
    maximum_output_bytes: int,
) -> dict[str, Any]:
    stdout_path = evidence_root / f"{identity}.stdout.log"
    stderr_path = evidence_root / f"{identity}.stderr.log"
    started = time.monotonic()
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=os.name != "nt",
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            ),
        )
        timed_out = False
        output_exceeded = False
        while process.poll() is None:
            elapsed = time.monotonic() - started
            if elapsed > timeout_seconds:
                timed_out = True
                _terminate_process_tree(process)
                break
            output_bytes = stdout_path.stat().st_size + stderr_path.stat().st_size
            if output_bytes > maximum_output_bytes:
                output_exceeded = True
                _terminate_process_tree(process)
                break
            time.sleep(0.1)
        try:
            return_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(process)
            return_code = process.wait(timeout=5)
    duration = time.monotonic() - started
    output_bytes = stdout_path.stat().st_size + stderr_path.stat().st_size
    receipt = {
        "command": list(command),
        "cwd": str(cwd),
        "returnCode": return_code,
        "durationSeconds": round(duration, 3),
        "timedOut": timed_out,
        "outputLimitExceeded": output_exceeded,
        "outputBytes": output_bytes,
        "stdoutPath": str(stdout_path),
        "stderrPath": str(stderr_path),
        "stdoutTail": _read_bounded(stdout_path, min(maximum_output_bytes, 64_000)),
        "stderrTail": _read_bounded(stderr_path, min(maximum_output_bytes, 64_000)),
    }
    if timed_out:
        raise ResilientImportError(f"{identity} exceeded {timeout_seconds} seconds")
    if output_exceeded:
        raise ResilientImportError(
            f"{identity} exceeded {maximum_output_bytes} output bytes"
        )
    if return_code != 0:
        raise ResilientImportError(
            f"{identity} failed with exit code {return_code}; "
            f"see {stdout_path} and {stderr_path}"
        )
    return receipt


def _git(project: Path, *arguments: str, check: bool = True) -> str | None:
    executable = shutil.which("git")
    if executable is None:
        return None
    result = subprocess.run(
        [executable, "-C", str(project), *arguments],
        check=False,
        text=True,
        capture_output=True,
        timeout=30,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        if check:
            raise ResilientImportError(
                f"git {' '.join(arguments)} failed: {result.stderr.strip()}"
            )
        return None
    return result.stdout.strip()


def _source_identity(project: Path) -> dict[str, str | None]:
    root = _git(project, "rev-parse", "--show-toplevel", check=False)
    if root is None:
        return {"gitRoot": None, "head": None, "trackedStatus": None}
    git_root = Path(root).resolve(strict=True)
    head = _git(git_root, "rev-parse", "HEAD")
    tracked_status = _git(
        git_root, "status", "--porcelain=v1", "--untracked-files=no"
    )
    if tracked_status:
        raise ResilientImportError("Target checkout contains tracked changes")
    return {"gitRoot": str(git_root), "head": head, "trackedStatus": ""}


def _verify_source_unchanged(identity: dict[str, str | None]) -> None:
    root = identity.get("gitRoot")
    if root is None:
        return
    git_root = Path(root)
    if _git(git_root, "rev-parse", "HEAD") != identity.get("head"):
        raise ResilientImportError("Target HEAD changed during import")
    if _git(git_root, "status", "--porcelain=v1", "--untracked-files=no"):
        raise ResilientImportError("Godot import changed tracked target source")


def _isolated_environment(root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    paths = {
        "HOME": root / "home",
        "USERPROFILE": root / "home",
        "APPDATA": root / "appdata",
        "LOCALAPPDATA": root / "localappdata",
        "XDG_DATA_HOME": root / "xdg-data",
        "XDG_CONFIG_HOME": root / "xdg-config",
        "XDG_CACHE_HOME": root / "xdg-cache",
        "TEMP": root / "temp",
        "TMP": root / "temp",
    }
    for path in set(paths.values()):
        path.mkdir(parents=True, exist_ok=True)
    environment.update({name: str(path) for name, path in paths.items()})
    return environment


def _parse_version(output: str) -> str:
    match = _VERSION_RE.search(output)
    if match is None:
        raise ResilientImportError(f"Could not parse Godot version from: {output[:200]}")
    return match.group("version")


def run_resilient_import(
    *,
    project: Path,
    godot: Path,
    artifacts: Path,
    expected_version: str,
    renderers: Sequence[str],
    timeout_seconds: int,
    maximum_output_bytes: int,
    dotnet: Path | None = None,
    skip_dotnet: bool = False,
) -> dict[str, Any]:
    project_input = project
    godot_input = godot
    if project_input.is_symlink():
        raise ResilientImportError("Project path may not be a symlink")
    if godot_input.is_symlink():
        raise ResilientImportError("Godot path may not be a symlink")
    project = project_input.resolve(strict=True)
    godot = godot_input.resolve(strict=True)
    artifacts = artifacts.resolve()
    if not (project / "project.godot").is_file():
        raise ResilientImportError(
            "Project must be a canonical directory containing project.godot"
        )
    if not godot.is_file():
        raise ResilientImportError("Godot path must be a canonical regular file")
    if _is_within(artifacts, project):
        raise ResilientImportError("Evidence root must be outside target source")
    if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ResilientImportError("Timeout is outside the governed range")
    if not 1 <= maximum_output_bytes <= MAX_OUTPUT_BYTES:
        raise ResilientImportError("Output budget is outside the governed range")
    unsupported = sorted(set(renderers) - set(_RENDERERS))
    if unsupported or not renderers:
        raise ResilientImportError(f"Unsupported renderer selection: {unsupported}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_root = artifacts / f"resilient-import-{stamp}-{uuid.uuid4().hex[:12]}"
    run_root.mkdir(parents=True, exist_ok=False)
    environment = _isolated_environment(run_root / "environment")
    source = _source_identity(project)

    version_receipt = _run_bounded(
        [str(godot), "--version"],
        cwd=project,
        environment=environment,
        evidence_root=run_root,
        identity="godot-version",
        timeout_seconds=min(timeout_seconds, 60),
        maximum_output_bytes=maximum_output_bytes,
    )
    observed_version = _parse_version(
        f"{version_receipt['stdoutTail']}\n{version_receipt['stderrTail']}"
    )
    if expected_version and observed_version != expected_version:
        raise ResilientImportError(
            f"Godot version mismatch: expected {expected_version}, observed {observed_version}"
        )

    dotnet_receipt = None
    excluded_parts = {".godot", ".mono", "bin", "obj"}
    csprojects = sorted(
        path
        for path in project.rglob("*.csproj")
        if not excluded_parts.intersection(path.relative_to(project).parts)
    )
    if csprojects and not skip_dotnet:
        discovered_dotnet = shutil.which("dotnet")
        dotnet_path = dotnet or (Path(discovered_dotnet) if discovered_dotnet else None)
        if dotnet_path is None:
            raise ResilientImportError(
                "C# project requires an explicit or discoverable dotnet executable"
            )
        lock_files = sorted(
            path
            for path in project.rglob("packages.lock.json")
            if not excluded_parts.intersection(path.relative_to(project).parts)
        )
        dotnet_command = [
            str(dotnet_path),
            "build",
            str(csprojects[0]),
            "--nologo",
        ]
        if lock_files:
            dotnet_command.append("--locked-mode")
        dotnet_receipt = {
            "lockMode": bool(lock_files),
            "lockFiles": [str(path) for path in lock_files],
            **_run_bounded(
                dotnet_command,
                cwd=project,
                environment=environment,
                evidence_root=run_root,
                identity="dotnet-build",
                timeout_seconds=timeout_seconds,
                maximum_output_bytes=maximum_output_bytes,
            ),
        }

    passes = []
    for renderer in renderers:
        command = [
            str(godot),
            "--headless",
            "--path",
            str(project),
            *_RENDERERS[renderer],
            "--import",
        ]
        passes.append(
            {
                "renderer": renderer,
                **_run_bounded(
                    command,
                    cwd=project,
                    environment=environment,
                    evidence_root=run_root,
                    identity=f"import-{renderer}",
                    timeout_seconds=timeout_seconds,
                    maximum_output_bytes=maximum_output_bytes,
                ),
            }
        )
        _verify_source_unchanged(source)

    receipt = {
        "schemaVersion": "1.0",
        "contract": "evavo_resilient_godot_import_v1",
        "status": "passed",
        "completedAt": datetime.now(UTC).isoformat(),
        "project": str(project),
        "source": source,
        "godot": {
            "path": str(godot),
            "sha256": _sha256(godot),
            "version": observed_version,
            "versionProbe": version_receipt,
        },
        "dotnetBuild": dotnet_receipt,
        "passes": passes,
        "evidenceRoot": str(run_root),
        "credentialValuesRetained": False,
        "truthBoundary": (
            "This receipt proves the selected headless Godot import commands completed "
            "for the recorded engine and unchanged tracked source. It does not prove a "
            "visible native window, physical input, every GPU, final visual quality, "
            "performance acceptance, export or complete gameplay."
        ),
    }
    summary = run_root / "summary.json"
    summary.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def _parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--godot", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--expected-version", default="4.6.2")
    parser.add_argument(
        "--renderer",
        action="append",
        choices=sorted(_RENDERERS),
        dest="renderers",
    )
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--maximum-output-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--dotnet", type=Path)
    parser.add_argument("--skip-dotnet", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        receipt = run_resilient_import(
            project=args.project,
            godot=args.godot,
            artifacts=args.artifacts,
            expected_version=args.expected_version,
            renderers=args.renderers or ["forward_plus", "compatibility"],
            timeout_seconds=args.timeout_seconds,
            maximum_output_bytes=args.maximum_output_bytes,
            dotnet=args.dotnet,
            skip_dotnet=args.skip_dotnet,
        )
    except (OSError, ResilientImportError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

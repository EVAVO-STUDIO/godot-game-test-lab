from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .asset_audit_io import (
    AssetAuditError,
    default_evidence_root,
    default_lab_root,
    is_within,
    normalize_relative_path,
    paths_overlap,
    read_git_state,
    reject_link_components,
    resolve_directory,
    resolve_regular_file,
)


@dataclass(frozen=True)
class AssetAuditTarget:
    requested_path: str
    git_root: str
    project_root: str
    project_subpath: str
    target_sha: str


@dataclass(frozen=True)
class AssetAuditMcpConfig:
    lab_root: Path
    allowed_target_roots: tuple[Path, ...]
    evidence_root: Path

    @classmethod
    def from_environment(
        cls,
        *,
        lab_root: Path | None = None,
        allowed_target_roots: list[Path] | None = None,
        evidence_root: Path | None = None,
    ) -> AssetAuditMcpConfig:
        requested_lab = lab_root or default_lab_root()
        resolved_lab = resolve_directory(requested_lab, "Asset-audit Lab root")
        roots = allowed_target_roots or _environment_roots()
        resolved_roots: list[Path] = []
        identities: set[str] = set()
        for root in roots:
            resolved = resolve_directory(root, "Asset-audit allowed target root")
            identity = os.path.normcase(str(resolved))
            if identity not in identities:
                identities.add(identity)
                resolved_roots.append(resolved)
        if not resolved_roots:
            raise AssetAuditError("At least one allowed target root is required")
        requested_evidence = evidence_root or default_evidence_root()
        if not requested_evidence.is_absolute():
            raise AssetAuditError("Asset-audit evidence root must be absolute")
        requested_evidence = reject_link_components(
            requested_evidence,
            "Asset-audit evidence root",
        )
        if any(
            paths_overlap(requested_evidence, root)
            for root in (resolved_lab, *resolved_roots)
        ):
            raise AssetAuditError(
                "Asset-audit evidence root must remain disjoint from source roots"
            )
        requested_evidence.mkdir(parents=True, exist_ok=True)
        resolved_evidence = resolve_directory(
            requested_evidence,
            "Asset-audit evidence root",
        )
        if any(
            paths_overlap(resolved_evidence, root)
            for root in (resolved_lab, *resolved_roots)
        ):
            raise AssetAuditError(
                "Resolved asset-audit evidence root overlaps a source root"
            )
        return cls(
            lab_root=resolved_lab,
            allowed_target_roots=tuple(resolved_roots),
            evidence_root=resolved_evidence,
        )


def _environment_roots() -> list[Path]:
    configured = os.environ.get("EVAVO_GODOT_LAB_ALLOWED_ROOTS", "").strip()
    if configured:
        return [Path(value) for value in configured.split(os.pathsep) if value.strip()]
    if os.name == "nt":
        return [Path(r"C:\GitRepos")]
    return [Path.cwd()]


def _selected_project(
    requested: Path,
    git_root: Path,
    project_subpath: str | None,
) -> Path:
    if project_subpath and project_subpath.strip() != ".":
        relative = normalize_relative_path(
            project_subpath,
            label="project_subpath",
        )
        candidate = reject_link_components(
            git_root.joinpath(*PurePosixPath(relative).parts),
            "Selected project root",
        )
        project = resolve_directory(candidate, "Selected project root")
        if not is_within(project, git_root):
            raise AssetAuditError("project_subpath escapes the target Git root")
        return project

    probe = requested.parent if requested.is_file() else requested
    for candidate in (probe, *probe.parents):
        if not is_within(candidate, git_root):
            break
        project_file = candidate / "project.godot"
        if project_file.is_file() and not project_file.is_symlink():
            return resolve_directory(candidate, "Selected project root")
        if candidate == git_root:
            break

    matches: list[Path] = []
    stack = [git_root]
    directories_seen = 0
    while stack:
        directory = stack.pop()
        directories_seen += 1
        if directories_seen > 10_000:
            raise AssetAuditError(
                "Target project discovery exceeds the bounded directory limit"
            )
        for entry in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
            reject_link_components(entry, "Target discovery path")
            if not entry.is_dir():
                continue
            if entry.name.casefold() in {
                ".git",
                ".godot",
                "node_modules",
                "dist",
                "build",
            }:
                continue
            project_file = entry / "project.godot"
            if project_file.is_file() and not project_file.is_symlink():
                matches.append(entry)
                if len(matches) > 64:
                    raise AssetAuditError(
                        "Target project discovery exceeds the bounded project limit"
                    )
                if len(matches) > 1:
                    raise AssetAuditError(
                        "Target contains multiple Godot projects; project_subpath is required"
                    )
            stack.append(entry)
    if len(matches) != 1:
        raise AssetAuditError("Target does not contain one unambiguous Godot project")
    return resolve_directory(matches[0], "Selected project root")


def resolve_target(
    target: str,
    *,
    config: AssetAuditMcpConfig,
    project_subpath: str | None = None,
    expected_target_sha: str | None = None,
) -> AssetAuditTarget:
    requested_path = reject_link_components(Path(target), "Target path")
    try:
        requested = requested_path.resolve(strict=True)
    except OSError as error:
        raise AssetAuditError(f"Target path does not exist: {requested_path}") from error
    if not any(is_within(requested, root) for root in config.allowed_target_roots):
        raise AssetAuditError("Target path is outside the configured allowed roots")

    state = read_git_state(requested.parent if requested.is_file() else requested)
    if not state.available or state.git_root is None or state.target_sha is None:
        raise AssetAuditError(
            f"Target must be a Git repository: {state.error or 'Git state unavailable'}"
        )
    git_root = resolve_directory(Path(state.git_root), "Target Git root")
    if not any(is_within(git_root, root) for root in config.allowed_target_roots):
        raise AssetAuditError("Target Git root is outside the configured allowed roots")
    if paths_overlap(git_root, config.lab_root):
        raise AssetAuditError("Target Git root must remain disjoint from the Lab")
    project = _selected_project(requested, git_root, project_subpath)
    project_file = resolve_regular_file(project / "project.godot", "project.godot")
    if project_file.parent != project:
        raise AssetAuditError("Selected project.godot resolved outside its project")

    if expected_target_sha is not None:
        expected = expected_target_sha.strip().lower()
        if len(expected) != 40 or any(
            character not in "0123456789abcdef" for character in expected
        ):
            raise AssetAuditError(
                "expected_target_sha must be a lowercase 40-character digest"
            )
        if expected != state.target_sha:
            raise AssetAuditError(
                f"Target SHA mismatch: expected {expected}, observed {state.target_sha}"
            )
    relative = project.relative_to(git_root).as_posix() or "."
    return AssetAuditTarget(
        requested_path=str(requested),
        git_root=str(git_root),
        project_root=str(project),
        project_subpath=relative,
        target_sha=state.target_sha,
    )


def resolve_audit_path(
    value: str,
    *,
    target: AssetAuditTarget,
    config: AssetAuditMcpConfig,
) -> Path:
    requested = Path(value).expanduser()
    if not requested.is_absolute():
        requested = Path(target.git_root) / requested
    resolved = resolve_regular_file(requested, "Art Studio audit")
    if not (
        is_within(resolved, Path(target.git_root))
        or is_within(resolved, config.evidence_root)
    ):
        raise AssetAuditError(
            "Art Studio audit must remain inside the target Git root or evidence root"
        )
    return resolved

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .bot_qa import run_bot_qa
from .core import find_project_root, inspect_project
from .engine_manager import (
    default_engine_root,
    ensure_project_engine,
    list_installations,
)
from .integrity import audit_project
from .local_sandbox import run_local_sandbox
from .media_evidence import normalize_media_policy, scan_run_media
from .native_qa import run_native_qa
from .native_qa_common import (
    NativeQaError,
    _archive_checkout,
    _canonical_json,
    _git_text,
    _load_json_object,
    _require_clean_checkout,
)
from .pipeline import doctor_payload, validate_project_pipeline, write_report_bundle
from .profile_bootstrap import build_profile

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_MAX_RUNS = 512
_MAX_ARTIFACTS = 20_000
_MAX_JSON_BYTES = 4 * 1024 * 1024
_MAX_IMAGE_BYTES = 24 * 1024 * 1024
_MAX_AUDIO_BYTES = 32 * 1024 * 1024
_IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
_AUDIO_SUFFIXES = {".flac", ".mp3", ".ogg", ".wav"}


@dataclass(frozen=True)
class TargetRecord:
    requested_path: str
    git_root: str
    project_root: str
    project_subpath: str
    target_sha: str


@dataclass(frozen=True)
class BridgeConfig:
    lab_root: Path
    allowed_target_roots: tuple[Path, ...]
    evidence_root: Path
    engine_root: Path = field(default_factory=default_engine_root)
    require_interactive_desktop: bool = True
    auto_provision_engines: bool = True

    @classmethod
    def from_environment(
        cls,
        *,
        lab_root: Path | None = None,
        allowed_target_roots: list[Path] | None = None,
        evidence_root: Path | None = None,
        engine_root: Path | None = None,
        require_interactive_desktop: bool = True,
        auto_provision_engines: bool = True,
    ) -> BridgeConfig:
        requested_lab = _reject_symlink_components(
            lab_root or Path(__file__).resolve().parents[2], "Lab root"
        )
        resolved_lab = requested_lab.resolve(strict=True)
        roots = allowed_target_roots or _environment_roots()
        resolved_roots = tuple(
            _reject_symlink_components(root, "Allowed target root").resolve(strict=True)
            for root in roots
        )
        if not resolved_roots:
            raise NativeQaError("At least one allowed target root is required for the agent bridge")
        requested_evidence = _reject_symlink_components(
            evidence_root or _environment_evidence_root(), "Agent evidence root"
        )
        requested_evidence.mkdir(parents=True, exist_ok=True)
        resolved_evidence = requested_evidence.resolve(strict=True)
        if not resolved_evidence.is_dir():
            raise NativeQaError("Agent evidence root must be a regular directory")
        requested_engine = _reject_symlink_components(
            engine_root or default_engine_root(), "Managed engine root"
        )
        requested_engine.mkdir(parents=True, exist_ok=True)
        resolved_engine = requested_engine.resolve(strict=True)
        if not resolved_engine.is_dir():
            raise NativeQaError("Managed engine root must be a regular directory")
        if _is_within(resolved_engine, resolved_lab):
            raise NativeQaError("Managed engine root must remain outside the Lab checkout")
        if any(_is_within(resolved_engine, root) for root in resolved_roots):
            raise NativeQaError("Managed engine root must remain outside target roots")
        return cls(
            lab_root=resolved_lab,
            allowed_target_roots=resolved_roots,
            evidence_root=resolved_evidence,
            engine_root=resolved_engine,
            require_interactive_desktop=require_interactive_desktop,
            auto_provision_engines=auto_provision_engines,
        )


def _environment_roots() -> list[Path]:
    configured = os.environ.get("EVAVO_GODOT_LAB_ALLOWED_ROOTS", "").strip()
    if configured:
        return [Path(value) for value in configured.split(os.pathsep) if value.strip()]
    if os.name == "nt":
        return [Path(r"C:\GitRepos")]
    return [Path.cwd()]


def _environment_evidence_root() -> Path:
    configured = os.environ.get("EVAVO_GODOT_LAB_EVIDENCE_ROOT", "").strip()
    if configured:
        return Path(configured)
    if os.name == "nt":
        return Path(r"C:\GodotLabEvidence")
    return Path.home() / ".local" / "share" / "EVAVO" / "GodotLabEvidence"


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
                raise NativeQaError(
                    f"{label} may not traverse a symbolic link: {component}"
                )
        except OSError as error:
            raise NativeQaError(f"Could not inspect {label}: {component}") from error
    return absolute


def _safe_relative(value: str, label: str) -> Path:
    text = value.strip().replace("\\", "/")
    pure = PurePosixPath(text)
    if (
        not text
        or pure.is_absolute()
        or ":" in text
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise NativeQaError(f"{label} must be a traversal-free relative path")
    if len(text.encode("utf-8")) > 512:
        raise NativeQaError(f"{label} is too long")
    return Path(*pure.parts)


def _stable_version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
    if match is None:
        raise NativeQaError("Godot version must use stable major.minor.patch syntax")
    values = match.groups()
    return (int(values[0]), int(values[1]), int(values[2]))


def _slug(value: str) -> str:
    lowered = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return (lowered or "godot")[:48]


def _engine_selection_payload(value: object) -> dict[str, Any]:
    try:
        return asdict(value)
    except TypeError:
        fields = ("version", "flavor", "project_branch", "csharp", "reason")
        return {name: getattr(value, name) for name in fields if hasattr(value, name)}


class GodotAgentBridge:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config

    def capabilities(self) -> dict[str, Any]:
        return {
            "schemaVersion": "1.0",
            "bridge": "evavo-godot-lab-agent",
            "labRoot": str(self.config.lab_root),
            "allowedTargetRoots": [str(path) for path in self.config.allowed_target_roots],
            "evidenceRoot": str(self.config.evidence_root),
            "engineRoot": str(self.config.engine_root),
            "requireInteractiveDesktop": self.config.require_interactive_desktop,
            "autoProvisionEngines": self.config.auto_provision_engines,
            "tools": [
                "doctor",
                "ensure-engine",
                "inspect",
                "audit",
                "validate",
                "propose-bot-profile",
                "native-authored-qa",
                "deterministic-bot-qa",
                "isolated-linux-sandbox",
                "media-qa",
                "review-run",
                "list-artifacts",
                "view-image",
                "hear-audio",
            ],
            "truthBoundaries": [
                "The bridge can execute only beneath configured target roots.",
                "Retained evidence is written only beneath the configured evidence root.",
                "Managed editors are official stable archives verified against SHA512-SUMS.txt.",
                "Exact native and bot runs require clean Lab and target checkouts.",
                "Synthetic input does not certify physical controllers.",
                "Audio metrics and previews do not replace human mix or music judgment.",
                "Native visual evidence requires Greg's logged-in Windows session.",
                "Linux sandbox evidence uses no-network software rendering "
                "and is not native GPU proof.",
            ],
        }

    def doctor(self, godot: str | None = None, dotnet: str | None = None) -> dict[str, Any]:
        payload = doctor_payload(
            godot_executable=Path(godot) if godot else None,
            dotnet_executable=Path(dotnet) if dotnet else None,
        )
        payload["managedEngineRoot"] = str(self.config.engine_root)
        payload["managedEngines"] = list_installations(self.config.engine_root)
        payload["autoProvisionEngines"] = self.config.auto_provision_engines
        return payload

    def ensure_engine(
        self,
        target: str,
        *,
        project_subpath: str | None = None,
        version: str | None = None,
        flavor: str = "auto",
        install_templates: bool = True,
        offline: bool = False,
    ) -> dict[str, Any]:
        record = self.target_record(target, project_subpath=project_subpath)
        selection, installation = ensure_project_engine(
            Path(record.project_root),
            version=version,
            flavor=flavor,
            root=self.config.engine_root,
            install_templates=install_templates,
            offline=offline,
        )
        return {
            "status": "ready",
            "target": asdict(record),
            "selection": _engine_selection_payload(selection),
            "installation": installation.to_dict(),
        }

    def _resolved_godot(
        self,
        record: TargetRecord,
        godot: str | None,
        minimum_godot_version: str,
    ) -> tuple[Path | None, dict[str, Any] | None]:
        if godot:
            requested = _reject_symlink_components(Path(godot), "Godot executable")
            executable = requested.resolve(strict=True)
            if not executable.is_file():
                raise NativeQaError("Godot executable must be a regular file")
            return executable, None
        if not self.config.auto_provision_engines:
            return None, None
        selection, installation = ensure_project_engine(
            Path(record.project_root),
            root=self.config.engine_root,
            install_templates=True,
        )
        actual = _stable_version(installation.version)
        minimum = _stable_version(minimum_godot_version)
        if actual < minimum:
            selection, installation = ensure_project_engine(
                Path(record.project_root),
                version=minimum_godot_version,
                root=self.config.engine_root,
                install_templates=True,
            )
        return Path(installation.executable), {
            "selection": _engine_selection_payload(selection),
            "installation": installation.to_dict(),
        }

    def target_record(
        self,
        target: str,
        *,
        project_subpath: str | None = None,
        require_clean: bool = False,
    ) -> TargetRecord:
        requested_path = _reject_symlink_components(Path(target), "Target path")
        requested = requested_path.resolve(strict=True)
        if not any(_is_within(requested, root) for root in self.config.allowed_target_roots):
            raise NativeQaError("Target path is outside the configured allowed roots")
        git_probe = requested.parent if requested.is_file() else requested
        git_root_path = Path(_git_text(git_probe, ["rev-parse", "--show-toplevel"]))
        git_root = _reject_symlink_components(
            git_root_path, "Target Git root"
        ).resolve(strict=True)
        if not any(_is_within(git_root, root) for root in self.config.allowed_target_roots):
            raise NativeQaError("Target Git root is outside the configured allowed roots")
        if project_subpath and project_subpath.strip() != ".":
            relative = _safe_relative(project_subpath, "project_subpath")
            project_candidate = _reject_symlink_components(
                git_root / relative, "Selected project root"
            )
            project_root = project_candidate.resolve(strict=True)
            if not _is_within(project_root, git_root):
                raise NativeQaError("project_subpath escapes the target Git root")
        else:
            discovered = find_project_root(requested)
            project_root = _reject_symlink_components(
                discovered, "Selected project root"
            ).resolve(strict=True)
        project_file = project_root / "project.godot"
        if project_file.is_symlink() or not project_file.is_file():
            raise NativeQaError("Selected project does not contain a regular project.godot")
        relative_project = project_root.relative_to(git_root)
        target_sha = _git_text(git_root, ["rev-parse", "HEAD"])
        if require_clean:
            _require_clean_checkout(self.config.lab_root, "test lab")
            _require_clean_checkout(git_root, "target repository")
        return TargetRecord(
            requested_path=str(requested),
            git_root=str(git_root),
            project_root=str(project_root),
            project_subpath=relative_project.as_posix() if relative_project.parts else ".",
            target_sha=target_sha,
        )

    def inspect(self, target: str, project_subpath: str | None = None) -> dict[str, Any]:
        record = self.target_record(target, project_subpath=project_subpath)
        payload = asdict(inspect_project(Path(record.project_root)))
        payload["target"] = asdict(record)
        return payload

    def audit(self, target: str, project_subpath: str | None = None) -> dict[str, Any]:
        record = self.target_record(target, project_subpath=project_subpath)
        payload = audit_project(Path(record.project_root)).to_dict()
        payload["target"] = asdict(record)
        return payload

    def validate(
        self,
        target: str,
        *,
        project_subpath: str | None = None,
        godot: str | None = None,
        dotnet: str | None = None,
        minimum_godot_version: str = "4.6.2",
        timeout_seconds: int = 300,
        boot_frames: int = 30,
    ) -> dict[str, Any]:
        record = self.target_record(
            target,
            project_subpath=project_subpath,
            require_clean=True,
        )
        resolved_godot, managed_engine = self._resolved_godot(
            record, godot, minimum_godot_version
        )
        run_id, run_root = self._new_run("validate", Path(record.git_root).name)
        work_container = run_root / "work"
        work_root = work_container / "repository"
        try:
            archive_receipt = _archive_checkout(
                Path(record.git_root),
                record.target_sha,
                work_root,
                max(30, timeout_seconds),
            )
            project_relative = (
                Path(".")
                if record.project_subpath == "."
                else Path(*PurePosixPath(record.project_subpath).parts)
            )
            archived_project = (work_root / project_relative).resolve(strict=True)
            if not _is_within(archived_project, work_root):
                raise NativeQaError("Archived project path escapes the exact-SHA source copy")
            project_file = archived_project / "project.godot"
            if project_file.is_symlink() or not project_file.is_file():
                raise NativeQaError("Archived project does not contain a regular project.godot")
            (run_root / "source-archive.json").write_text(
                _canonical_json(archive_receipt), encoding="utf-8"
            )
            report = validate_project_pipeline(
                archived_project,
                godot_executable=resolved_godot,
                dotnet_executable=Path(dotnet) if dotnet else None,
                minimum_godot_version=minimum_godot_version,
                timeout_seconds=timeout_seconds,
                boot_frames=boot_frames,
                log_directory=run_root / "engine-logs",
            )
            write_report_bundle(report, run_root)
            payload = json.loads(report.to_json())
            payload.update(
                {
                    "runId": run_id,
                    "runRoot": str(run_root),
                    "labSha": self._lab_sha(),
                    "target": asdict(record),
                    "sourceArchive": archive_receipt,
                    "executedProject": record.project_subpath,
                    "targetCheckoutExecuted": False,
                    "managedEngine": managed_engine,
                }
            )
            (run_root / "agent-validation-summary.json").write_text(
                _canonical_json(payload), encoding="utf-8"
            )
            return payload
        finally:
            shutil.rmtree(work_container, ignore_errors=True)

    def propose_bot_profile(
        self,
        target: str,
        *,
        project_subpath: str | None = None,
    ) -> dict[str, Any]:
        record = self.target_record(
            target,
            project_subpath=project_subpath,
            require_clean=True,
        )
        profile, discovery = build_profile(Path(record.project_root))
        run_id, run_root = self._new_run("profile-proposal", Path(record.git_root).name)
        profile_path = run_root / "godot-lab-bot.proposal.json"
        discovery_path = run_root / "godot-lab-bot.discovery.json"
        profile_path.write_text(_canonical_json(profile), encoding="utf-8")
        discovery_path.write_text(_canonical_json(discovery), encoding="utf-8")
        return {
            "status": "proposed",
            "runId": run_id,
            "runRoot": str(run_root),
            "target": asdict(record),
            "profile": str(profile_path),
            "discovery": str(discovery_path),
            "profileContent": profile,
            "truthBoundary": (
                "The proposal is retained outside the target repository. Another governed "
                "target-repository change must review and commit it before exact bot QA."
            ),
        }

    def run_bot_qa(
        self,
        target: str,
        profile: str,
        *,
        project_subpath: str | None = None,
        godot: str | None = None,
        dotnet: str | None = None,
        minimum_godot_version: str = "4.6.2",
        timeout_seconds: int = 900,
        boot_frames: int = 30,
        maximum_total_seconds: int = 3600,
        maximum_artifact_bytes: int = 20 * 1024**3,
        window_position: str = "32,32",
        media_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        governed_media_policy = normalize_media_policy(media_policy)
        record = self.target_record(
            target,
            project_subpath=project_subpath,
            require_clean=True,
        )
        resolved_godot, managed_engine = self._resolved_godot(
            record, godot, minimum_godot_version
        )
        run_id, run_root = self._new_run("bot", Path(record.git_root).name)
        args = argparse.Namespace(
            lab_root=self.config.lab_root,
            target_repository=Path(record.git_root),
            project_subpath=record.project_subpath,
            profile=Path(profile),
            expected_lab_sha=self._lab_sha(),
            expected_target_sha=record.target_sha,
            artifacts=run_root,
            allowed_artifact_root=self.config.evidence_root,
            godot=resolved_godot,
            dotnet=Path(dotnet) if dotnet else None,
            minimum_godot_version=minimum_godot_version,
            timeout=timeout_seconds,
            boot_frames=boot_frames,
            max_total_seconds=maximum_total_seconds,
            max_artifact_bytes=maximum_artifact_bytes,
            window_position=window_position,
            require_interactive_desktop=self.config.require_interactive_desktop,
        )
        summary = dict(run_bot_qa(args))
        summary["runId"] = run_id
        summary["runRoot"] = str(run_root)
        summary["managedEngine"] = managed_engine
        self._attach_media_review(summary, run_root, governed_media_policy)
        (run_root / "mcp-bot-summary.json").write_text(
            _canonical_json(summary), encoding="utf-8"
        )
        return summary

    def run_native_qa(
        self,
        target: str,
        profile: str,
        *,
        project_subpath: str | None = None,
        godot: str | None = None,
        dotnet: str | None = None,
        minimum_godot_version: str = "4.6.2",
        timeout_seconds: int = 900,
        boot_frames: int = 30,
        maximum_total_seconds: int = 3600,
        maximum_artifact_bytes: int = 20 * 1024**3,
        window_position: str = "32,32",
        media_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        governed_media_policy = normalize_media_policy(media_policy)
        record = self.target_record(
            target,
            project_subpath=project_subpath,
            require_clean=True,
        )
        resolved_godot, managed_engine = self._resolved_godot(
            record, godot, minimum_godot_version
        )
        run_id, run_root = self._new_run("native", Path(record.git_root).name)
        args = argparse.Namespace(
            lab_root=self.config.lab_root,
            target_repository=Path(record.git_root),
            project_subpath=record.project_subpath,
            profile=Path(profile),
            expected_lab_sha=self._lab_sha(),
            expected_target_sha=record.target_sha,
            artifacts=run_root,
            allowed_artifact_root=self.config.evidence_root,
            godot=resolved_godot,
            dotnet=Path(dotnet) if dotnet else None,
            minimum_godot_version=minimum_godot_version,
            timeout=timeout_seconds,
            boot_frames=boot_frames,
            max_total_seconds=maximum_total_seconds,
            max_artifact_bytes=maximum_artifact_bytes,
            window_position=window_position,
            require_interactive_desktop=self.config.require_interactive_desktop,
        )
        summary = dict(run_native_qa(args))
        summary["runId"] = run_id
        summary["runRoot"] = str(run_root)
        summary["managedEngine"] = managed_engine
        self._attach_media_review(summary, run_root, governed_media_policy)
        (run_root / "mcp-native-summary.json").write_text(
            _canonical_json(summary), encoding="utf-8"
        )
        return summary

    def run_linux_sandbox(
        self,
        target: str,
        profile: str,
        *,
        project_subpath: str | None = None,
        docker: str = "docker",
        timeout_seconds: int = 2700,
        cpus: float = 4.0,
        memory: str = "10g",
        memory_swap: str = "10g",
        pids_limit: int = 1024,
        nofile_limit: int = 4096,
        shm_size: str = "1g",
        rebuild_image: bool = False,
        remove_image: bool = False,
    ) -> dict[str, Any]:
        record = self.target_record(
            target,
            project_subpath=project_subpath,
            require_clean=True,
        )
        run_id, run_root = self._new_run(
            "linux-sandbox", Path(record.git_root).name
        )
        summary = run_local_sandbox(
            lab_root=self.config.lab_root,
            target_root=Path(record.git_root),
            profile_path=Path(profile),
            artifacts_root=run_root,
            expected_lab_sha=self._lab_sha(),
            expected_target_sha=record.target_sha,
            expected_project_subpath=record.project_subpath,
            allowed_target_roots=self.config.allowed_target_roots,
            allowed_artifact_root=self.config.evidence_root,
            docker=docker,
            timeout_seconds=timeout_seconds,
            cpus=cpus,
            memory=memory,
            memory_swap=memory_swap,
            pids_limit=pids_limit,
            nofile_limit=nofile_limit,
            shm_size=shm_size,
            rebuild_image=rebuild_image,
            remove_image=remove_image,
        )
        summary["runId"] = run_id
        summary["runRoot"] = str(run_root)
        (run_root / "mcp-linux-sandbox-summary.json").write_text(
            _canonical_json(summary), encoding="utf-8"
        )
        return summary

    def analyze_run_media(
        self,
        run_id: str,
        policy: dict[str, Any] | None = None,
        timeout_seconds: int = 300,
    ) -> dict[str, Any]:
        run_root = self._run_root(run_id)
        return scan_run_media(
            run_root,
            run_root / "media-review",
            policy=normalize_media_policy(policy),
            timeout_seconds=timeout_seconds,
        )

    def list_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        entries = sorted(
            self.config.evidence_root.iterdir(),
            key=lambda path: path.name.casefold(),
            reverse=True,
        )
        for path in entries[:_MAX_RUNS]:
            if path.is_symlink() or not path.is_dir() or not _RUN_ID_RE.fullmatch(path.name):
                continue
            runs.append(
                {
                    "runId": path.name,
                    "modifiedUnix": path.stat().st_mtime,
                    "summaryFiles": [
                        item.name
                        for item in sorted(path.glob("*summary*.json"))
                        if item.is_file() and not item.is_symlink()
                    ],
                }
            )
        return runs

    def review_run(self, run_id: str) -> dict[str, Any]:
        run_root = self._run_root(run_id)
        summaries: dict[str, Any] = {}
        for path in sorted(run_root.glob("*summary*.json")):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
                continue
            summaries[path.name] = _load_json_object(path, path.name)
        media_path = run_root / "media-review" / "media-agent-summary.json"
        if media_path.is_file() and not media_path.is_symlink():
            summaries["media-agent-summary.json"] = _load_json_object(
                media_path, "media summary"
            )
        return {
            "runId": run_id,
            "runRoot": str(run_root),
            "summaries": summaries,
            "artifacts": self.list_artifacts(run_id),
        }

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        run_root = self._run_root(run_id)
        records: list[dict[str, Any]] = []
        for path in sorted(run_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if len(records) >= _MAX_ARTIFACTS:
                break
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(run_root).as_posix()
            mime, _encoding = mimetypes.guess_type(path.name)
            records.append(
                {
                    "path": relative,
                    "bytes": path.stat().st_size,
                    "mimeType": mime or "application/octet-stream",
                }
            )
        return records

    def read_json_artifact(self, run_id: str, relative_path: str) -> dict[str, Any]:
        path = self._artifact_path(run_id, relative_path)
        if path.suffix.casefold() != ".json":
            raise NativeQaError("Only JSON artifacts can be read as structured text")
        if path.stat().st_size > _MAX_JSON_BYTES:
            raise NativeQaError("JSON artifact exceeds the 4 MiB bridge limit")
        return _load_json_object(path, "run artifact")

    def image_artifact(self, run_id: str, relative_path: str) -> tuple[bytes, str]:
        path = self._artifact_path(run_id, relative_path)
        suffix = path.suffix.casefold()
        if suffix not in _IMAGE_SUFFIXES:
            raise NativeQaError("Requested artifact is not a supported image")
        data = path.read_bytes()
        if not data or len(data) > _MAX_IMAGE_BYTES:
            raise NativeQaError("Image artifact is empty or exceeds the 24 MiB bridge limit")
        return data, suffix.removeprefix(".").replace("jpg", "jpeg")

    def audio_artifact(self, run_id: str, relative_path: str) -> tuple[bytes, str]:
        path = self._artifact_path(run_id, relative_path)
        suffix = path.suffix.casefold()
        if suffix not in _AUDIO_SUFFIXES:
            raise NativeQaError("Requested artifact is not a supported audio file")
        data = path.read_bytes()
        if not data or len(data) > _MAX_AUDIO_BYTES:
            raise NativeQaError("Audio artifact is empty or exceeds the 32 MiB bridge limit")
        mime = mimetypes.guess_type(path.name)[0] or "audio/wav"
        return data, mime

    def _lab_sha(self) -> str:
        return _git_text(self.config.lab_root, ["rev-parse", "HEAD"])

    def _new_run(self, kind: str, target_name: str) -> tuple[str, Path]:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{stamp}-{_slug(kind)}-{_slug(target_name)}-{uuid.uuid4().hex[:10]}"
        run_root = self.config.evidence_root / run_id
        run_root.mkdir(parents=False, exist_ok=False)
        return run_id, run_root

    def _run_root(self, run_id: str) -> Path:
        if not _RUN_ID_RE.fullmatch(run_id):
            raise NativeQaError("run_id is invalid")
        path = (self.config.evidence_root / run_id).resolve(strict=True)
        if not _is_within(path, self.config.evidence_root):
            raise NativeQaError("run_id escapes the evidence root")
        if path.is_symlink() or not path.is_dir():
            raise NativeQaError("run_id does not identify a regular run directory")
        return path

    def _artifact_path(self, run_id: str, relative_path: str) -> Path:
        run_root = self._run_root(run_id)
        relative = _safe_relative(relative_path, "artifact path")
        path = (run_root / relative).resolve(strict=True)
        if not _is_within(path, run_root) or path.is_symlink() or not path.is_file():
            raise NativeQaError("artifact path does not identify a regular file in the run")
        return path

    def _attach_media_review(
        self,
        summary: dict[str, Any],
        run_root: Path,
        policy: dict[str, Any],
    ) -> None:
        media = self._media_review(run_root, policy)
        summary["mediaReview"] = media
        gating = any(
            policy[key]
            for key in (
                "requireAudioTrack",
                "failOnSilence",
                "failOnClipping",
                "failOnAvSyncDrift",
            )
        )
        media_status = str(media.get("status", "blocked"))
        if media_status == "failed" or (gating and media_status != "passed"):
            summary["status"] = "failed"
            raw_findings = summary.get("findings")
            findings = list(raw_findings) if isinstance(raw_findings, list) else []
            message = "Synchronized media QA did not satisfy the governed audio policy"
            if message not in findings:
                findings.append(message)
            summary["findings"] = findings

    def _media_review(
        self, run_root: Path, policy: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            return scan_run_media(
                run_root,
                run_root / "media-review",
                policy=policy,
            )
        except (NativeQaError, FileNotFoundError, OSError, ValueError) as error:
            return {"status": "blocked", "error": str(error)}


__all__ = ["BridgeConfig", "GodotAgentBridge", "TargetRecord"]

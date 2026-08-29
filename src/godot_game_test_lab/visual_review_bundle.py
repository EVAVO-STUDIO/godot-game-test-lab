from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .native_qa_common import NativeQaError, _canonical_json

_BUNDLE_SCHEMA = "evavo.visual-review-bundle.v1"
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_token(value: str, label: str) -> str:
    if _TOKEN_RE.fullmatch(value) is None:
        raise NativeQaError(f"{label} must be a bounded stable token")
    return value


def _resolved_root(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise NativeQaError(f"Visual review artifact root is not a directory: {resolved}")
    return resolved


def _confined_file(root: Path, path: Path) -> Path:
    requested = path if path.is_absolute() else root / path
    if requested.is_symlink():
        raise NativeQaError(f"Visual review evidence may not be a symbolic link: {requested}")
    actual = requested.resolve(strict=True)
    if not actual.is_file() or not actual.is_relative_to(root):
        raise NativeQaError(f"Visual review evidence escapes its artifact root: {requested}")
    relative = actual.relative_to(root)
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise NativeQaError(f"Visual review evidence contains a symbolic link: {cursor}")
    return actual


def _candidate_pngs(root: Path, maximum_entries: int) -> list[Path]:
    candidates: list[Path] = []
    scanned = 0
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names[:] = sorted(
            name
            for name in directory_names
            if not (Path(directory) / name).is_symlink()
            and name not in {"work", ".git", "node_modules"}
        )
        for file_name in sorted(file_names):
            scanned += 1
            if scanned > maximum_entries:
                raise NativeQaError("Visual review evidence discovery exceeded its entry budget")
            path = Path(directory) / file_name
            if path.suffix.lower() != ".png" or path.is_symlink():
                continue
            relative = path.relative_to(root)
            if "checkpoints" in relative.parts or file_name in {"final.png", "screenshot.png"}:
                candidates.append(path)
    return sorted(candidates, key=lambda path: path.relative_to(root).as_posix())


def _frame_id(relative: Path, index: int) -> str:
    stem = re.sub(r"[^A-Za-z0-9._:-]+", "-", relative.with_suffix("").as_posix()).strip("-")
    candidate = f"frame-{index + 1:03d}-{stem}"[:128]
    if _TOKEN_RE.fullmatch(candidate):
        return candidate
    return f"frame-{index + 1:03d}-{hashlib.sha256(relative.as_posix().encode()).hexdigest()[:16]}"


def _observation_id(relative: Path, index: int) -> str:
    parts = relative.parts
    journey = "journey"
    if "journeys" in parts:
        position = parts.index("journeys")
        if position + 1 < len(parts):
            journey = re.sub(r"[^A-Za-z0-9._:-]+", "-", parts[position + 1])
    state = re.sub(r"[^A-Za-z0-9._:-]+", "-", relative.stem)
    candidate = f"godot:{journey}:{state}:{index + 1}"
    return candidate if _TOKEN_RE.fullmatch(candidate) else f"godot:observation:{index + 1}"


def _timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


def _bounded_json(path: Path, maximum_bytes: int = 8 * 1024 * 1024) -> object | None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > maximum_bytes:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _layout_digest_for(root: Path, image: Path) -> str | None:
    cursor = image.parent
    while cursor != root and cursor.is_relative_to(root):
        candidate = cursor / "ui-layout-analysis.json"
        if candidate.is_file() and not candidate.is_symlink():
            return _sha256_file(_confined_file(root, candidate))
        cursor = cursor.parent
    journey_candidate = image.parent.parent / "ui-layout-analysis.json"
    if journey_candidate.is_file() and not journey_candidate.is_symlink():
        return _sha256_file(_confined_file(root, journey_candidate))
    return None


def _collect_findings(root: Path, maximum_findings: int = 1_000) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in sorted(root.rglob("ui-layout-analysis.json")):
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            continue
        value = _bounded_json(path)
        if not isinstance(value, Mapping):
            continue
        snapshots = value.get("snapshots", [])
        if not isinstance(snapshots, Sequence) or isinstance(snapshots, (str, bytes)):
            continue
        for snapshot in snapshots:
            if not isinstance(snapshot, Mapping):
                continue
            result = snapshot.get("analysis")
            if not isinstance(result, Mapping):
                continue
            issues = result.get("issues", [])
            if not isinstance(issues, Sequence) or isinstance(issues, (str, bytes)):
                continue
            for issue in issues:
                if len(findings) >= maximum_findings:
                    return findings
                if not isinstance(issue, Mapping):
                    continue
                findings.append(
                    {
                        "id": str(issue.get("id", f"layout-{len(findings) + 1}"))[:256],
                        "frameId": str(snapshot.get("id", "final"))[:128],
                        "rule": str(issue.get("code", "godot-layout"))[:128],
                        "severity": str(issue.get("severity", "warning"))[:32],
                        "message": str(issue.get("description", "Godot layout finding"))[:1_024],
                        "elementIds": [
                            str(item)[:512]
                            for item in issue.get("paths", [])
                            if isinstance(item, str)
                        ][:16],
                        "source": "semantic",
                        "evidencePath": path.relative_to(root).as_posix(),
                    }
                )
    return findings


def _collect_actions(root: Path, maximum_actions: int = 2_000) -> list[dict[str, Any]]:
    summary = _bounded_json(root / "native-agent-summary.json")
    if not isinstance(summary, Mapping):
        return []
    actions: list[dict[str, Any]] = []
    journeys = summary.get("journeys", [])
    if not isinstance(journeys, Sequence) or isinstance(journeys, (str, bytes)):
        return []
    for journey in journeys:
        if not isinstance(journey, Mapping):
            continue
        journey_id = str(journey.get("id", "journey"))[:128]
        harness = journey.get("harness")
        if not isinstance(harness, Mapping):
            continue
        steps = harness.get("steps", [])
        if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
            continue
        for step in steps:
            if len(actions) >= maximum_actions:
                return actions
            if not isinstance(step, Mapping):
                continue
            actions.append(
                {
                    "id": f"{journey_id}:step:{len(actions) + 1}",
                    "journeyId": journey_id,
                    "kind": str(step.get("type", "unknown"))[:128],
                    "accepted": bool(step.get("accepted", False)),
                    "elapsedFrames": int(step.get("elapsedFrames", 0))
                    if isinstance(step.get("elapsedFrames"), int)
                    else None,
                }
            )
    return actions


def build_visual_review_bundle(
    artifact_root: Path,
    output_path: Path,
    campaign_id: str,
    producer_source_sha256: str,
    *,
    maximum_frames: int = 16,
    maximum_entries: int = 20_000,
    maximum_frame_bytes: int = 25 * 1024 * 1024,
) -> dict[str, Any]:
    root = _resolved_root(artifact_root)
    _safe_token(campaign_id, "campaign_id")
    if _SHA256_RE.fullmatch(producer_source_sha256) is None:
        raise NativeQaError("producer_source_sha256 must be a lowercase SHA-256 digest")
    if not 1 <= maximum_frames <= 64:
        raise NativeQaError("maximum_frames must be between 1 and 64")
    candidates = _candidate_pngs(root, maximum_entries)
    if not candidates:
        raise NativeQaError("No Godot checkpoint PNGs were found below the artifact root")
    selected = candidates[:maximum_frames]
    frames: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected):
        actual = _confined_file(root, candidate)
        size = actual.stat().st_size
        if not 8 <= size <= maximum_frame_bytes:
            raise NativeQaError(f"Godot checkpoint image size is outside policy: {actual}")
        with actual.open("rb") as source:
            if source.read(8) != _PNG_SIGNATURE:
                raise NativeQaError(f"Godot checkpoint is not a PNG image: {actual}")
        relative = actual.relative_to(root)
        frame: dict[str, Any] = {
            "id": _frame_id(relative, index),
            "observationId": _observation_id(relative, index),
            "relativePath": relative.as_posix(),
            "sha256": _sha256_file(actual),
            "bytes": size,
            "mediaType": "image/png",
            "capturedAt": _timestamp(actual),
            "state": relative.stem[:128],
        }
        geometry_digest = _layout_digest_for(root, actual)
        if geometry_digest:
            frame["geometryDigest"] = geometry_digest
        frames.append(frame)

    partial: dict[str, Any] = {
        "schema": _BUNDLE_SCHEMA,
        "campaignId": campaign_id,
        "producer": "godot-game-test-lab",
        "producerSourceSha256": producer_source_sha256,
        "createdAt": datetime.now(UTC).isoformat(),
        "frames": frames,
        "findings": _collect_findings(root),
        "actions": _collect_actions(root),
        "reviewQuestions": [
            "Are any controls, HUD elements, menus or dialogs visibly overlapping or occluded?",
            "Does the hierarchy, spacing and focus state remain clear at every captured game state?",
            "Do the rendered frames reveal clipping, scaling, texture, typography or z-order defects not visible in semantic geometry?",
            "When ordered frames or video are supplied, are animation timing, transitions and game feedback coherent?",
        ],
        "privacy": {
            "redacted": False,
            "containsUserData": True,
            "handling": "private-local",
        },
    }
    manifest = {
        **partial,
        "rootDigest": _sha256_bytes(
            json.dumps(partial, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ),
    }
    requested_output = output_path if output_path.is_absolute() else root / output_path
    if requested_output.exists() or requested_output.is_symlink():
        raise NativeQaError(f"Visual review manifest already exists: {requested_output}")
    destination = requested_output.resolve(strict=False)
    if not destination.is_relative_to(root):
        raise NativeQaError("Visual review manifest output must remain below the artifact root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(_canonical_json(manifest), encoding="utf-8")
    return {
        "manifest": manifest,
        "manifestPath": destination.relative_to(root).as_posix(),
        "manifestSha256": _sha256_file(destination),
        "candidateFrameCount": len(candidates),
        "retainedFrameCount": len(frames),
        "framesTruncated": len(candidates) > len(frames),
    }

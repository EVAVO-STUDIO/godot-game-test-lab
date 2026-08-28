from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_CONTRACT = "evavo.godot-game-test-lab.quality-profile-receipt.v1"
_ALLOWED_PLATFORMS = {"windows", "linux", "macos", "steam", "android", "ios"}
_ALLOWED_RENDERERS = {"compatibility", "mobile", "forward-plus"}


def build_quality_profile_receipt(
    *,
    game_id: str,
    target_sha: str,
    lab_sha: str,
    quality_profile_path: Path,
    profile_id: str,
    platform: str,
    renderer: str,
    engine_version: str,
    evidence_path: Path,
    executed: bool,
    passed: bool,
) -> dict[str, Any]:
    """Build a bounded native-profile receipt from immutable local evidence.

    This function does not execute Godot, mutate the game, or claim browser/device
    evidence. It binds an already executed native profile to exact bytes.
    """

    _require_id(game_id, "game_id")
    _require_id(profile_id, "profile_id")
    _require_hex(target_sha, 40, "target_sha")
    _require_hex(lab_sha, 40, "lab_sha")
    if platform not in _ALLOWED_PLATFORMS:
        raise ValueError("platform is not a native quality-profile platform")
    if renderer not in _ALLOWED_RENDERERS:
        raise ValueError("renderer is invalid")
    if platform in {"android", "ios"} and renderer == "forward-plus":
        raise ValueError("mobile native profiles must not claim Forward+")
    if not engine_version.startswith("4."):
        raise ValueError("engine_version must identify Godot 4")
    if not executed:
        raise ValueError("native profile receipt requires executed evidence")
    if not passed:
        raise ValueError("native profile receipt requires a passing result")

    profile_bytes = _read_regular(quality_profile_path, "quality profile")
    profile = _parse_json(profile_bytes, "quality profile")
    if profile.get("gameId") != game_id:
        raise ValueError("quality profile gameId mismatch")
    declared = next(
        (
            item
            for item in profile.get("profiles", [])
            if item.get("id") == profile_id
        ),
        None,
    )
    if declared is None:
        raise ValueError("profile_id is not declared by quality profile")
    if declared.get("platform") != platform:
        raise ValueError("declared platform does not match receipt platform")
    if declared.get("renderer") != renderer:
        raise ValueError("declared renderer does not match receipt renderer")

    evidence_bytes = _read_regular(evidence_path, "native evidence")
    return {
        "contract": _CONTRACT,
        "schemaVersion": "1.0.0",
        "gameId": game_id,
        "profileId": profile_id,
        "platform": platform,
        "renderer": renderer,
        "engineVersion": engine_version,
        "targetSha": target_sha,
        "labSha": lab_sha,
        "qualityProfileSha256": _sha256(profile_bytes),
        "evidenceSha256": _sha256(evidence_bytes),
        "evidenceBytes": len(evidence_bytes),
        "executed": True,
        "passed": True,
        "browserEvidence": False,
        "physicalDeviceEvidence": False,
        "sourceMutationPerformed": False,
        "publicationPerformed": False,
    }


def _read_regular(path: Path, label: str) -> bytes:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} must be a regular non-linked file")
    return resolved.read_bytes()


def _parse_json(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_id(value: str, label: str) -> None:
    invalid_character = any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in value
    )
    if not value or len(value) > 120 or invalid_character:
        raise ValueError(f"{label} must be a bounded kebab-case identifier")
    if value.startswith("-") or value.endswith("-") or "--" in value:
        raise ValueError(f"{label} must be a bounded kebab-case identifier")


def _require_hex(value: str, length: int, label: str) -> None:
    if len(value) != length or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{label} must be lowercase hexadecimal with length {length}")

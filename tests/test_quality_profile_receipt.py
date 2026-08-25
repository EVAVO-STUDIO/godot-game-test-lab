from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab.quality_profile_receipt import build_quality_profile_receipt


def _profile(path: Path, *, renderer: str = "forward-plus", platform: str = "steam") -> Path:
    value = {
        "schemaVersion": 1,
        "gameId": "sample-game",
        "webEligibility": {
            "status": "candidate",
            "reason": "fixture",
            "requiresGdscript": True,
            "requiresCompatibilityRenderer": True,
        },
        "sharedSimulation": {
            "gameplayParityRequired": True,
            "physicsParityRequired": True,
            "networkProtocolParityRequired": True,
            "saveSchemaParityRequired": True,
        },
        "profiles": [
            {
                "id": "steam-high",
                "platform": platform,
                "renderer": renderer,
                "qualityTier": "high",
                "required": True,
                "presentation": {
                    "renderScale": 1,
                    "targetFps": 60,
                    "textureTier": "high",
                    "shadowTier": "high",
                    "effectsTier": "high",
                },
            }
        ],
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_native_profile_receipt_binds_exact_profile_and_evidence(tmp_path: Path) -> None:
    profile = _profile(tmp_path / "profile.json")
    evidence = tmp_path / "native-summary.json"
    evidence.write_text('{"outcome":"passed"}', encoding="utf-8")

    receipt = build_quality_profile_receipt(
        game_id="sample-game",
        target_sha="a" * 40,
        lab_sha="b" * 40,
        quality_profile_path=profile,
        profile_id="steam-high",
        platform="steam",
        renderer="forward-plus",
        engine_version="4.6.3",
        evidence_path=evidence,
        executed=True,
        passed=True,
    )

    assert receipt["passed"] is True
    assert receipt["profileId"] == "steam-high"
    assert receipt["renderer"] == "forward-plus"
    assert receipt["browserEvidence"] is False
    assert receipt["sourceMutationPerformed"] is False
    assert len(receipt["qualityProfileSha256"]) == 64
    assert len(receipt["evidenceSha256"]) == 64


def test_receipt_rejects_profile_renderer_drift(tmp_path: Path) -> None:
    profile = _profile(tmp_path / "profile.json")
    evidence = tmp_path / "native-summary.json"
    evidence.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="declared renderer"):
        build_quality_profile_receipt(
            game_id="sample-game",
            target_sha="a" * 40,
            lab_sha="b" * 40,
            quality_profile_path=profile,
            profile_id="steam-high",
            platform="steam",
            renderer="compatibility",
            engine_version="4.6.3",
            evidence_path=evidence,
            executed=True,
            passed=True,
        )


def test_receipt_rejects_unexecuted_or_failed_evidence(tmp_path: Path) -> None:
    profile = _profile(tmp_path / "profile.json")
    evidence = tmp_path / "native-summary.json"
    evidence.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="executed evidence"):
        build_quality_profile_receipt(
            game_id="sample-game",
            target_sha="a" * 40,
            lab_sha="b" * 40,
            quality_profile_path=profile,
            profile_id="steam-high",
            platform="steam",
            renderer="forward-plus",
            engine_version="4.6.3",
            evidence_path=evidence,
            executed=False,
            passed=True,
        )

    with pytest.raises(ValueError, match="passing result"):
        build_quality_profile_receipt(
            game_id="sample-game",
            target_sha="a" * 40,
            lab_sha="b" * 40,
            quality_profile_path=profile,
            profile_id="steam-high",
            platform="steam",
            renderer="forward-plus",
            engine_version="4.6.3",
            evidence_path=evidence,
            executed=True,
            passed=False,
        )


def test_mobile_profile_cannot_claim_forward_plus(tmp_path: Path) -> None:
    profile = _profile(tmp_path / "profile.json", platform="android", renderer="forward-plus")
    evidence = tmp_path / "native-summary.json"
    evidence.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="must not claim Forward"):
        build_quality_profile_receipt(
            game_id="sample-game",
            target_sha="a" * 40,
            lab_sha="b" * 40,
            quality_profile_path=profile,
            profile_id="steam-high",
            platform="android",
            renderer="forward-plus",
            engine_version="4.6.3",
            evidence_path=evidence,
            executed=True,
            passed=True,
        )

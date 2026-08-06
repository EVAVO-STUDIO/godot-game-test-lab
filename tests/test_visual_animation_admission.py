from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from godot_game_test_lab import visual_animation_admission as admission

ALL_FALSE = {
    "providerExecution": False, "sourceOverwrite": False, "sourceDeletion": False,
    "targetRepositoryMutation": False, "creativeApproval": False,
    "historicalApproval": False, "runtimeApproval": False,
    "publication": False, "forcePush": False,
}


def write(path: Path, data: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(data).hexdigest(), "sizeBytes": len(data)}


def self_hash(value: dict, key: str) -> dict:
    value[key] = admission.sha256_json(value)
    value["runId"] = value[key][:20]
    return value


def fixture(tmp_path: Path):
    game, candidates, frames, evidence = tmp_path / "game", tmp_path / "candidates", tmp_path / "frames", tmp_path / "evidence"
    candidate = write(candidates / "hero.png", b"static-candidate")
    scales, mattes = write(evidence / "scales.png", b"scale-sheet"), write(evidence / "mattes.png", b"matte-sheet")
    static = self_hash({
        "schema": admission.STATIC_SCHEMA, "contract": "evavo.brass-creative-evaluation.v1", "status": "passed",
        "candidatePath": "hero.png", "candidateSha256": candidate["sha256"], "candidateSizeBytes": candidate["sizeBytes"],
        "runtimeScaleEvidence": scales, "matteEvidence": mattes, "blockers": [],
        "creativeApproval": False, "historicalApproval": False, "runtimeApproval": False,
        "publicationAuthority": False, "authority": ALL_FALSE,
    }, "evaluationSha256")
    static_path = evidence / "static.json"
    static_path.write_text(json.dumps(static), encoding="utf-8")
    frame_records = []
    for index in range(4):
        identity = write(frames / f"idle_{index}.png", f"frame-{index}".encode())
        frame_records.append({"index": index, "path": f"idle_{index}.png", "sha256": identity["sha256"], "sizeBytes": identity["sizeBytes"], "features": {}})
    sheet = write(evidence / "animation-sheet.png", b"animation-sheet")
    resource = game / "assets" / "hero.tres"
    resource.parent.mkdir(parents=True)
    resource.write_text('[resource]\nclip = "idle"\n' + "\n".join(f'path = "idle_{index}.png"' for index in range(4)), encoding="utf-8")
    animation = self_hash({
        "schema": admission.ANIMATION_SCHEMA, "contract": "evavo.brass-creative-evaluation.v1", "status": "passed",
        "clipId": "idle", "spriteFramesDestination": "res://assets/hero.tres", "frames": frame_records,
        "contactSheet": sheet, "blockers": [], "creativeApproval": False, "historicalApproval": False,
        "runtimeApproval": False, "publicationAuthority": False, "authority": ALL_FALSE,
    }, "evaluationSha256")
    animation_path = evidence / "animation.json"
    animation_path.write_text(json.dumps(animation), encoding="utf-8")
    game_head = "a" * 40
    engine = self_hash({
        "schema": admission.ENGINE_SCHEMA, "status": "passed", "gameHead": game_head,
        "godotVersion": "4.6.2", "renderer": "Forward+",
        "candidateSha256s": [candidate["sha256"], *[record["sha256"] for record in frame_records]],
        "spriteFramesLoaded": True, "firstFrameRendered": True, "finalEvidenceFrameRendered": True,
        "importErrors": [], "consoleErrors": [],
    }, "evidenceSha256")
    engine_path = evidence / "engine.json"
    engine_path.write_text(json.dumps(engine), encoding="utf-8")
    contract = Path(__file__).resolve().parents[1] / "config" / "visual-animation-admission.v1.json"
    return game, candidates, frames, static_path, animation_path, engine_path, game_head, contract


def test_valid_static_animation_and_engine_chain_passes(tmp_path: Path):
    report = admission.admit(*fixture(tmp_path))
    assert report["status"] == "passed"
    assert len(report["animationAdmission"]["frames"]) == 4
    assert report["engineEvidence"]["godotVersion"] == "4.6.2"


def test_changed_candidate_bytes_fail_closed(tmp_path: Path):
    args = fixture(tmp_path)
    (args[1] / "hero.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        admission.admit(*args)


def test_missing_spriteframes_reference_fails_closed(tmp_path: Path):
    args = fixture(tmp_path)
    (args[0] / "assets" / "hero.tres").write_text('[resource]\nclip = "idle"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="does not reference frame"):
        admission.admit(*args)


def test_engine_evidence_must_cover_all_frames(tmp_path: Path):
    args = list(fixture(tmp_path))
    engine_path = args[5]
    engine = json.loads(engine_path.read_text())
    engine["candidateSha256s"] = engine["candidateSha256s"][:-1]
    engine.pop("evidenceSha256")
    engine.pop("runId")
    self_hash(engine, "evidenceSha256")
    engine_path.write_text(json.dumps(engine), encoding="utf-8")
    with pytest.raises(ValueError, match="does not cover"):
        admission.admit(*args)

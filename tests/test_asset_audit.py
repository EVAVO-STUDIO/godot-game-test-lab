from __future__ import annotations

import json
from pathlib import Path

import pytest

from asset_audit_fixtures import _audit, _codes, _project, _rgba, _write_audit

from godot_game_test_lab.asset_audit import validate_asset_audit


def test_valid_exact_audit_passes(tmp_path: Path) -> None:
    root, audit_path = _project(tmp_path)
    report = validate_asset_audit(root, audit_path, require_audit_root_match=True)
    assert report["status"] == "passed"
    assert report["schemaVersion"] == "1.1"
    assert report["summary"]["observedAssets"] == 2
    assert report["sourceState"]["unchanged"] is True


def test_changed_bytes_fail_exact_identity(tmp_path: Path) -> None:
    root, audit_path = _project(tmp_path)
    (root / "assets/art/ui/icons/cargo_icon.png").write_bytes(b"changed")
    report = validate_asset_audit(root, audit_path)
    assert report["status"] == "failed"
    assert "asset-identity-mismatch" in _codes(report)


def test_unrecorded_asset_is_fail_closed_but_has_explicit_diagnostic_allowance(
    tmp_path: Path,
) -> None:
    root, audit_path = _project(tmp_path)
    extra = root / "assets/art/ui/icons/extra_icon.png"
    extra.write_bytes(_rgba(1, 1, [0]))
    blocked = validate_asset_audit(root, audit_path)
    assert blocked["status"] == "failed"
    assert "unrecorded-art-files" in _codes(blocked)
    allowed = validate_asset_audit(root, audit_path, allow_unrecorded_assets=True)
    assert allowed["status"] == "passed"
    assert allowed["summary"]["warnings"] == 1


@pytest.mark.parametrize(
    ("alpha", "expected_code"),
    [
        ([255, 255], "meaningful-alpha-not-proven"),
        ([0, 0], "fully-transparent-image"),
    ],
)
def test_alpha_required_roles_reject_opaque_and_blank_images(
    tmp_path: Path,
    alpha: list[int],
    expected_code: str,
) -> None:
    root, audit_path = _project(tmp_path, alpha=alpha)
    report = validate_asset_audit(root, audit_path)
    assert report["status"] == "failed"
    assert expected_code in _codes(report)


def test_strict_json_rejects_duplicate_properties_and_unknown_fields(
    tmp_path: Path,
) -> None:
    root, audit_path = _project(tmp_path)
    source = audit_path.read_text(encoding="utf-8")
    audit_path.write_text(
        source[:-1] + ',"schemaVersion":"1.0"}',
        encoding="utf-8",
    )
    duplicate = validate_asset_audit(root, audit_path)
    assert duplicate["status"] == "failed"
    assert "duplicate JSON property" in duplicate["findings"][0]["message"]

    _write_audit(audit_path, _audit(root))
    value = json.loads(audit_path.read_text(encoding="utf-8"))
    value["unexpectedAuthority"] = True
    _write_audit(audit_path, value)
    unknown = validate_asset_audit(root, audit_path)
    assert unknown["status"] == "failed"
    assert "invalid properties" in unknown["findings"][0]["message"]


def test_corrupt_png_crc_fails_even_when_hash_matches_audit(tmp_path: Path) -> None:
    root, audit_path = _project(tmp_path)
    target = root / "assets/art/ui/icons/cargo_icon.png"
    data = bytearray(target.read_bytes())
    data[-5] ^= 0xFF
    target.write_bytes(data)
    value = _audit(root)
    image_row = next(row for row in value["artFiles"] if row["path"].endswith(".png"))
    # Retain plausible producer evidence so the independent CRC check is decisive.
    image_row["image"]["alphaUsage"] = "meaningful"
    image_row["image"]["probeComplete"] = True
    _write_audit(audit_path, value)
    report = validate_asset_audit(root, audit_path)
    assert report["status"] == "failed"
    assert "invalid-image-payload" in _codes(report)


def test_duplicate_cleanup_candidates_are_exact(tmp_path: Path) -> None:
    root, audit_path = _project(tmp_path)
    source = root / "assets/art/ui/icons/cargo_icon.png"
    duplicate = root / "assets/art/ui/icons/cargo_icon_copy.png"
    duplicate.write_bytes(source.read_bytes())
    value = _audit(root)
    value["cleanupCandidates"] = []
    _write_audit(audit_path, value)
    report = validate_asset_audit(root, audit_path)
    assert report["status"] == "failed"
    assert "duplicate-cleanup-candidates-incomplete" in _codes(report)


def test_animation_canvas_is_independently_rechecked(tmp_path: Path) -> None:
    root = tmp_path / "game"
    root.mkdir()
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    frames = root / "assets/art/fx/weather"
    frames.mkdir(parents=True)
    (frames / "rain_1.png").write_bytes(_rgba(1, 1, [0]))
    (frames / "rain_2.png").write_bytes(_rgba(2, 1, [0, 255]))
    family = {
        "id": "assets/art/fx/weather/rain",
        "role": "weather-overlay",
        "frames": [
            {"path": "assets/art/fx/weather/rain_1.png", "frameIndex": 1},
            {"path": "assets/art/fx/weather/rain_2.png", "frameIndex": 2},
        ],
        "missingFrameIndices": [],
        "consistentDimensions": True,
        "recommendedFramesPerSecond": 10,
        "loopMode": "linear",
        "timingNotes": ["fixture"],
    }
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, _audit(root, families=[family]))
    report = validate_asset_audit(root, audit_path)
    assert report["status"] == "failed"
    assert "animation-canvas-evidence-disagrees" in _codes(report)
    assert "animation-canvas-mismatch" in _codes(report)


def test_unsupported_compressed_alpha_requires_explicit_allowance(tmp_path: Path) -> None:
    root, _ = _project(tmp_path)
    avif = root / "assets/art/ui/icons/unknown_icon.avif"
    avif.write_bytes(b"not-decoded-by-the-bounded-probe")
    audit_path = tmp_path / "avif-audit.json"
    _write_audit(audit_path, _audit(root))
    blocked = validate_asset_audit(root, audit_path)
    assert blocked["status"] == "failed"
    assert "meaningful-alpha-not-proven" in _codes(blocked)
    allowed = validate_asset_audit(root, audit_path, allow_unverified_alpha=True)
    assert allowed["status"] == "passed"
    assert allowed["summary"]["warnings"] >= 1


def test_final_identity_recheck_detects_post_admission_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import godot_game_test_lab.asset_audit_validation as module

    root, audit_path = _project(tmp_path)
    target = root / "assets/art/ui/icons/cargo_icon.png"
    original = module.read_stable_regular_file
    changed = False

    def wrapped(path: Path, **kwargs: object):
        nonlocal changed
        result = original(path, **kwargs)
        if path == target.resolve() and kwargs.get("retain_payload") and not changed:
            changed = True
            target.write_bytes(_rgba(2, 1, [255, 255]))
        return result

    monkeypatch.setattr(module, "read_stable_regular_file", wrapped)
    report = validate_asset_audit(root, audit_path)
    assert report["status"] == "failed"
    assert "asset-changed-after-admission" in _codes(report)


def test_finding_limit_does_not_hide_failure_counts(tmp_path: Path) -> None:
    root = tmp_path / "game"
    root.mkdir()
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    icons = root / "assets/art/ui/icons"
    icons.mkdir(parents=True)
    for index in range(8):
        (icons / f"opaque_icon_{index}.png").write_bytes(_rgba(1, 1, [255]))
    audit_path = tmp_path / "audit.json"
    _write_audit(audit_path, _audit(root))
    report = validate_asset_audit(root, audit_path, maximum_findings=3)
    assert report["status"] == "failed"
    assert report["findingsTruncated"] is True
    assert report["summary"]["retainedFindings"] == 3
    assert report["summary"]["omittedFindings"] > 0
    assert report["summary"]["errors"] >= 8

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from asset_audit_fixtures import _codes, _init_git, _project, _rgba

from godot_game_test_lab.asset_audit import main, validate_asset_audit
from godot_game_test_lab.asset_audit_io import AssetAuditError, write_evidence_json


def test_casefold_collision_and_symlink_inventory_fail_closed(tmp_path: Path) -> None:
    root, audit_path = _project(tmp_path)
    first = root / "assets/art/ui/icons/COLLISION.png"
    second = root / "assets/art/ui/icons/collision.png"
    first.write_bytes(_rgba(1, 1, [0]))
    if os.path.normcase(str(first)) != os.path.normcase(str(second)):
        second.write_bytes(_rgba(1, 1, [255]))
        report = validate_asset_audit(root, audit_path, allow_unrecorded_assets=True)
        assert report["status"] == "failed"
        assert "collision" in report["findings"][0]["message"].lower()
        first.unlink()
        second.unlink()
    else:
        first.unlink()

    link = root / "assets/art/ui/icons/link.png"
    try:
        link.symlink_to(root / "assets/art/ui/icons/cargo_icon.png")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")
    report = validate_asset_audit(root, audit_path, allow_unrecorded_assets=True)
    assert report["status"] == "failed"
    assert "link or reparse" in report["findings"][0]["message"]


def test_exact_git_sha_and_clean_checkout_are_enforced(tmp_path: Path) -> None:
    root, audit_path = _project(tmp_path)
    sha = _init_git(root)
    clean = validate_asset_audit(
        root,
        audit_path,
        expected_target_sha=sha,
        require_clean_target=True,
    )
    assert clean["status"] == "passed"
    (root / "project.godot").write_text("[application]\nchanged=true\n", encoding="utf-8")
    dirty = validate_asset_audit(
        root,
        audit_path,
        expected_target_sha=sha,
        require_clean_target=True,
    )
    assert dirty["status"] == "failed"
    assert "target-not-clean" in _codes(dirty)


def test_output_is_evidence_confined_create_only_and_preserves_arbitrary_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, audit_path = _project(tmp_path)
    evidence = tmp_path / "evidence"
    code = main(
        [
            str(root),
            str(audit_path),
            "--evidence-root",
            str(evidence),
            "--output",
            "asset/review.json",
        ]
    )
    assert code == 0
    first = json.loads(capsys.readouterr().out)
    output = evidence / "asset/review.json"
    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8")) == first

    before = output.read_bytes()
    blocked = main(
        [
            str(root),
            str(audit_path),
            "--evidence-root",
            str(evidence),
            "--output",
            "asset/review.json",
        ]
    )
    assert blocked == 2
    assert output.read_bytes() == before
    capsys.readouterr()

    refreshed = main(
        [
            str(root),
            str(audit_path),
            "--evidence-root",
            str(evidence),
            "--output",
            "asset/review.json",
            "--replace-output",
        ]
    )
    assert refreshed == 0
    capsys.readouterr()

    arbitrary = evidence / "asset/client.json"
    arbitrary.write_text('{"mcpServers":{},"keep":true}\n', encoding="utf-8")
    arbitrary_before = arbitrary.read_bytes()
    rejected = main(
        [
            str(root),
            str(audit_path),
            "--evidence-root",
            str(evidence),
            "--output",
            "asset/client.json",
            "--replace-output",
        ]
    )
    assert rejected == 2
    assert arbitrary.read_bytes() == arbitrary_before
    capsys.readouterr()

    escaped = main(
        [
            str(root),
            str(audit_path),
            "--evidence-root",
            str(evidence),
            "--output",
            str(tmp_path / "outside.json"),
        ]
    )
    assert escaped == 2
    assert not (tmp_path / "outside.json").exists()


def test_writer_rejects_evidence_root_inside_target(tmp_path: Path) -> None:
    root, _ = _project(tmp_path)
    with pytest.raises(AssetAuditError, match="disjoint"):
        write_evidence_json(
            {
                "schemaVersion": "1.1",
                "tool": "godot-game-test-lab",
                "check": "art-studio-asset-audit",
            },
            output=Path("report.json"),
            evidence_root=root / "evidence",
            protected_roots=(root,),
        )

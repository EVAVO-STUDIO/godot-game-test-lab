from __future__ import annotations

import json
import shutil
from pathlib import Path

from godot_game_test_lab.web_export_audit import audit_web_export

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "generated-descriptor.v2.json"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _materialize_fixture(tmp_path: Path) -> Path:
    export_root = tmp_path / "contract-fixture"
    export_root.mkdir()
    shutil.copyfile(FIXTURE, export_root / "export.json")
    for suffix in ("js", "wasm", "pck"):
        export_root.joinpath(f"contract-fixture.{suffix}").write_bytes(b"")
    return export_root


def _finding_codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def test_canonical_runtime_descriptor_fixture_passes_independent_audit(
    tmp_path: Path,
) -> None:
    source = FIXTURE.read_text(encoding="utf-8")
    descriptor = json.loads(source)

    assert json.dumps(descriptor, indent=2) + "\n" == source
    assert set(descriptor["assetIntegrity"].values()) == {EMPTY_SHA256}

    report = audit_web_export(_materialize_fixture(tmp_path))

    assert report.status == "passed"
    assert report.errors == 0
    assert report.assets_verified == 3
    assert report.profile == "threaded"
    assert report.executable == "contract-fixture"
    assert "web.threaded_isolation_unproven" not in _finding_codes(report)
    assert "web.signature_missing" in _finding_codes(report)


def test_canonical_runtime_descriptor_fixture_detects_asset_tampering(
    tmp_path: Path,
) -> None:
    export_root = _materialize_fixture(tmp_path)
    export_root.joinpath("contract-fixture.wasm").write_bytes(b"tampered")

    report = audit_web_export(export_root)

    assert report.status == "failed"
    assert "web.asset_hash_mismatch" in _finding_codes(report)
    assert "web.asset_size_mismatch" in _finding_codes(report)
    assert report.assets_verified == 2

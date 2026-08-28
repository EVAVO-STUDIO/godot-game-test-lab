from __future__ import annotations

import hashlib
import json
from pathlib import Path

from godot_game_test_lab.web_export_audit import audit_web_export


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def make_export(root: Path, *, profile: str = "single-threaded", ensure: bool = False) -> Path:
    root.mkdir()
    assets = {
        "demo.js": b"loader",
        "demo.wasm": b"wasm",
        "demo.pck": b"pack",
    }
    for name, content in assets.items():
        (root / name).write_bytes(content)
    descriptor = {
        "schemaVersion": 2,
        "id": "demo",
        "loaderUrl": "./demo.js",
        "executable": "demo",
        "mainPack": "./demo.pck",
        "webRuntimeProfile": profile,
        "renderer": "compatibility",
        "fileSizes": {f"./{name}": len(content) for name, content in assets.items()},
        "assetIntegrity": {
            f"./{name}": _sha256(content) for name, content in assets.items()
        },
        "args": [],
        "focusCanvas": True,
        "canvasResizePolicy": 2,
        "ensureCrossOriginIsolationHeaders": ensure,
    }
    (root / "export.json").write_text(
        json.dumps(descriptor, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def finding_codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def test_valid_single_threaded_export_passes_with_unsigned_warning(tmp_path: Path) -> None:
    root = make_export(tmp_path / "web")

    report = audit_web_export(root)

    assert report.status == "passed"
    assert report.assets_verified == 3
    assert report.errors == 0
    assert "web.signature_missing" in finding_codes(report)


def test_tampered_asset_fails_integrity(tmp_path: Path) -> None:
    root = make_export(tmp_path / "web")
    (root / "demo.wasm").write_bytes(b"tampered")

    report = audit_web_export(root)

    assert report.status == "failed"
    assert "web.asset_hash_mismatch" in finding_codes(report)


def test_descriptor_rejects_encoded_path_escape_without_reading_outside(tmp_path: Path) -> None:
    root = make_export(tmp_path / "web")
    outside = tmp_path / "outside.wasm"
    outside.write_bytes(b"outside")
    descriptor_path = root / "export.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["assetIntegrity"]["./%2e%2e/outside.wasm"] = _sha256(b"outside")
    descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

    report = audit_web_export(root)

    assert report.status == "failed"
    assert "web.integrity_reference" in finding_codes(report)


def test_threaded_export_requires_isolation_evidence(tmp_path: Path) -> None:
    root = make_export(tmp_path / "web", profile="threaded", ensure=False)

    report = audit_web_export(root)

    assert report.status == "failed"
    assert "web.threaded_isolation_unproven" in finding_codes(report)


def test_threaded_export_accepts_retained_cloudflare_headers(tmp_path: Path) -> None:
    root = make_export(tmp_path / "web", profile="threaded", ensure=False)
    headers = tmp_path / "_headers"
    headers.write_text(
        "/*\n  Cross-Origin-Opener-Policy: same-origin\n"
        "  Cross-Origin-Embedder-Policy: require-corp\n",
        encoding="utf-8",
    )

    report = audit_web_export(root, headers_path=headers)

    assert report.status == "passed"
    assert report.errors == 0
    assert "web.secure_context_unproven" in finding_codes(report)


def test_size_mismatch_fails_even_when_hash_matches(tmp_path: Path) -> None:
    root = make_export(tmp_path / "web")
    descriptor_path = root / "export.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["fileSizes"]["./demo.pck"] = 999
    descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

    report = audit_web_export(root)

    assert report.status == "failed"
    assert "web.asset_size_mismatch" in finding_codes(report)


def test_symlink_inside_export_is_rejected(tmp_path: Path) -> None:
    root = make_export(tmp_path / "web")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (root / "linked.txt").symlink_to(outside)

    report = audit_web_export(root)

    assert report.status == "failed"
    assert "web.symlink_rejected" in finding_codes(report)


def test_rejects_loader_and_pack_basename_drift(tmp_path: Path) -> None:
    root = make_export(tmp_path / "web")
    descriptor_path = root / "export.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["loaderUrl"] = "./renamed.js"
    descriptor["mainPack"] = "./renamed.pck"
    descriptor["assetIntegrity"]["./renamed.js"] = descriptor["assetIntegrity"]["./demo.js"]
    descriptor["assetIntegrity"]["./renamed.pck"] = descriptor["assetIntegrity"]["./demo.pck"]
    descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

    report = audit_web_export(root)

    assert report.status == "failed"
    assert "web.loader_executable_mismatch" in finding_codes(report)
    assert "web.main_pack_executable_mismatch" in finding_codes(report)


def test_missing_isolation_flag_uses_schema_default_false(tmp_path: Path) -> None:
    root = make_export(tmp_path / "web")
    descriptor_path = root / "export.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    del descriptor["ensureCrossOriginIsolationHeaders"]
    descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

    report = audit_web_export(root)

    assert report.status == "passed"
    assert "web.isolation_flag" not in finding_codes(report)


def test_rejects_unsafe_extra_file_size_reference(tmp_path: Path) -> None:
    root = make_export(tmp_path / "web")
    descriptor_path = root / "export.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["fileSizes"]["%2e%2e/outside.bin"] = 1
    descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

    report = audit_web_export(root)

    assert report.status == "failed"
    assert "web.file_size_reference" in finding_codes(report)


def test_rejects_duplicate_normalized_size_paths(tmp_path: Path) -> None:
    root = make_export(tmp_path / "web")
    descriptor_path = root / "export.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["fileSizes"]["demo.js"] = descriptor["fileSizes"]["./demo.js"]
    descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

    report = audit_web_export(root)

    assert report.status == "failed"
    assert "web.file_size_duplicate" in finding_codes(report)


def test_cli_writes_machine_readable_report(tmp_path: Path, capsys) -> None:
    from godot_game_test_lab.web_export_audit import main

    root = make_export(tmp_path / "web")
    output = tmp_path / "report.json"

    exit_code = main([str(root), "--output", str(output)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "passed"
    assert payload["policyStatus"] == "passed"
    assert json.loads(output.read_text(encoding="utf-8"))["assetsVerified"] == 3


def test_cli_can_promote_warnings_to_policy_failure(tmp_path: Path, capsys) -> None:
    from godot_game_test_lab.web_export_audit import main

    root = make_export(tmp_path / "web")

    exit_code = main([str(root), "--warnings-as-errors"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["status"] == "passed"
    assert payload["policyStatus"] == "failed"

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from godot_game_test_lab.localization_stable_id_bundle import (
    StableIdBundleAdmissionError,
    _fingerprint,
    admit_stable_id_application_bundle,
    validate_stable_id_application_bundle,
)


def _git(root: Path, *args: str, binary: bool = False) -> str | bytes:
    return subprocess.check_output(
        ["git", *args],
        cwd=root,
        text=not binary,
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_blob(value: bytes) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {len(value)}\0".encode("ascii"))
    digest.update(value)
    return digest.hexdigest()


def _with_fingerprint(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("sha256", None)
    result["sha256"] = _fingerprint(result)
    return result


def _csv_bytes(messages: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["keys", "en_AU"])
    for message in messages:
        writer.writerow([message["stableId"], message["text"]])
    return output.getvalue().encode("utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, Any], str, bytes, bytes]:
    root = tmp_path / "target"
    source_path = root / "scenes" / "menu.tscn"
    source_path.parent.mkdir(parents=True)
    before = (
        '[gd_scene format=3]\n\n'
        '[node name="Menu" type="Control"]\n\n'
        '[node name="Action" type="Button" parent="."]\n'
        'text = "SEAL CHARTER"\n'
    ).encode("utf-8")
    after = before.replace(b'SEAL CHARTER', b'menu.main.action.new-game')
    source_path.write_bytes(before)

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.test"], cwd=root, check=True
    )
    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/EVAVO-STUDIO/Fixture_Game.git",
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "--", "scenes/menu.tscn"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    head = str(_git(root, "rev-parse", "HEAD")).strip()

    messages = [
        {
            "stableId": "menu.main.action.new-game",
            "text": "SEAL CHARTER",
            "sourcePath": "scenes/menu.tscn",
            "nodePath": "Action",
            "property": "text",
            "sourceTextSha256": _sha256(b"SEAL CHARTER"),
        }
    ]
    csv_payload = _csv_bytes(messages)
    bundle = _with_fingerprint(
        {
            "version": "localization-godot-stable-id-application-bundle-v1",
            "generatedAt": "2026-08-20T03:30:00Z",
            "repository": "EVAVO-STUDIO/Fixture_Game",
            "exactHead": head,
            "planSha256": "a" * 64,
            "catalogSha256": "b" * 64,
            "decisionSha256": "c" * 64,
            "sourceLocale": "en-AU",
            "status": "bundled-not-applied",
            "files": [
                {
                    "path": "scenes/menu.tscn",
                    "operation": "replace",
                    "beforeBytes": len(before),
                    "beforeSha256": _sha256(before),
                    "beforeGitBlobSha1": _git_blob(before),
                    "afterBytes": len(after),
                    "afterSha256": _sha256(after),
                    "afterGitBlobSha1": _git_blob(after),
                    "editCount": 1,
                    "stableIds": ["menu.main.action.new-game"],
                    "afterContentBase64": base64.b64encode(after).decode("ascii"),
                }
            ],
            "sourceCatalog": {
                "path": "localization/generated/main_menu.en_AU.csv",
                "operation": "create",
                "encoding": "UTF-8",
                "bom": False,
                "sourceLocale": "en-AU",
                "godotLocale": "en_AU",
                "messageCount": 1,
                "bytes": len(csv_payload),
                "sha256": _sha256(csv_payload),
                "gitBlobSha1": _git_blob(csv_payload),
                "contentBase64": base64.b64encode(csv_payload).decode("ascii"),
                "messages": messages,
            },
            "totalRetainedBytes": len(after) + len(csv_payload),
            "requiredApplicationSequence": [
                "obtain product mutation authority",
                "apply externally staged exact bytes",
            ],
            "authority": {
                "appliesChanges": False,
                "createsFiles": False,
                "sourceMutationAuthority": False,
                "runtimeRegistrationAuthority": False,
                "commitAuthority": False,
                "pushAuthority": False,
                "releaseAuthority": False,
                "publicationAuthority": False,
            },
        }
    )
    return root, bundle, head, before, after


def _refingerprint(bundle: dict[str, Any]) -> None:
    bundle["sha256"] = _fingerprint(bundle)


def test_admits_exact_bundle_without_mutating_target(tmp_path: Path) -> None:
    root, bundle, head, before, _ = _fixture(tmp_path)
    report = admit_stable_id_application_bundle(root, bundle)
    assert report["status"] == "passed"
    assert report["version"] == "evavo_godot_stable_id_bundle_admission_report_v1"
    assert report["exactHead"] == head
    assert report["checks"]["bundleFingerprintVerified"] is True
    assert report["checks"]["targetGitStateUnchanged"] is True
    assert report["authority"]["targetRepositoryMutationAuthority"] is False
    assert report["authority"]["publicationAuthority"] is False
    assert report["sha256"] == _fingerprint(report)
    assert (root / "scenes" / "menu.tscn").read_bytes() == before
    assert not (root / "localization" / "generated" / "main_menu.en_AU.csv").exists()
    assert str(_git(root, "rev-parse", "HEAD")).strip() == head
    assert _git(root, "status", "--porcelain=v1", "--untracked-files=all") == ""


def test_rejects_tampered_bundle_fingerprint(tmp_path: Path) -> None:
    _, bundle, _, _, _ = _fixture(tmp_path)
    bundle["files"][0]["afterSha256"] = "d" * 64
    with pytest.raises(StableIdBundleAdmissionError, match="fingerprint is invalid or stale"):
        validate_stable_id_application_bundle(bundle)


def test_rejects_dirty_target(tmp_path: Path) -> None:
    root, bundle, _, _, _ = _fixture(tmp_path)
    (root / "dirty.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(StableIdBundleAdmissionError, match="must be clean"):
        admit_stable_id_application_bundle(root, bundle)


def test_rejects_target_head_mismatch(tmp_path: Path) -> None:
    root, bundle, _, _, _ = _fixture(tmp_path)
    bundle["exactHead"] = "d" * 40
    _refingerprint(bundle)
    with pytest.raises(StableIdBundleAdmissionError, match="does not match bundle exactHead"):
        admit_stable_id_application_bundle(root, bundle)


def test_rejects_target_origin_mismatch(tmp_path: Path) -> None:
    root, bundle, _, _, _ = _fixture(tmp_path)
    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/EVAVO-STUDIO/Other.git"],
        cwd=root,
        check=True,
    )
    with pytest.raises(StableIdBundleAdmissionError, match="origin does not match"):
        admit_stable_id_application_bundle(root, bundle)


def test_rejects_current_source_byte_drift(tmp_path: Path) -> None:
    root, bundle, _, before, _ = _fixture(tmp_path)
    changed = before.replace(b"SEAL CHARTER", b"START COMPANY")
    (root / "scenes" / "menu.tscn").write_bytes(changed)
    subprocess.run(["git", "add", "--", "scenes/menu.tscn"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "changed"], cwd=root, check=True)
    bundle["exactHead"] = str(_git(root, "rev-parse", "HEAD")).strip()
    _refingerprint(bundle)
    with pytest.raises(StableIdBundleAdmissionError, match="before identity"):
        admit_stable_id_application_bundle(root, bundle)


def test_rejects_tampered_after_bytes_even_with_refingerprinted_bundle(tmp_path: Path) -> None:
    root, bundle, _, _, after = _fixture(tmp_path)
    bundle["files"][0]["afterContentBase64"] = base64.b64encode(after + b"\n").decode(
        "ascii"
    )
    _refingerprint(bundle)
    with pytest.raises(StableIdBundleAdmissionError, match="after identity"):
        admit_stable_id_application_bundle(root, bundle)


def test_rejects_after_bytes_that_do_not_assign_stable_id(tmp_path: Path) -> None:
    root, bundle, _, _, after = _fixture(tmp_path)
    changed = after.replace(b"menu.main.action.new-game", b"menu.main.action.other")
    file = bundle["files"][0]
    file["afterContentBase64"] = base64.b64encode(changed).decode("ascii")
    file["afterBytes"] = len(changed)
    file["afterSha256"] = _sha256(changed)
    file["afterGitBlobSha1"] = _git_blob(changed)
    _refingerprint(bundle)
    with pytest.raises(StableIdBundleAdmissionError, match="must assign stable ID"):
        admit_stable_id_application_bundle(root, bundle)


def test_rejects_existing_source_catalog_path(tmp_path: Path) -> None:
    root, bundle, _, _, _ = _fixture(tmp_path)
    destination = root / "localization" / "generated" / "main_menu.en_AU.csv"
    destination.parent.mkdir(parents=True)
    destination.write_text("existing", encoding="utf-8")
    subprocess.run(
        ["git", "add", "--", "localization/generated/main_menu.en_AU.csv"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "commit", "-qm", "catalog exists"], cwd=root, check=True)
    bundle["exactHead"] = str(_git(root, "rev-parse", "HEAD")).strip()
    _refingerprint(bundle)
    with pytest.raises(StableIdBundleAdmissionError, match="already exists"):
        admit_stable_id_application_bundle(root, bundle)


def test_rejects_source_catalog_id_mismatch(tmp_path: Path) -> None:
    root, bundle, _, _, _ = _fixture(tmp_path)
    message = bundle["sourceCatalog"]["messages"][0]
    message["stableId"] = "menu.main.action.other"
    payload = _csv_bytes(bundle["sourceCatalog"]["messages"])
    catalog = bundle["sourceCatalog"]
    catalog["contentBase64"] = base64.b64encode(payload).decode("ascii")
    catalog["bytes"] = len(payload)
    catalog["sha256"] = _sha256(payload)
    catalog["gitBlobSha1"] = _git_blob(payload)
    _refingerprint(bundle)
    with pytest.raises(StableIdBundleAdmissionError, match="do not exactly match"):
        admit_stable_id_application_bundle(root, bundle)


def test_rejects_incorrect_total_retained_bytes(tmp_path: Path) -> None:
    root, bundle, _, _, _ = _fixture(tmp_path)
    bundle["totalRetainedBytes"] += 1
    _refingerprint(bundle)
    with pytest.raises(StableIdBundleAdmissionError, match="totalRetainedBytes"):
        admit_stable_id_application_bundle(root, bundle)


def test_rejects_unknown_contract_fields(tmp_path: Path) -> None:
    _, bundle, _, _, _ = _fixture(tmp_path)
    bundle["unexpected"] = True
    _refingerprint(bundle)
    with pytest.raises(StableIdBundleAdmissionError, match="fields changed"):
        validate_stable_id_application_bundle(bundle)


def test_rejects_bundle_authority_escalation(tmp_path: Path) -> None:
    _, bundle, _, _, _ = _fixture(tmp_path)
    bundle["authority"]["appliesChanges"] = True
    _refingerprint(bundle)
    with pytest.raises(StableIdBundleAdmissionError, match="must remain false"):
        validate_stable_id_application_bundle(bundle)


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires platform privileges on Windows")
def test_rejects_symlinked_replacement_path(tmp_path: Path) -> None:
    root, bundle, _, _, _ = _fixture(tmp_path)
    real = root / "scenes" / "menu.tscn"
    outside = tmp_path / "outside.tscn"
    outside.write_bytes(real.read_bytes())
    real.unlink()
    real.symlink_to(outside)
    subprocess.run(["git", "add", "--", "scenes/menu.tscn"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "symlink"], cwd=root, check=True)
    bundle["exactHead"] = str(_git(root, "rev-parse", "HEAD")).strip()
    _refingerprint(bundle)
    with pytest.raises(StableIdBundleAdmissionError, match="symbolic link"):
        admit_stable_id_application_bundle(root, bundle)


def test_rejects_source_message_path_that_does_not_own_the_replacement(tmp_path: Path) -> None:
    root, bundle, _, _, _ = _fixture(tmp_path)
    bundle["sourceCatalog"]["messages"][0]["sourcePath"] = "scenes/other.tscn"
    _refingerprint(bundle)
    with pytest.raises(StableIdBundleAdmissionError, match="paths do not match"):
        admit_stable_id_application_bundle(root, bundle)

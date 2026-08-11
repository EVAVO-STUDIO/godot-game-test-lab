"""Independent installed-byte and native Godot admission for exact game-asset deliveries."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from .game_asset_delivery_common import (
    AUTHORITY,
    CONTRACT_SCHEMA,
    DELIVERY_SCHEMA,
    HEAD40,
    REPORT_SCHEMA,
    STORAGE_SCHEMA,
    _all_false,
    _git_head,
    _hash,
    _installed_file,
    _object,
    _positive_int,
    _read_json,
    _target_path,
    _text,
    _verify_self_hash,
    hash_object,
    inspect_bmfont,
    inspect_godot_resource,
    inspect_png,
    sha256_bytes,
)
from .game_asset_delivery_native import _verify_native

REPORT_SCHEMA_ID = "evavo.godot-game-asset-delivery-admission.v1"
if REPORT_SCHEMA != REPORT_SCHEMA_ID:
    raise RuntimeError("game-asset delivery report schema identity differs")


def admit_game_asset_delivery(
    game_root: Path,
    game_head: str,
    delivery_path: Path,
    storage_admission_path: Path,
    contract_path: Path,
    native_evidence_path: Path | None = None,
) -> dict[str, Any]:
    root = game_root.resolve(strict=True)
    if not root.is_dir() or game_root.is_symlink():
        raise ValueError("game root must be a regular non-symlink directory")
    expected_head = _text(game_head, "gameHead", 40)
    if not HEAD40.fullmatch(expected_head) or _git_head(root) != expected_head:
        raise ValueError("game checkout head differs from expected gameHead")

    exact_delivery, delivery_bytes, delivery = _read_json(delivery_path, "delivery bundle")
    exact_storage, storage_bytes, storage = _read_json(storage_admission_path, "storage admission")
    exact_contract, contract_bytes, contract = _read_json(contract_path, "game-asset admission contract")

    if delivery.get("schema") != DELIVERY_SCHEMA:
        raise ValueError(f"delivery.schema must be {DELIVERY_SCHEMA}")
    bundle_sha = _verify_self_hash(delivery, "bundleSha256", True)
    _all_false(delivery.get("authority"), "delivery.authority")
    if delivery.get("gameHead") != expected_head:
        raise ValueError("delivery game head differs")

    if storage.get("schema") != STORAGE_SCHEMA:
        raise ValueError(f"storage.schema must be {STORAGE_SCHEMA}")
    storage_sha = _verify_self_hash(storage, "admissionSha256", True)
    _all_false(storage.get("authority"), "storage.authority")
    if storage.get("delivery", {}).get("bundleSha256") != bundle_sha:
        raise ValueError("storage admission is not bound to the exact delivery")

    if contract.get("schema") != CONTRACT_SCHEMA:
        raise ValueError(f"contract.schema must be {CONTRACT_SCHEMA}")
    _all_false(contract.get("authority"), "contract.authority")

    delivery_items = delivery.get("items")
    storage_items = storage.get("items")
    if not isinstance(delivery_items, list) or not delivery_items:
        raise ValueError("delivery.items must be non-empty")
    if not isinstance(storage_items, list) or not storage_items:
        raise ValueError("storage.items must be non-empty")
    storage_index = {item.get("assetId"): item for item in storage_items if isinstance(item, dict)}
    if len(storage_index) != len(storage_items):
        raise ValueError("storage admission contains invalid or duplicate assets")

    installed = []
    by_target: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(delivery_items):
        item = _object(raw, f"delivery.items[{index}]")
        asset_id = _text(item.get("assetId"), f"delivery.items[{index}].assetId", 160)
        target = _target_path(item.get("targetPath"), f"delivery.items[{index}].targetPath")
        sha = _hash(item.get("sha256"), f"delivery.items[{index}].sha256")
        size = _positive_int(item.get("bytes"), f"delivery.items[{index}].bytes")
        exact_file, file_bytes = _installed_file(root, target, f"installed asset {asset_id}")
        if sha256_bytes(file_bytes) != sha or len(file_bytes) != size:
            raise ValueError(f"installed asset identity differs for {asset_id}")
        stored = storage_index.get(asset_id)
        if not stored or stored.get("sha256") != sha or stored.get("bytes") != size or stored.get("targetPath") != target:
            raise ValueError(f"storage admission item differs for {asset_id}")
        extension = exact_file.suffix.casefold()
        inspection: dict[str, Any] = {"type": "binary"}
        if extension == ".png":
            inspection = {"type": "png", **inspect_png(file_bytes, f"installed asset {asset_id}")}
        elif extension == ".fnt":
            inspection = {"type": "bmfont", **inspect_bmfont(file_bytes, f"installed asset {asset_id}")}
        elif extension in {".tres", ".tscn"}:
            inspection = {"type": "godot-resource", **inspect_godot_resource(file_bytes, f"installed asset {asset_id}")}
        record = {
            "assetId": asset_id,
            "kind": item.get("kind"),
            "role": item.get("role"),
            "targetPath": target,
            "path": str(exact_file),
            "sha256": sha,
            "bytes": size,
            "documentId": stored.get("documentId"),
            "versionId": stored.get("versionId"),
            "inspection": inspection,
        }
        installed.append(record)
        by_target[target] = record

    if set(storage_index) != {item["assetId"] for item in installed}:
        raise ValueError("storage admission coverage differs from delivery items")

    for item in installed:
        if item["inspection"]["type"] == "bmfont":
            page_target = str(PurePosixPath(item["targetPath"]).parent / item["inspection"]["pageFile"])
            if page_target not in by_target or by_target[page_target]["inspection"]["type"] != "png":
                raise ValueError(f"BMFont page is not present in delivery: {page_target}")
        if item["inspection"]["type"] == "godot-resource":
            for reference in item["inspection"]["references"]:
                relative = reference.removeprefix("res://")
                _installed_file(root, _target_path(relative, "Godot resource reference"), "Godot resource reference")

    native_binding = None
    native_summary = None
    if native_evidence_path is not None:
        native_binding, native_summary = _verify_native(native_evidence_path, expected_head, contract)

    if delivery.get("status") != "approved" or storage.get("status") != "stored":
        status = "review-required"
    elif native_binding is None:
        status = "source-passed-native-pending"
    else:
        status = "passed"

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": status,
        "gameRoot": str(root),
        "gameHead": expected_head,
        "delivery": {
            "path": str(exact_delivery),
            "fileSha256": sha256_bytes(delivery_bytes),
            "bundleSha256": bundle_sha,
            "status": delivery.get("status"),
        },
        "storageAdmission": {
            "path": str(exact_storage),
            "fileSha256": sha256_bytes(storage_bytes),
            "admissionSha256": storage_sha,
            "status": storage.get("status"),
        },
        "contract": {
            "path": str(exact_contract),
            "fileSha256": sha256_bytes(contract_bytes),
            "contract": contract.get("contract"),
        },
        "nativeEvidence": native_binding,
        "nativeSummary": native_summary,
        "installedItems": sorted(installed, key=lambda item: item["assetId"]),
        "summary": {
            "itemCount": len(installed),
            "totalBytes": sum(item["bytes"] for item in installed),
            "allInstalledBytesVerified": True,
            "allStorageVersionsVerified": True,
            "sourceAdmissionPassed": True,
            "nativeEvidenceProvided": native_binding is not None,
        },
        "creativeApproval": delivery.get("creativeApproval") is True,
        "historicalApproval": delivery.get("historicalApproval") is True,
        "provenanceApproval": delivery.get("provenanceApproval") is True,
        "nativeEvidencePassed": status == "passed",
        "nativeCompositionApproval": False,
        "publicationAuthority": False,
        "authority": dict(AUTHORITY),
    }
    report["reportSha256"] = hash_object(report)
    report["runId"] = report["reportSha256"][:20]
    return report


def write_report_create_only(path_value: Path, report: dict[str, Any]) -> Path:
    destination = Path(os.path.abspath(path_value))
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"report output already exists: {destination}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="godot-lab-game-asset-delivery")
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--game-head", required=True)
    parser.add_argument("--delivery", type=Path, required=True)
    parser.add_argument("--storage-admission", type=Path, required=True)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "config" / "game-asset-delivery-admission.v1.json",
    )
    parser.add_argument("--native-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = admit_game_asset_delivery(
            args.game_root,
            args.game_head,
            args.delivery,
            args.storage_admission,
            args.contract,
            args.native_evidence,
        )
        write_report_create_only(args.output, report)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"game-asset delivery admission failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "reportSha256": report["reportSha256"],
                "runId": report["runId"],
                "output": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())

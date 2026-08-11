from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "module": ROOT / "src/godot_game_test_lab/game_asset_delivery_admission.py",
    "contract": ROOT / "config/game-asset-delivery-admission.v1.json",
    "test": ROOT / "tests/test_game_asset_delivery_admission.py",
    "docs": ROOT / "docs/GAME_ASSET_DELIVERY_ADMISSION.md",
    "workflow": ROOT / ".github/workflows/game-asset-delivery-admission.yml",
}

failures: list[str] = []
sources: dict[str, str] = {}
for name, path in FILES.items():
    if not path.is_file() or path.is_symlink() or path.stat().st_size < 1:
        failures.append(f"missing regular file: {path.relative_to(ROOT)}")
        sources[name] = ""
    else:
        sources[name] = path.read_text(encoding="utf-8")
        if "\r" in sources[name]:
            failures.append(f"CRLF found: {path.relative_to(ROOT)}")

required = {
    "module": [
        "evavo.godot-game-asset-delivery-admission.v1",
        "source-passed-native-pending",
        "nativeEvidencePassed",
        '"nativeCompositionApproval": False',
        "inspect_png",
        "inspect_bmfont",
        "inspect_godot_resource",
        "write_report_create_only",
    ],
    "test": [
        "test_approved_source_is_native_pending",
        "test_native_evidence_produces_technical_pass_without_approval",
        "test_review_required_cannot_be_promoted_by_native_evidence",
        "test_installed_byte_tamper_is_rejected",
        "test_bad_bmfont_smoothing_is_rejected",
        "test_create_only_report",
    ],
    "workflow": [
        "workflow_dispatch:",
        "permissions:",
        "contents: read",
        "persist-credentials: false",
        "check_game_asset_delivery_admission.py",
    ],
}
for name, tokens in required.items():
    for token in tokens:
        if token not in sources[name]:
            failures.append(f"{name} is missing {token}")

contract = json.loads(sources["contract"] or "{}")
if contract.get("schema") != "evavo.godot-game-asset-delivery-admission-contract.v1":
    failures.append("contract schema differs")
if not contract.get("requirements") or not all(contract["requirements"].values()):
    failures.append("contract requirements must all remain true")
if not contract.get("authority") or any(contract["authority"].values()):
    failures.append("contract authority must remain all false")

combined = "\n".join(sources.values()).casefold()
for forbidden in ["git push --force", "contents: write", "pull-requests: write", "automaticapproval\": true"]:
    if forbidden in combined:
        failures.append(f"forbidden authority present: {forbidden}")

if failures:
    for failure in failures:
        print(f"- {failure}")
    raise SystemExit(1)
print("Godot Game Test Lab game-asset delivery admission contract passed.")

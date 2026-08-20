from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_attended_multiplayer_is_discoverable_through_existing_qa_capability() -> None:
    manifest = json.loads((ROOT / "evavo.capabilities.json").read_text(encoding="utf-8"))
    capability = next(
        item
        for item in manifest["capabilities"]
        if item["id"] == "testlab.qa.multiplayer"
    )
    assert "python -m godot_game_test_lab.attended_multiplayer" in capability[
        "entrypoints"
    ]
    assert "src/godot_game_test_lab/attended_multiplayer.py" in capability[
        "entrypoints"
    ]
    assert "docs/ATTENDED_MULTIPLAYER_RECEIPT.md" in capability["entrypoints"]
    assert {"attended", "receipt", "exact-sha"}.issubset(capability["tags"])
    assert "Completed passed multiplayer run for attended receipt" in capability[
        "requires"
    ]
    assert "Same-session operator attestation for attended receipt" in capability[
        "requires"
    ]


def test_attended_multiplayer_module_is_canonical_without_phantom_console_alias() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject["project"]["scripts"]
    assert "godot-lab-attended-multiplayer" not in scripts

    text = (ROOT / "docs" / "ATTENDED_MULTIPLAYER_RECEIPT.md").read_text(
        encoding="utf-8"
    )
    canonical = "python -m godot_game_test_lab.attended_multiplayer"
    assert canonical in text
    assert "must not assume an alias that is absent" in text


def test_attended_multiplayer_public_surface_retains_truth_boundaries() -> None:
    source = (
        ROOT / "src" / "godot_game_test_lab" / "attended_multiplayer_receipt.py"
    ).read_text(encoding="utf-8")
    for marker in (
        '"deterministicReleaseVerdictAuthority": False',
        '"humanVisualApprovalClaimed": False',
        '"humanGameFeelApprovalClaimed": False',
        '"physicalControllerCertified": False',
        '"realNetworkConditionsCertified": False',
        '"releaseApprovalClaimed": False',
        '"sourceMutationAuthority": False',
        '"deploymentAuthority": False',
        '"publicationAuthority": False',
    ):
        assert marker in source

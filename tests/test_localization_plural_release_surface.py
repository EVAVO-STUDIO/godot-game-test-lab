from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_plural_localization_release_surface_is_version_aligned() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    package_init = (ROOT / "src" / "godot_game_test_lab" / "__init__.py").read_text(
        encoding="utf-8"
    )

    assert 'version = "0.9.0"' in pyproject
    assert '__version__ = "0.9.0"' in package_init
    assert (
        'godot-lab-localization-plural = '
        '"godot_game_test_lab.localization_plural_runtime_cli:main"'
    ) in pyproject


def test_plural_localization_capability_and_contract_files_are_published() -> None:
    capabilities = json.loads((ROOT / "evavo.capabilities.json").read_text(encoding="utf-8"))
    capability_ids = {item["id"] for item in capabilities["capabilities"]}

    assert "testlab.localization.plural-runtime" in capability_ids
    assert (
        ROOT / "schemas" / "localization-godot-plural-testlab-request.v1.schema.json"
    ).is_file()
    assert (
        ROOT
        / "schemas"
        / "evavo-godot-plural-localization-test-lab-report.v1.schema.json"
    ).is_file()
    assert (ROOT / "docs" / "LOCALIZATION_PLURAL_RUNTIME_VALIDATION.md").is_file()


def test_plural_localization_cli_maps_engine_provisioning_failures_to_blocked_contract() -> None:
    text = (
        ROOT / "src" / "godot_game_test_lab" / "localization_plural_cli.py"
    ).read_text(encoding="utf-8")

    assert "from .engine_manager import EngineProvisionError, ensure_project_engine" in text
    assert "EngineProvisionError," in text
    assert '"status": "blocked"' in text
    assert '"nativeGodotImportVerified": False' in text
    assert '"runtimePluralLookupVerified": False' in text

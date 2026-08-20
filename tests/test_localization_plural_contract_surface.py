from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_plural_localization_runtime_contract_surface_is_present() -> None:
    for relative in (
        "src/godot_game_test_lab/localization_plural.py",
        "src/godot_game_test_lab/localization_plural_safe.py",
        "src/godot_game_test_lab/localization_plural_runtime.py",
        "src/godot_game_test_lab/localization_plural_runtime_cli.py",
        "schemas/localization-godot-plural-testlab-request.v1.schema.json",
        "schemas/evavo-godot-plural-localization-test-lab-report.v1.schema.json",
        "docs/LOCALIZATION_PLURAL_RUNTIME_VALIDATION.md",
    ):
        assert (ROOT / relative).is_file(), relative


def test_test_lab_package_version_is_consistently_0_9_0() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    init = (ROOT / "src" / "godot_game_test_lab" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert re.search(r'(?m)^version = "0\.9\.0"$', pyproject)
    assert '__version__ = "0.9.0"' in init


def test_plural_localization_json_schemas_parse_and_pin_contract_versions() -> None:
    request_schema = json.loads(
        (
            ROOT
            / "schemas"
            / "localization-godot-plural-testlab-request.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    report_schema = json.loads(
        (
            ROOT
            / "schemas"
            / "evavo-godot-plural-localization-test-lab-report.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert (
        request_schema["properties"]["version"]["const"]
        == "localization-godot-plural-testlab-request-v1"
    )
    assert (
        report_schema["properties"]["version"]["const"]
        == "evavo_godot_plural_localization_test_lab_report_v1"
    )
    authority = report_schema["properties"]["authority"]["properties"]
    assert authority["targetRepositoryMutationAuthority"]["const"] is False
    assert authority["repairAuthority"]["const"] is False
    assert authority["publicationAuthority"]["const"] is False


def test_documentation_names_guarded_module_as_canonical_invocation() -> None:
    text = (ROOT / "docs" / "LOCALIZATION_PLURAL_RUNTIME_VALIDATION.md").read_text(
        encoding="utf-8"
    )
    assert "python -m godot_game_test_lab.localization_plural_runtime_cli" in text
    assert "global subprocess guard" in text
    assert "publicationAuthority" in text
    assert "not be treated as the final guarded entrypoint" in text

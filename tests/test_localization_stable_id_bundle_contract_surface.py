from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stable_id_bundle_contract_surface_is_present() -> None:
    for relative in (
        "src/godot_game_test_lab/localization_stable_id_bundle.py",
        "src/godot_game_test_lab/localization_stable_id_bundle_cli.py",
        "schemas/localization-godot-stable-id-application-bundle.v1.schema.json",
        "schemas/evavo-godot-stable-id-bundle-admission-report.v1.schema.json",
        "docs/LOCALIZATION_STABLE_ID_BUNDLE_ADMISSION.md",
    ):
        assert (ROOT / relative).is_file(), relative


def test_stable_id_bundle_schemas_parse_and_pin_authority() -> None:
    bundle = json.loads(
        (
            ROOT
            / "schemas"
            / "localization-godot-stable-id-application-bundle.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    report = json.loads(
        (
            ROOT
            / "schemas"
            / "evavo-godot-stable-id-bundle-admission-report.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert (
        bundle["properties"]["version"]["const"]
        == "localization-godot-stable-id-application-bundle-v1"
    )
    assert (
        report["properties"]["version"]["const"]
        == "evavo_godot_stable_id_bundle_admission_report_v1"
    )
    for schema in (bundle, report):
        authority = schema["properties"]["authority"]["properties"]
        assert authority["publicationAuthority"]["const"] is False
    report_authority = report["properties"]["authority"]["properties"]
    for field in (
        "targetRepositoryMutationAuthority",
        "sourceMutationAuthority",
        "runtimeRegistrationAuthority",
        "commitAuthority",
        "pushAuthority",
        "releaseAuthority",
        "publicationAuthority",
    ):
        assert report_authority[field]["const"] is False


def test_package_console_alias_uses_read_only_admission_cli() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(
        r'^godot-lab-localization-stable-id-bundle = '
        r'"godot_game_test_lab\.localization_stable_id_bundle_cli:main"$',
        pyproject,
        flags=re.MULTILINE,
    )


def test_documentation_preserves_non_mutation_boundary() -> None:
    text = (
        ROOT / "docs" / "LOCALIZATION_STABLE_ID_BUNDLE_ADMISSION.md"
    ).read_text(encoding="utf-8")
    assert "godot-lab-localization-stable-id-bundle" in text
    assert "does not execute Godot" in text
    assert "targetRepositoryMutationAuthority" in text
    assert "publicationAuthority" in text
    assert "cannot infer or manufacture that decision" in text

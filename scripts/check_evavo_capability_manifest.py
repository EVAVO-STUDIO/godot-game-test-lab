#!/usr/bin/env python3
"""Validate all Test Lab capabilities, extending the retained broad checker."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

PLURAL_ID = "testlab.localization.plural-runtime"
PLURAL_EFFECTS = ["read", "compute", "write", "execute"]
PLURAL_INTERFACES = ["automation", "cli", "testing"]
PLURAL_ENTRYPOINTS = {
    "godot-lab-localization-plural",
    "python -m godot_game_test_lab.localization_plural_runtime_cli",
    "src/godot_game_test_lab/localization_plural_runtime.py",
    "src/godot_game_test_lab/localization_plural_safe.py",
    "scripts/Invoke-GodotPluralLocalizationValidation.ps1",
    "docs/LOCALIZATION_PLURAL_RUNTIME_VALIDATION.md",
}
PLURAL_REQUIRES = {
    "Fingerprint-valid localization-godot-plural-testlab-request-v1",
    "Exact clean target Git head with supported github.com origin",
    "Exact admitted project-relative CSV bytes",
    "Compatible Godot editor and .NET SDK when required",
    "External evidence root",
    "Human-reviewed locale probe mapping",
}

STABLE_ID_BUNDLE_ID = "testlab.localization.stable-id-bundle-admit"
STABLE_ID_BUNDLE_EFFECTS = ["read", "compute"]
STABLE_ID_BUNDLE_INTERFACES = ["automation", "cli", "library", "testing"]
STABLE_ID_BUNDLE_ENTRYPOINTS = {
    "godot-lab-localization-stable-id-bundle",
    "python -m godot_game_test_lab.localization_stable_id_bundle_cli",
    "src/godot_game_test_lab/localization_stable_id_bundle.py",
    "src/godot_game_test_lab/localization_stable_id_bundle_cli.py",
    "docs/LOCALIZATION_STABLE_ID_BUNDLE_ADMISSION.md",
}
STABLE_ID_BUNDLE_REQUIRES = {
    "Fingerprint-valid localization-godot-stable-id-application-bundle-v1",
    "Exact clean target Git head with supported github.com origin",
    "Exact current, proposed and source-catalog byte identities",
    "Separate product-owned authority for later application or commit",
}


def load_legacy() -> ModuleType:
    path = Path(__file__).with_name("check_evavo_capability_manifest_legacy.py")
    spec = importlib.util.spec_from_file_location("godot_lab_capability_legacy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the retained capability checker.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_expected_contract(legacy: ModuleType) -> None:
    effects = dict(legacy.EXPECTED_EFFECTS)
    effects[PLURAL_ID] = PLURAL_EFFECTS
    effects[STABLE_ID_BUNDLE_ID] = STABLE_ID_BUNDLE_EFFECTS
    legacy.EXPECTED_EFFECTS = effects
    legacy.EXPECTED_IDS = tuple(effects)

    scripts = dict(legacy.EXPECTED_SCRIPTS)
    scripts["godot-lab-localization-plural"] = (
        "godot_game_test_lab.localization_plural_runtime_cli:main"
    )
    scripts["godot-lab-localization-stable-id-bundle"] = (
        "godot_game_test_lab.localization_stable_id_bundle_cli:main"
    )
    legacy.EXPECTED_SCRIPTS = scripts


def json_object(legacy: ModuleType, relative: str) -> dict:
    try:
        value = json.loads(legacy.read(relative, 4_000_000))
    except json.JSONDecodeError as error:
        legacy.FAILURES.append(f"invalid JSON {relative}: {error}")
        return {}
    if not isinstance(value, dict):
        legacy.FAILURES.append(f"{relative} must be an object")
        return {}
    return value


def validate_plural_capability(legacy: ModuleType, by_id: dict[str, dict]) -> None:
    capability = by_id.get(PLURAL_ID, {})
    legacy.check(
        capability.get("interfaces") == PLURAL_INTERFACES,
        "plural-localization interfaces drifted",
    )
    legacy.check(
        capability.get("effects") == PLURAL_EFFECTS,
        "plural-localization effect authority drifted",
    )
    legacy.check(
        set(capability.get("entrypoints", [])) == PLURAL_ENTRYPOINTS,
        "plural-localization guarded entrypoints drifted",
    )
    legacy.check(
        set(capability.get("requires", [])) == PLURAL_REQUIRES,
        "plural-localization prerequisites drifted",
    )
    tags = set(capability.get("tags", []))
    legacy.check(
        {"exact-head", "runtime-probe", "admission", "evidence"}.issubset(tags),
        "plural-localization evidence tags are incomplete",
    )
    effects = capability.get("effects", [])
    legacy.check(
        "network" not in effects and "publish" not in effects,
        "plural-localization capability exceeds Test Lab authority",
    )

    markers = {
        "src/godot_game_test_lab/localization_plural.py": (
            "localization-godot-plural-testlab-request-v1",
            "validate_plural_testlab_request",
            '"requestWritesTarget": False',
        ),
        "src/godot_game_test_lab/localization_plural_safe.py": (
            "run_plural_localization_validation_safe",
            "Plural localization CSV bytes changed during validation.",
            '"targetRepositoryMutationAuthority": False',
            '"publicationAuthority": False',
        ),
        "src/godot_game_test_lab/localization_plural_runtime.py": (
            "run_plural_localization_runtime_validation",
            "run_plural_localization_validation_safe",
            ".godot may not be a symbolic link",
        ),
        "src/godot_game_test_lab/localization_plural_runtime_cli.py": (
            "Canonical guarded validator",
            "run_plural_localization_runtime_validation",
            '"repairAuthority": False',
            '"publicationAuthority": False',
        ),
        "scripts/Invoke-GodotPluralLocalizationValidation.ps1": (
            "godot_game_test_lab.localization_plural_runtime_cli",
            '"--request", $Request',
            '"--artifacts", $Artifacts',
        ),
        "docs/LOCALIZATION_PLURAL_RUNTIME_VALIDATION.md": (
            "python -m godot_game_test_lab.localization_plural_runtime_cli",
            "global subprocess guard",
            "publicationAuthority",
            "not be treated as the final guarded entrypoint",
        ),
    }
    for relative, required in markers.items():
        legacy.includes_all(legacy.read(relative), required, relative)

    request = json_object(
        legacy,
        "schemas/localization-godot-plural-testlab-request.v1.schema.json",
    )
    request_properties = request.get("properties", {})
    legacy.check(
        request_properties.get("version", {}).get("const")
        == "localization-godot-plural-testlab-request-v1",
        "plural-localization request schema version drifted",
    )
    request_authority = request_properties.get("authority", {}).get("properties", {})
    for field in (
        "requestExecutesGodot",
        "requestWritesTarget",
        "requestPublishesTarget",
        "nativeGodotImportVerified",
        "runtimePluralLookupVerified",
    ):
        legacy.check(
            request_authority.get(field, {}).get("const") is False,
            f"plural-localization request authority drifted: {field}",
        )
    legacy.check(
        request_authority.get("testLabExecutionRequired", {}).get("const") is True,
        "plural-localization request no longer requires Test Lab execution",
    )

    report = json_object(
        legacy,
        "schemas/evavo-godot-plural-localization-test-lab-report.v1.schema.json",
    )
    report_properties = report.get("properties", {})
    legacy.check(
        report_properties.get("version", {}).get("const")
        == "evavo_godot_plural_localization_test_lab_report_v1",
        "plural-localization report schema version drifted",
    )
    report_authority = report_properties.get("authority", {}).get("properties", {})
    for field in (
        "targetRepositoryMutationAuthority",
        "repairAuthority",
        "publicationAuthority",
    ):
        legacy.check(
            report_authority.get(field, {}).get("const") is False,
            f"plural-localization report authority drifted: {field}",
        )


def validate_stable_id_bundle_capability(
    legacy: ModuleType, by_id: dict[str, dict]
) -> None:
    capability = by_id.get(STABLE_ID_BUNDLE_ID, {})
    legacy.check(
        capability.get("interfaces") == STABLE_ID_BUNDLE_INTERFACES,
        "stable-ID bundle interfaces drifted",
    )
    legacy.check(
        capability.get("effects") == STABLE_ID_BUNDLE_EFFECTS,
        "stable-ID bundle effect authority drifted",
    )
    legacy.check(
        set(capability.get("entrypoints", [])) == STABLE_ID_BUNDLE_ENTRYPOINTS,
        "stable-ID bundle entrypoints drifted",
    )
    legacy.check(
        set(capability.get("requires", [])) == STABLE_ID_BUNDLE_REQUIRES,
        "stable-ID bundle prerequisites drifted",
    )
    tags = set(capability.get("tags", []))
    legacy.check(
        {"exact-head", "exact-bytes", "admission", "read-only"}.issubset(tags),
        "stable-ID bundle evidence tags are incomplete",
    )
    effects = capability.get("effects", [])
    legacy.check(
        effects == ["read", "compute"]
        and "write" not in effects
        and "execute" not in effects
        and "network" not in effects
        and "publish" not in effects,
        "stable-ID bundle capability exceeds read-only admission authority",
    )

    markers = {
        "src/godot_game_test_lab/localization_stable_id_bundle.py": (
            '_BUNDLE_VERSION = "localization-godot-stable-id-application-bundle-v1"',
            "admit_stable_id_application_bundle",
            "Stable-ID bundle admission changed the target Git state.",
            '"targetRepositoryMutationAuthority"',
            '"publicationAuthority"',
            "shell=False",
        ),
        "src/godot_game_test_lab/localization_stable_id_bundle_cli.py": (
            "load_strict_json_object",
            "admit_stable_id_application_bundle",
            '"targetRepositoryMutationAuthority": False',
            '"publicationAuthority": False',
        ),
        "docs/LOCALIZATION_STABLE_ID_BUNDLE_ADMISSION.md": (
            "godot-lab-localization-stable-id-bundle",
            "does not execute Godot",
            "targetRepositoryMutationAuthority",
            "publicationAuthority",
            "cannot infer or manufacture that decision",
        ),
    }
    for relative, required in markers.items():
        legacy.includes_all(legacy.read(relative, 4_000_000), required, relative)

    bundle = json_object(
        legacy,
        "schemas/localization-godot-stable-id-application-bundle.v1.schema.json",
    )
    bundle_properties = bundle.get("properties", {})
    legacy.check(
        bundle_properties.get("version", {}).get("const")
        == "localization-godot-stable-id-application-bundle-v1",
        "stable-ID bundle schema version drifted",
    )
    bundle_authority = bundle_properties.get("authority", {}).get("properties", {})
    for field in (
        "appliesChanges",
        "createsFiles",
        "sourceMutationAuthority",
        "runtimeRegistrationAuthority",
        "commitAuthority",
        "pushAuthority",
        "releaseAuthority",
        "publicationAuthority",
    ):
        legacy.check(
            bundle_authority.get(field, {}).get("const") is False,
            f"stable-ID bundle authority drifted: {field}",
        )

    report = json_object(
        legacy,
        "schemas/evavo-godot-stable-id-bundle-admission-report.v1.schema.json",
    )
    report_properties = report.get("properties", {})
    legacy.check(
        report_properties.get("version", {}).get("const")
        == "evavo_godot_stable_id_bundle_admission_report_v1",
        "stable-ID bundle report schema version drifted",
    )
    report_authority = report_properties.get("authority", {}).get("properties", {})
    for field in (
        "targetRepositoryMutationAuthority",
        "sourceMutationAuthority",
        "runtimeRegistrationAuthority",
        "commitAuthority",
        "pushAuthority",
        "releaseAuthority",
        "publicationAuthority",
    ):
        legacy.check(
            report_authority.get(field, {}).get("const") is False,
            f"stable-ID bundle report authority drifted: {field}",
        )


def main() -> int:
    try:
        legacy = load_legacy()
        patch_expected_contract(legacy)
        legacy.FAILURES.clear()
        manifest, by_id = legacy.validate_manifest_shape()
        if manifest and by_id:
            legacy.validate_live_sources(manifest, by_id)
            validate_plural_capability(legacy, by_id)
            validate_stable_id_bundle_capability(legacy, by_id)
    except (OSError, RuntimeError) as error:
        print(f"FAIL capability checker could not run: {error}", file=sys.stderr)
        return 1

    if legacy.FAILURES:
        for failure in legacy.FAILURES:
            print(f"FAIL {failure}", file=sys.stderr)
        print(
            f"{len(legacy.FAILURES)} Godot Test Lab capability checks failed.",
            file=sys.stderr,
        )
        return 1

    print(
        "PASS 14 Godot Test Lab capabilities match live guarded source while "
        "retaining no target publication or financial authority."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

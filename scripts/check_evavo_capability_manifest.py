#!/usr/bin/env python3
"""Validate all Test Lab capabilities against retained guarded source."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

WEB_EXPORT_ID = "testlab.web-export.audit"
WEB_EXPORT_EFFECTS = ["read", "compute"]
WEB_EXPORT_INTERFACES = ["automation", "cli", "library", "testing"]
WEB_EXPORT_ENTRYPOINTS = {
    "godot-lab-web-export-audit",
    "python -m godot_game_test_lab.web_export_audit",
    "scripts/audit_godot_web_export.py",
    "src/godot_game_test_lab/web_export_audit.py",
}
WEB_EXPORT_REQUIRES = {
    "Bounded local Godot web export root",
    "schemaVersion 2 export.json descriptor inside the export root",
    "Retained COOP/COEP header evidence when threaded isolation is not descriptor-provided",
    "Browser execution and publication authority remain downstream",
}

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

EXPECTED_SCRIPTS = {
    "godot-lab": "godot_game_test_lab.cli:main",
    "godot-lab-native-qa": "godot_game_test_lab.native_qa:main",
    "godot-lab-multiplayer-qa": "godot_game_test_lab.multiplayer_qa:main",
    "godot-lab-bot-qa": "godot_game_test_lab.bot_qa:main",
    "godot-lab-init-qa": "godot_game_test_lab.profile_bootstrap:main",
    "godot-lab-media-qa": "godot_game_test_lab.media_cli:main",
    "godot-lab-mcp": "godot_game_test_lab.mcp_server:main",
    "godot-lab-engine": "godot_game_test_lab.engine_cli:main",
    "godot-lab-sandbox": "godot_game_test_lab.local_sandbox:main",
    "godot-lab-web-export-audit": "godot_game_test_lab.web_export_audit:main",
    "godot-lab-android-journey": "godot_game_test_lab.android_semantic_driver_cli:main",
    "godot-lab-rally-falcon-preview": "godot_game_test_lab.rally_falcon_preview:main",
    "godot-lab-localization-plural": (
        "godot_game_test_lab.localization_plural_runtime_cli:main"
    ),
    "godot-lab-localization-stable-id-bundle": (
        "godot_game_test_lab.localization_stable_id_bundle_cli:main"
    ),
    "godot-lab-sprite-animation": (
        "godot_game_test_lab.sprite_animation_runtime_cli:main"
    ),
    "godot-lab-sprite-animation-probe": (
        "godot_game_test_lab.sprite_animation_probe_runner:main"
    ),
    "godot-lab-movie-evidence": "godot_game_test_lab.movie_evidence_cli:main",
    "godot-lab-movie-temporal": "godot_game_test_lab.movie_temporal_cli:main",
    "godot-lab-movie-source-identities": (
        "godot_game_test_lab.movie_source_identity_cli:main"
    ),
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
    effects[WEB_EXPORT_ID] = WEB_EXPORT_EFFECTS
    effects[PLURAL_ID] = PLURAL_EFFECTS
    effects[STABLE_ID_BUNDLE_ID] = STABLE_ID_BUNDLE_EFFECTS
    legacy.EXPECTED_EFFECTS = effects
    legacy.EXPECTED_IDS = tuple(effects)
    legacy.EXPECTED_SCRIPTS = dict(EXPECTED_SCRIPTS)


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


def validate_web_export_capability(
    legacy: ModuleType,
    by_id: dict[str, dict],
) -> None:
    capability = by_id.get(WEB_EXPORT_ID, {})
    legacy.check(
        capability.get("interfaces") == WEB_EXPORT_INTERFACES,
        "web-export audit interfaces drifted",
    )
    legacy.check(
        capability.get("effects") == WEB_EXPORT_EFFECTS,
        "web-export audit effect authority drifted",
    )
    legacy.check(
        set(capability.get("entrypoints", [])) == WEB_EXPORT_ENTRYPOINTS,
        "web-export audit entrypoints drifted",
    )
    legacy.check(
        set(capability.get("requires", [])) == WEB_EXPORT_REQUIRES,
        "web-export audit prerequisites drifted",
    )
    tags = set(capability.get("tags", []))
    legacy.check(
        {"web", "integrity", "threaded", "isolation", "read-only"}.issubset(tags),
        "web-export audit tags are incomplete",
    )
    legacy.check(
        capability.get("effects") == ["read", "compute"],
        "web-export audit exceeds read-only computation authority",
    )

    markers = {
        "src/godot_game_test_lab/web_export_audit.py": (
            "class WebExportAuditLimits",
            "assetIntegrity",
            "ensureCrossOriginIsolationHeaders",
            "web.threaded_isolation_unproven",
            "It does not prove browser execution",
        ),
        "scripts/audit_godot_web_export.py": (
            "import_module(\"godot_game_test_lab.web_export_audit\").main",
            "raise SystemExit(main())",
        ),
    }
    for relative, required in markers.items():
        legacy.includes_all(legacy.read(relative, 4_000_000), required, relative)


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
    legacy: ModuleType,
    by_id: dict[str, dict],
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
            validate_web_export_capability(legacy, by_id)
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

    capability_count = len(legacy.EXPECTED_IDS)
    command_count = len(legacy.EXPECTED_SCRIPTS)
    print(
        f"PASS {capability_count} Godot Test Lab capabilities and "
        f"{command_count} commands match live guarded source while retaining "
        "no target publication or financial authority."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLURAL_ID = "testlab.localization.plural-runtime"


def load_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_manifest_declares_exact_guarded_capability_surface() -> None:
    manifest = load_json("evavo.capabilities.json")
    capabilities = {item["id"]: item for item in manifest["capabilities"]}
    assert len(capabilities) == 13
    assert set(capabilities) == {
        "testlab.readiness.automated-testing",
        "testlab.engine.provision",
        "testlab.project.inspect-audit",
        "testlab.project.validate-runtime",
        PLURAL_ID,
        "testlab.qa.native-authored",
        "testlab.qa.multiplayer",
        "testlab.qa.bot",
        "testlab.sandbox.linux",
        "testlab.media.analyze",
        "testlab.asset-delivery.admit",
        "testlab.visual-animation.admit",
        "testlab.rig-motion.accept-v4.1",
    }

    plural = capabilities[PLURAL_ID]
    assert plural["interfaces"] == ["automation", "cli", "testing"]
    assert plural["effects"] == ["read", "compute", "write", "execute"]
    assert "network" not in plural["effects"]
    assert "publish" not in plural["effects"]
    assert "godot-lab-localization-plural" in plural["entrypoints"]
    assert (
        "python -m godot_game_test_lab.localization_plural_runtime_cli"
        in plural["entrypoints"]
    )
    assert "exact-head" in plural["tags"]
    assert "runtime-probe" in plural["tags"]


def test_console_alias_uses_guarded_runtime_cli() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject["project"]["scripts"]
    assert scripts["godot-lab-localization-plural"] == (
        "godot_game_test_lab.localization_plural_runtime_cli:main"
    )


def test_request_and_report_schemas_retain_false_authority() -> None:
    request = load_json(
        "schemas/localization-godot-plural-testlab-request.v1.schema.json"
    )
    request_authority = request["properties"]["authority"]["properties"]
    for field in (
        "requestExecutesGodot",
        "requestWritesTarget",
        "requestPublishesTarget",
        "nativeGodotImportVerified",
        "runtimePluralLookupVerified",
    ):
        assert request_authority[field]["const"] is False
    assert request_authority["testLabExecutionRequired"]["const"] is True

    report = load_json(
        "schemas/evavo-godot-plural-localization-test-lab-report.v1.schema.json"
    )
    report_authority = report["properties"]["authority"]["properties"]
    for field in (
        "targetRepositoryMutationAuthority",
        "repairAuthority",
        "publicationAuthority",
    ):
        assert report_authority[field]["const"] is False


def test_dependency_free_capability_checker_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_evavo_capability_manifest.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "PASS 13 Godot Test Lab capabilities" in result.stdout

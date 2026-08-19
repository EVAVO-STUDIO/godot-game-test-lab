from __future__ import annotations

import json

from godot_game_test_lab.automated_testing_probe import PROBE_SCHEMA, build_probe


def _doctor(*, godot: bool = False, mono: bool = False, dotnet: bool = False):
    return {
        "godot": {"editorCompatible": godot, "executable": "C:/secret/Godot.exe"},
        "godotMono": {"editorCompatible": mono, "executable": "C:/secret/GodotMono.exe"},
        "dotnet": {"available": dotnet, "executable": "C:/secret/dotnet.exe"},
    }


def test_probe_reports_ready_from_compatible_editor_without_exposing_paths():
    value = build_probe(
        doctor_fn=lambda: _doctor(godot=True, dotnet=True),
        installations_fn=lambda: [],
    )
    assert value["schema"] == PROBE_SCHEMA
    assert value["ready"] is True
    assert value["host"]["godotEditorCompatible"] is True
    assert value["host"]["dotnetAvailable"] is True
    assert value["truth"]["targetProjectExecuted"] is False
    assert value["truth"]["engineProvisioningPerformed"] is False
    assert "C:/secret" not in json.dumps(value)


def test_probe_can_be_ready_from_validated_managed_engine_without_provisioning_it():
    value = build_probe(
        doctor_fn=lambda: _doctor(),
        installations_fn=lambda: [
            {"status": "ready", "executable": "C:/private/managed/Godot.exe"},
            {"status": "blocked"},
        ],
    )
    assert value["ready"] is True
    assert value["host"]["managedEngineReady"] is True
    assert value["host"]["managedEngineCount"] == 1
    assert value["truth"]["networkProvisioningPerformed"] is False
    assert "C:/private" not in json.dumps(value)


def test_probe_stays_blocked_when_no_compatible_editor_is_available():
    value = build_probe(
        doctor_fn=lambda: _doctor(dotnet=True),
        installations_fn=lambda: [],
    )
    assert value["ready"] is False
    assert value["capabilities"]["nativeValidation"] is False
    assert value["capabilities"]["nativeBotQa"] is False
    assert value["capabilities"]["staticAudit"] is True
    assert value["capabilities"]["linuxSandbox"] is True
    assert value["truth"]["projectSelected"] is False
    assert value["truth"]["targetProjectMutated"] is False

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "Invoke-GodotLabAndroidJourney.ps1"
CHECKPOINT_HOST = ROOT / "scripts" / "Invoke-GodotLabAndroidSemanticJourneyWithCheckpoints.ps1"
DRIVER = ROOT / "templates" / "android-semantic-driver" / "EVAVOAndroidSemanticDriver.gd"


def test_physical_journey_requires_bridge_mapping_and_physical_device() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    assert "deviceClass -ne 'physical'" in source
    assert "forward --target" in source
    assert "forward-remove --target" in source
    assert "CREATE_ANDROID_PORT_MAPPING" in source
    assert "arbitraryAdbShellExposed = $false" in source
    assert "rawCoordinatesUsed = $false" in source


def test_physical_journey_retains_semantic_outcome_assertions() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    assert "assertionCount" in source
    assert "projectStateAssertionsPerformed" in source
    assert "semanticOutcomeAssertionsClaimed" in source
    assert "finalSemanticState" in source
    assert "semanticDriverEnabled" in source


def test_physical_journey_binds_named_checkpoints_to_android_bridge_evidence() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    host = CHECKPOINT_HOST.read_text(encoding="utf-8")
    assert "Invoke-GodotLabAndroidSemanticJourneyWithCheckpoints.ps1" in source
    assert "visualCheckpointEvidenceCaptured" in source
    assert "visualGameplayEvidenceClaimed" in source
    assert "bridgeEvidenceCheckpoints" in source
    assert "visualCheckpointHostEvidence" in source
    assert "godot_game_test_lab.android_semantic_driver_cli" in host
    assert "android-visual-checkpoint-request.v1" in host
    assert "android-visual-checkpoint-resume.v1" in host
    assert "node $BridgeCli evidence --target $Target --package $Package" in host
    assert "semanticInputOwnedByGodotDriver = $true" in host
    assert "visualEvidenceOwnedByAndroidBridge = $true" in host
    assert "rawCoordinatesUsed = $false" in host
    assert "arbitraryAdbShellExposed = $false" in host


def test_android_driver_remains_debug_loopback_and_bounded_state_only() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    assert 'OS.has_feature("debug")' in source
    assert '_server.listen(port, "127.0.0.1")' in source
    assert 'STATE_PROVIDER_GROUP := "evavo_test_state_provider"' in source
    assert 'STATE_PROVIDER_METHOD := "evavo_test_state"' in source
    assert "MAX_STATE_KEYS := 32" in source
    assert "MAX_STATE_STRING_LENGTH := 128" in source
    assert '"projectState": _collect_project_state()' in source
    assert "get_node(" not in source
    assert "set(" not in source

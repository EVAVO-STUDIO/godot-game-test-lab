from __future__ import annotations

from pathlib import Path

import pytest

from godot_game_test_lab.audio_analysis import AudioAnalysisVerificationError, REPORT_ID
from godot_game_test_lab.audio_analysis_mcp import (
    AudioAnalysisMcpConfig,
    _resolve_contract,
    _resolve_evidence,
    _resolve_target,
    capability_document,
)


def _config(tmp_path: Path) -> tuple[AudioAnalysisMcpConfig, dict[str, Path]]:
    lab = tmp_path / "lab"
    games = tmp_path / "games"
    contracts = tmp_path / "contracts"
    evidence = tmp_path / "evidence"
    target = games / "Brass_Brine"
    for directory in (lab, games, contracts, evidence, target):
        directory.mkdir(parents=True, exist_ok=True)
    (contracts / "contract.json").write_text("{}\n", encoding="utf-8")
    (evidence / "selection.json").write_text("{}\n", encoding="utf-8")
    config = AudioAnalysisMcpConfig.from_environment(
        lab_root=lab,
        allowed_target_roots=[games],
        allowed_contract_roots=[contracts],
        evidence_root=evidence,
    )
    return config, {
        "lab": lab,
        "games": games,
        "contracts": contracts,
        "evidence": evidence,
        "target": target,
    }


def test_capability_document_retains_no_effect_authority(tmp_path: Path) -> None:
    config, _ = _config(tmp_path)
    document = capability_document(config)
    assert document["report"] == REPORT_ID
    assert document["tools"] == [
        "godot_audio_analysis_capabilities",
        "godot_validate_audio_analysis",
    ]
    assert document["writesTargetRepository"] is False
    assert document["performsGitMutation"] is False
    assert document["arbitraryShellAllowed"] is False
    assert document["arbitraryGitArgumentsAllowed"] is False
    assert document["arbitraryExecutablePathsAllowed"] is False
    assert document["publicationAuthority"] is False
    assert document["humanListeningApproval"] is False
    assert document["godotGameplayMixApproval"] is False


def test_root_resolution_is_fail_closed(tmp_path: Path) -> None:
    config, paths = _config(tmp_path)
    assert _resolve_target(str(paths["target"]), config) == paths["target"]
    assert _resolve_contract(
        str(paths["contracts"] / "contract.json"),
        config,
    ) == paths["contracts"] / "contract.json"
    assert _resolve_evidence(
        "selection.json",
        "selection",
        config,
    ) == paths["evidence"] / "selection.json"

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(AudioAnalysisVerificationError, match="outside configured game"):
        _resolve_target(str(outside), config)
    with pytest.raises(AudioAnalysisVerificationError, match="outside configured contract"):
        _resolve_contract(str(outside / "file.json"), config)
    with pytest.raises(AudioAnalysisVerificationError, match="configured evidence root"):
        _resolve_evidence(str(outside / "file.json"), "evidence", config)


def test_evidence_root_must_be_disjoint_from_sources(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    games = tmp_path / "games"
    contracts = tmp_path / "contracts"
    target = games / "Brass_Brine"
    for directory in (lab, games, contracts, target):
        directory.mkdir(parents=True, exist_ok=True)
    with pytest.raises(AudioAnalysisVerificationError, match="disjoint"):
        AudioAnalysisMcpConfig.from_environment(
            lab_root=lab,
            allowed_target_roots=[games],
            allowed_contract_roots=[contracts],
            evidence_root=target / "evidence",
        )

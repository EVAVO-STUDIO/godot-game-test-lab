from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "Invoke-AuthorityPeerExchangeTarget.ps1"


def test_authority_target_runner_preserves_prior_evidence_runs() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "[DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')" in source
    assert "[Guid]::NewGuid().ToString('N').Substring(0, 8)" in source
    assert "refusing to overwrite retained evidence" in source
    assert "New-Item -ItemType Directory -Path $RunRoot | Out-Null" in source
    assert "Remove-Item -LiteralPath $RunRoot -Recurse -Force" not in source


def test_authority_target_run_id_remains_source_identified() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "$TargetState.sha.Substring(0, 12)" in source
    assert "$LabState.sha.Substring(0, 12)" in source
    assert "$Timestamp" in source
    assert "$Nonce" in source

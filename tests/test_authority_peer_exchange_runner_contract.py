from __future__ import annotations

from pathlib import Path


def test_authority_peer_exchange_runner_is_exact_sha_fail_closed_and_ps51_safe() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "Invoke-AuthorityPeerExchangeAcceptance.ps1").read_text(
        encoding="utf-8"
    )

    required = [
        "ExpectedTargetSha",
        "status --porcelain=v1 --untracked-files=all",
        "ConvertTo-WindowsCommandLineArgument",
        "System.Diagnostics.ProcessStartInfo",
        "$start.Arguments",
        "ReadToEndAsync()",
        "System.Text.UTF8Encoding($false)",
        "EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS",
        "godot_game_test_lab.authority_peer_exchange",
        "EVAVO_AUTHORITY_PEER_EXCHANGE=PASS",
        "Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256",
        "Target repository changed during authority peer-exchange acceptance.",
        "EVAVO_AUTHORITY_PEER_EXCHANGE_ACCEPTANCE=PASS",
    ]
    for marker in required:
        assert marker in source

    assert ".ArgumentList" not in source
    assert "Start-Process" not in source
    assert "1> $receiptPath" not in source
    assert "1> $verifierStdout" not in source
    assert "[void]$builder.Append([char]34)" in source

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "print-movie-source-identities.ps1"


def test_windows_launcher_uses_fixed_python_module_and_restores_pythonpath() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Set-StrictMode -Version Latest" in source
    assert "$ErrorActionPreference = 'Stop'" in source
    assert "-m godot_game_test_lab.movie_source_identity_cli" in source
    assert "--adapter $Adapter" in source
    assert "$env:PYTHONPATH = $PreviousPythonPath" in source


def test_windows_launcher_accepts_only_fixed_adapter_selectors() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "[ValidateSet('all', 'capture', 'temporal')]" in source
    assert "Invoke-Expression" not in source
    assert "Start-Process" not in source

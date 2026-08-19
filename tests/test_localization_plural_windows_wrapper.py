from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_wrapper_uses_canonical_guarded_module_without_shell_eval() -> None:
    text = (
        ROOT / "scripts" / "Invoke-GodotPluralLocalizationValidation.ps1"
    ).read_text(encoding="utf-8")
    assert "godot_game_test_lab.localization_plural_runtime_cli" in text
    assert "Invoke-Expression" not in text
    assert "iex " not in text.casefold()
    assert "--request" in text
    assert "--artifacts" in text
    assert "--minimum-godot-version" in text
    assert "@arguments" in text

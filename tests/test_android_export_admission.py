from __future__ import annotations

from pathlib import Path

import pytest

from godot_game_test_lab.android_export_admission import (
    AndroidExportAdmissionError,
    inspect_android_export_preset,
)


def _project(tmp_path: Path, internet: bool = True, platform: str = "Android") -> Path:
    (tmp_path / "project.godot").write_text('[application]\nconfig/name="Test"\n', encoding="utf-8")
    (tmp_path / "export_presets.cfg").write_text(
        "\n".join(
            [
                "[preset.0]",
                'name="Android"',
                f'platform="{platform}"',
                "runnable=true",
                "",
                "[preset.0.options]",
                f"permissions/internet={'true' if internet else 'false'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_accepts_android_preset_with_internet_permission(tmp_path: Path) -> None:
    result = inspect_android_export_preset(_project(tmp_path), "Android")
    assert result.platform == "Android"
    assert result.internet_permission is True
    assert result.preset_index == 0


def test_rejects_missing_internet_permission(tmp_path: Path) -> None:
    with pytest.raises(AndroidExportAdmissionError, match="permissions/internet=true"):
        inspect_android_export_preset(_project(tmp_path, internet=False), "Android")


def test_rejects_non_android_and_ambiguous_presets(tmp_path: Path) -> None:
    with pytest.raises(AndroidExportAdmissionError, match="not an Android"):
        inspect_android_export_preset(_project(tmp_path, platform="Linux"), "Android")

    project = _project(tmp_path)
    export_file = project / "export_presets.cfg"
    export_file.write_text(
        export_file.read_text(encoding="utf-8")
        + '\n[preset.1]\nname="Android"\nplatform="Android"\n\n[preset.1.options]\npermissions/internet=true\n',
        encoding="utf-8",
    )
    with pytest.raises(AndroidExportAdmissionError, match="exactly once"):
        inspect_android_export_preset(project, "Android")

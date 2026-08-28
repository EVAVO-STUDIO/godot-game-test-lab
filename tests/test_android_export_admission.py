from __future__ import annotations

from pathlib import Path

import pytest

from godot_game_test_lab.android_export_admission import (
    AndroidExportAdmissionError,
    inspect_android_export_preset,
)


def _project(
    tmp_path: Path,
    internet: bool = True,
    platform: str = "Android",
    *,
    driver: bool = True,
    enabled: bool = True,
    actions: tuple[str, ...] = ("move_right", "jump"),
) -> Path:
    addon = tmp_path / "addons" / "evavo_test_driver"
    addon.mkdir(parents=True, exist_ok=True)
    if driver:
        (addon / "EVAVOAndroidSemanticDriver.gd").write_text(
            "extends Node\n",
            encoding="utf-8",
        )
    action_text = ", ".join(f'"{value}"' for value in actions)
    driver_autoload = (
        'EVAVOAndroidSemanticDriver="*res://addons/evavo_test_driver/'
        'EVAVOAndroidSemanticDriver.gd"'
        if driver
        else 'Other="*res://other.gd"'
    )
    (tmp_path / "project.godot").write_text(
        "\n".join(
            [
                "[application]",
                'config/name="Test"',
                "",
                "[autoload]",
                driver_autoload,
                "",
                "[evavo]",
                f"test_driver/enabled={'true' if enabled else 'false'}",
                f"test_driver/allowed_actions=PackedStringArray({action_text})",
                "",
            ]
        ),
        encoding="utf-8",
    )
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


def test_accepts_android_preset_with_semantic_driver_and_internet_permission(
    tmp_path: Path,
) -> None:
    result = inspect_android_export_preset(_project(tmp_path), "Android")
    assert result.platform == "Android"
    assert result.internet_permission is True
    assert result.preset_index == 0
    assert result.driver_enabled is True
    assert result.allowed_action_count == 2
    assert result.driver_autoload.endswith("EVAVOAndroidSemanticDriver.gd")


def test_rejects_missing_internet_permission(tmp_path: Path) -> None:
    with pytest.raises(AndroidExportAdmissionError, match="permissions/internet=true"):
        inspect_android_export_preset(_project(tmp_path, internet=False), "Android")


def test_rejects_missing_or_disabled_semantic_driver(tmp_path: Path) -> None:
    with pytest.raises(AndroidExportAdmissionError, match="autoload"):
        inspect_android_export_preset(
            _project(tmp_path / "missing", driver=False),
            "Android",
        )
    with pytest.raises(AndroidExportAdmissionError, match="enabled=true"):
        inspect_android_export_preset(
            _project(tmp_path / "disabled", enabled=False),
            "Android",
        )
    with pytest.raises(AndroidExportAdmissionError, match="1..128"):
        inspect_android_export_preset(
            _project(tmp_path / "actions", actions=()),
            "Android",
        )


def test_rejects_non_android_and_ambiguous_presets(tmp_path: Path) -> None:
    with pytest.raises(AndroidExportAdmissionError, match="not an Android"):
        inspect_android_export_preset(_project(tmp_path, platform="Linux"), "Android")

    project = _project(tmp_path)
    export_file = project / "export_presets.cfg"
    duplicate = "\n".join(
        [
            "",
            "[preset.1]",
            'name="Android"',
            'platform="Android"',
            "",
            "[preset.1.options]",
            "permissions/internet=true",
            "",
        ]
    )
    export_file.write_text(
        export_file.read_text(encoding="utf-8") + duplicate,
        encoding="utf-8",
    )
    with pytest.raises(AndroidExportAdmissionError, match="exactly once"):
        inspect_android_export_preset(project, "Android")

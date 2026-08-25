from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

_SECTION = re.compile(r"^\[(preset\.(\d+)(?:\.options)?)\]$")
_NAME = re.compile(r'^name="(.*)"$')
_PLATFORM = re.compile(r'^platform="(.*)"$')
_INTERNET = re.compile(r"^permissions/internet=(true|false)$")
_AUTOLOAD = re.compile(r'^EVAVOAndroidSemanticDriver\s*=\s*"\*?(res://[^"]+)"$')
_ENABLED = re.compile(r"^test_driver/enabled\s*=\s*(true|false)$")
_ALLOWED = re.compile(r"^test_driver/allowed_actions\s*=\s*PackedStringArray\((.*)\)$")


class AndroidExportAdmissionError(ValueError):
    """Raised when a Godot Android semantic-driver export preset is not admissible."""


@dataclass(frozen=True)
class AndroidExportAdmission:
    preset: str
    preset_index: int
    platform: str
    internet_permission: bool
    driver_autoload: str
    driver_enabled: bool
    allowed_action_count: int


def _inspect_driver(project: Path) -> tuple[str, bool, int]:
    project_file = project / "project.godot"
    if not project_file.is_file():
        raise AndroidExportAdmissionError("project.godot is required for physical Android semantic QA")
    text = project_file.read_text(encoding="utf-8-sig")
    section = ""
    autoload: str | None = None
    enabled = False
    allowed_count = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "autoload":
            match = _AUTOLOAD.fullmatch(line)
            if match:
                autoload = match.group(1)
        elif section == "evavo":
            enabled_match = _ENABLED.fullmatch(line)
            if enabled_match:
                enabled = enabled_match.group(1) == "true"
                continue
            allowed_match = _ALLOWED.fullmatch(line)
            if allowed_match:
                body = allowed_match.group(1).strip()
                if body:
                    allowed_count = len(re.findall(r'"(?:[^"\\]|\\.)*"', body))

    if autoload is None:
        raise AndroidExportAdmissionError("EVAVOAndroidSemanticDriver autoload is required for semantic Android QA")
    script_path = project / autoload.removeprefix("res://")
    if not script_path.is_file():
        raise AndroidExportAdmissionError("EVAVOAndroidSemanticDriver autoload target does not exist")
    if not enabled:
        raise AndroidExportAdmissionError("evavo/test_driver/enabled=true is required for semantic Android QA")
    if not 1 <= allowed_count <= 128:
        raise AndroidExportAdmissionError("evavo/test_driver/allowed_actions must contain 1..128 actions")
    return autoload, True, allowed_count


def inspect_android_export_preset(project: Path, preset: str) -> AndroidExportAdmission:
    project = project.resolve()
    driver_autoload, driver_enabled, allowed_action_count = _inspect_driver(project)
    export_file = project / "export_presets.cfg"
    if not export_file.is_file():
        raise AndroidExportAdmissionError("export_presets.cfg is required for physical Android semantic QA")
    if not preset or len(preset) > 100 or "\x00" in preset:
        raise AndroidExportAdmissionError("preset name is invalid")

    text = export_file.read_text(encoding="utf-8-sig")
    current: tuple[int, bool] | None = None
    values: dict[int, dict[str, object]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        section = _SECTION.fullmatch(line)
        if section:
            index = int(section.group(2))
            current = (index, section.group(1).endswith(".options"))
            values.setdefault(index, {"name": None, "platform": None, "internet": False})
            continue
        if current is None:
            continue
        index, options = current
        if not options:
            name = _NAME.fullmatch(line)
            platform = _PLATFORM.fullmatch(line)
            if name:
                values[index]["name"] = name.group(1)
            elif platform:
                values[index]["platform"] = platform.group(1)
        else:
            internet = _INTERNET.fullmatch(line)
            if internet:
                values[index]["internet"] = internet.group(1) == "true"

    matches = [(index, value) for index, value in values.items() if value["name"] == preset]
    if len(matches) != 1:
        raise AndroidExportAdmissionError("requested Godot export preset must resolve exactly once")
    index, value = matches[0]
    if value["platform"] != "Android":
        raise AndroidExportAdmissionError("requested Godot export preset is not an Android preset")
    if value["internet"] is not True:
        raise AndroidExportAdmissionError(
            "Android semantic QA requires permissions/internet=true in the selected export preset"
        )
    return AndroidExportAdmission(
        preset=preset,
        preset_index=index,
        platform="Android",
        internet_permission=True,
        driver_autoload=driver_autoload,
        driver_enabled=driver_enabled,
        allowed_action_count=allowed_action_count,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Godot Android semantic QA export preset and driver installation.")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--preset", required=True)
    args = parser.parse_args(argv)
    try:
        result = inspect_android_export_preset(args.project, args.preset)
    except AndroidExportAdmissionError as error:
        print(json.dumps({
            "schema": "evavo.godot.android-export-admission.v1",
            "ok": False,
            "code": "android_export_not_admitted",
            "message": str(error),
        }, sort_keys=True))
        return 2
    print(json.dumps({
        "schema": "evavo.godot.android-export-admission.v1",
        "ok": True,
        "preset": result.preset,
        "platform": result.platform,
        "internetPermission": result.internet_permission,
        "semanticDriverAutoload": result.driver_autoload,
        "semanticDriverEnabled": result.driver_enabled,
        "allowedActionCount": result.allowed_action_count,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

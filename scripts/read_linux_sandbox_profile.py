#!/usr/bin/env python3
"""Read and validate a repository-owned Godot Linux sandbox profile."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

VERSION_RE = re.compile(r"^4\.[0-9]+\.[0-9]+$")
SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SAFE_ACTION_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,96}$")
ALLOWED_PROFILE_VERSIONS = {"1.0", "2.0"}
ALLOWED_ENGINE_FLAVORS = {"auto", "standard", "mono"}
ALLOWED_RENDERING_METHODS = {"gl_compatibility", "mobile", "forward_plus"}
ALLOWED_JOURNEY_DEVICES = {"semantic", "keyboard_mouse", "gamepad", "mixed"}
ALLOWED_REQUIRED_ACTION_DEVICES = {"keyboard", "mouse", "gamepad", "action"}
ALLOWED_STEP_TYPES = {
    "wait",
    "action",
    "action_tap",
    "key",
    "key_tap",
    "mouse_move",
    "mouse_button",
    "mouse_click",
    "joy_button",
    "joy_button_tap",
    "joy_axis",
    "checkpoint",
}
ALLOWED_ASSERTION_TYPES = {
    "scene_loaded",
    "input_action_exists",
    "node_exists",
    "node_visible",
    "focus_present",
    "metadata_equals",
}
MAX_ARGUMENTS = 32
MAX_ARGUMENT_BYTES = 256
MAX_JOURNEYS = 4
MAX_JOURNEY_STEPS = 256
MAX_REQUIRED_ACTIONS = 64
MAX_ASSERTIONS = 64
MAX_TEXT_BYTES = 256


class ProfileError(ValueError):
    pass


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProfileError(f"Duplicate JSON key is not allowed: {key!r}")
        value[key] = item
    return value


def _reject_non_finite(value: str) -> None:
    raise ProfileError(f"Non-finite JSON number is not allowed: {value}")


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except ProfileError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileError(
            f"Could not read Linux sandbox profile {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise ProfileError("Linux sandbox profile root must be an object.")
    return value


def _canonical_relative_path(
    value: Any,
    label: str,
    *,
    allow_dot: bool = False,
) -> str:
    text = str(value if value is not None else "").strip()
    if allow_dot and text in ("", "."):
        return "."
    if (
        not text
        or "\\" in text
        or "\x00" in text
        or "\n" in text
        or "\r" in text
    ):
        raise ProfileError(f"{label} must be a canonical relative path.")
    path = PurePosixPath(text)
    if path.is_absolute() or any(
        part in ("", ".", "..") for part in path.parts
    ):
        raise ProfileError(f"{label} must be a canonical relative path.")
    return path.as_posix()


def _scene_path(value: Any, label: str = "visual.scene") -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    if (
        not text.startswith("res://")
        or "\\" in text
        or "\x00" in text
        or "\n" in text
        or "\r" in text
    ):
        raise ProfileError(
            f"{label} must be an empty value or a canonical res:// path."
        )
    tail = text[6:]
    parts = tail.split("/")
    if not tail or any(part in ("", ".", "..") for part in parts):
        raise ProfileError(
            f"{label} must be an empty value or a canonical res:// path."
        )
    return "res://" + "/".join(parts)


def _safe_id(value: Any, label: str) -> str:
    text = str(value if value is not None else "").strip().lower()
    if not SAFE_ID_RE.fullmatch(text):
        raise ProfileError(f"{label} must be a safe lowercase identifier.")
    return text


def _bounded_text(value: Any, label: str, maximum: int = MAX_TEXT_BYTES) -> str:
    if not isinstance(value, str):
        raise ProfileError(f"{label} must be a string.")
    text = value.strip()
    if (
        not text
        or "\x00" in text
        or "\n" in text
        or "\r" in text
        or len(text.encode("utf-8")) > maximum
    ):
        raise ProfileError(f"{label} is empty or exceeds its bounded text limit.")
    return text


def _action_name(value: Any, label: str) -> str:
    text = _bounded_text(value, label, 96)
    if not SAFE_ACTION_RE.fullmatch(text):
        raise ProfileError(f"{label} contains unsupported characters.")
    return text


def _bounded_int(
    value: Any,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfileError(f"{label} must be an integer.")
    if value < minimum or value > maximum:
        raise ProfileError(f"{label} must be between {minimum} and {maximum}.")
    return value


def _bounded_float(
    value: Any,
    label: str,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError(f"{label} must be numeric.")
    result = float(value)
    if not math.isfinite(result) or result < minimum or result > maximum:
        raise ProfileError(f"{label} must be between {minimum} and {maximum}.")
    return result


def _boolean(value: Any, label: str, default: bool) -> bool:
    result = default if value is None else value
    if not isinstance(result, bool):
        raise ProfileError(f"{label} must be a boolean.")
    return result


def _arguments(value: Any, label: str = "visual.userArguments") -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProfileError(f"{label} must be an array.")
    if len(value) > MAX_ARGUMENTS:
        raise ProfileError(f"{label} may contain at most {MAX_ARGUMENTS} values.")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ProfileError(f"{label}[{index}] must be a string.")
        if (
            not item.startswith("--")
            or "\x00" in item
            or "\n" in item
            or "\r" in item
            or len(item.encode("utf-8")) > MAX_ARGUMENT_BYTES
        ):
            raise ProfileError(
                f"{label}[{index}] must be a bounded --prefixed argument."
            )
        result.append(item)
    return result


def _normalise_required_actions(value: Any, journey_index: int) -> list[dict[str, Any]]:
    label = f"journeys[{journey_index}].requiredActions"
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_REQUIRED_ACTIONS:
        raise ProfileError(
            f"{label} must be an array with at most {MAX_REQUIRED_ACTIONS} entries."
        )
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if isinstance(item, str):
            name = _action_name(item, f"{label}[{index}]")
            devices: list[str] = []
        elif isinstance(item, dict):
            name = _action_name(item.get("name"), f"{label}[{index}].name")
            raw_devices = item.get("devices", [])
            if not isinstance(raw_devices, list) or len(raw_devices) > 4:
                raise ProfileError(f"{label}[{index}].devices must be a bounded array.")
            devices = []
            for device_index, device_value in enumerate(raw_devices):
                device = str(device_value).strip().lower()
                if device not in ALLOWED_REQUIRED_ACTION_DEVICES:
                    raise ProfileError(
                        f"{label}[{index}].devices[{device_index}] is unsupported."
                    )
                if device not in devices:
                    devices.append(device)
        else:
            raise ProfileError(f"{label}[{index}] must be a string or object.")
        if name in seen:
            raise ProfileError(f"{label} repeats action {name!r}.")
        seen.add(name)
        result.append({"name": name, "devices": devices})
    return result


def _normalise_step(value: Any, journey_index: int, step_index: int) -> dict[str, Any]:
    label = f"journeys[{journey_index}].steps[{step_index}]"
    if not isinstance(value, dict):
        raise ProfileError(f"{label} must be an object.")
    step_type = str(value.get("type", "")).strip().lower()
    if step_type not in ALLOWED_STEP_TYPES:
        raise ProfileError(f"{label}.type is unsupported: {step_type!r}.")
    result: dict[str, Any] = {"type": step_type}
    if step_type == "wait":
        result["frames"] = _bounded_int(value.get("frames", 1), f"{label}.frames", 1, 600)
    elif step_type in {"action", "action_tap"}:
        result["action"] = _action_name(value.get("action"), f"{label}.action")
        result["strength"] = _bounded_float(
            value.get("strength", 1.0), f"{label}.strength", 0.0, 1.0
        )
        if step_type == "action":
            result["pressed"] = _boolean(value.get("pressed"), f"{label}.pressed", True)
        else:
            result["holdFrames"] = _bounded_int(
                value.get("holdFrames", 1), f"{label}.holdFrames", 1, 120
            )
    elif step_type in {"key", "key_tap"}:
        result["physicalKeycode"] = _bounded_int(
            value.get("physicalKeycode"),
            f"{label}.physicalKeycode",
            1,
            0xFFFFFF,
        )
        if step_type == "key":
            result["pressed"] = _boolean(value.get("pressed"), f"{label}.pressed", True)
        else:
            result["holdFrames"] = _bounded_int(
                value.get("holdFrames", 1), f"{label}.holdFrames", 1, 120
            )
    elif step_type == "mouse_move":
        result["x"] = _bounded_int(value.get("x"), f"{label}.x", -8192, 8192)
        result["y"] = _bounded_int(value.get("y"), f"{label}.y", -8192, 8192)
        result["relativeX"] = _bounded_int(
            value.get("relativeX", 0), f"{label}.relativeX", -4096, 4096
        )
        result["relativeY"] = _bounded_int(
            value.get("relativeY", 0), f"{label}.relativeY", -4096, 4096
        )
    elif step_type in {"mouse_button", "mouse_click"}:
        result["buttonIndex"] = _bounded_int(
            value.get("buttonIndex", 1), f"{label}.buttonIndex", 1, 9
        )
        result["x"] = _bounded_int(value.get("x", 0), f"{label}.x", -8192, 8192)
        result["y"] = _bounded_int(value.get("y", 0), f"{label}.y", -8192, 8192)
        if step_type == "mouse_button":
            result["pressed"] = _boolean(value.get("pressed"), f"{label}.pressed", True)
        else:
            result["holdFrames"] = _bounded_int(
                value.get("holdFrames", 1), f"{label}.holdFrames", 1, 120
            )
    elif step_type in {"joy_button", "joy_button_tap"}:
        result["deviceId"] = _bounded_int(
            value.get("deviceId", 0), f"{label}.deviceId", 0, 7
        )
        result["buttonIndex"] = _bounded_int(
            value.get("buttonIndex"), f"{label}.buttonIndex", 0, 31
        )
        if step_type == "joy_button":
            result["pressed"] = _boolean(value.get("pressed"), f"{label}.pressed", True)
        else:
            result["holdFrames"] = _bounded_int(
                value.get("holdFrames", 1), f"{label}.holdFrames", 1, 120
            )
    elif step_type == "joy_axis":
        result["deviceId"] = _bounded_int(
            value.get("deviceId", 0), f"{label}.deviceId", 0, 7
        )
        result["axis"] = _bounded_int(value.get("axis"), f"{label}.axis", 0, 15)
        result["value"] = _bounded_float(
            value.get("value"), f"{label}.value", -1.0, 1.0
        )
    elif step_type == "checkpoint":
        result["id"] = _safe_id(value.get("id"), f"{label}.id")
    return result


def _normalise_assertion(
    value: Any,
    journey_index: int,
    assertion_index: int,
) -> dict[str, Any]:
    label = f"journeys[{journey_index}].assertions[{assertion_index}]"
    if not isinstance(value, dict):
        raise ProfileError(f"{label} must be an object.")
    assertion_type = str(value.get("type", "")).strip().lower()
    if assertion_type not in ALLOWED_ASSERTION_TYPES:
        raise ProfileError(f"{label}.type is unsupported: {assertion_type!r}.")
    result: dict[str, Any] = {"type": assertion_type}
    if assertion_type == "input_action_exists":
        result["action"] = _action_name(value.get("action"), f"{label}.action")
    elif assertion_type in {"node_exists", "node_visible", "metadata_equals"}:
        result["path"] = _bounded_text(value.get("path"), f"{label}.path")
        if assertion_type == "metadata_equals":
            result["key"] = _bounded_text(value.get("key"), f"{label}.key", 96)
            expected = value.get("value")
            if not isinstance(expected, (str, int, float, bool)) and expected is not None:
                raise ProfileError(f"{label}.value must be a JSON scalar.")
            result["value"] = expected
    return result


def _normalise_ux(value: Any, journey_index: int) -> dict[str, Any]:
    label = f"journeys[{journey_index}].ux"
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ProfileError(f"{label} must be an object.")
    return {
        "captureControlTree": _boolean(
            value.get("captureControlTree"), f"{label}.captureControlTree", True
        ),
        "requireFocusOwner": _boolean(
            value.get("requireFocusOwner"), f"{label}.requireFocusOwner", False
        ),
        "minimumVisibleControls": _bounded_int(
            value.get("minimumVisibleControls", 0),
            f"{label}.minimumVisibleControls",
            0,
            2048,
        ),
        "minimumInteractiveWidth": _bounded_int(
            value.get("minimumInteractiveWidth", 24),
            f"{label}.minimumInteractiveWidth",
            1,
            512,
        ),
        "minimumInteractiveHeight": _bounded_int(
            value.get("minimumInteractiveHeight", 24),
            f"{label}.minimumInteractiveHeight",
            1,
            512,
        ),
        "maximumOutOfBoundsInteractive": _bounded_int(
            value.get("maximumOutOfBoundsInteractive", 0),
            f"{label}.maximumOutOfBoundsInteractive",
            0,
            512,
        ),
        "maximumOverlappingInteractivePairs": _bounded_int(
            value.get("maximumOverlappingInteractivePairs", 16),
            f"{label}.maximumOverlappingInteractivePairs",
            0,
            1024,
        ),
        "maximumSmallInteractiveTargets": _bounded_int(
            value.get("maximumSmallInteractiveTargets", 8),
            f"{label}.maximumSmallInteractiveTargets",
            0,
            512,
        ),
        "failOnBlackFrame": _boolean(
            value.get("failOnBlackFrame"), f"{label}.failOnBlackFrame", True
        ),
        "failOnFrozenVideo": _boolean(
            value.get("failOnFrozenVideo"), f"{label}.failOnFrozenVideo", False
        ),
    }


def _normalise_journeys(value: Any, profile_version: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if profile_version == "1.0":
        raise ProfileError("journeys require Linux sandbox profile schemaVersion 2.0.")
    if not isinstance(value, list) or len(value) > MAX_JOURNEYS:
        raise ProfileError(f"journeys must be an array with at most {MAX_JOURNEYS} entries.")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for journey_index, item in enumerate(value):
        label = f"journeys[{journey_index}]"
        if not isinstance(item, dict):
            raise ProfileError(f"{label} must be an object.")
        journey_id = _safe_id(item.get("id"), f"{label}.id")
        if journey_id in seen:
            raise ProfileError(f"journeys repeats id {journey_id!r}.")
        seen.add(journey_id)
        device = str(item.get("device", "semantic")).strip().lower()
        if device not in ALLOWED_JOURNEY_DEVICES:
            raise ProfileError(f"{label}.device is unsupported: {device!r}.")
        raw_steps = item.get("steps", [])
        if not isinstance(raw_steps, list) or len(raw_steps) > MAX_JOURNEY_STEPS:
            raise ProfileError(
                f"{label}.steps must contain at most {MAX_JOURNEY_STEPS} entries."
            )
        steps = [
            _normalise_step(step, journey_index, step_index)
            for step_index, step in enumerate(raw_steps)
        ]
        raw_assertions = item.get("assertions", [])
        if not isinstance(raw_assertions, list) or len(raw_assertions) > MAX_ASSERTIONS:
            raise ProfileError(
                f"{label}.assertions must contain at most {MAX_ASSERTIONS} entries."
            )
        assertions = [
            _normalise_assertion(assertion, journey_index, assertion_index)
            for assertion_index, assertion in enumerate(raw_assertions)
        ]
        result.append(
            {
                "id": journey_id,
                "required": _boolean(item.get("required"), f"{label}.required", True),
                "device": device,
                "scene": _scene_path(item.get("scene", ""), f"{label}.scene"),
                "maxFrames": _bounded_int(
                    item.get("maxFrames", 900), f"{label}.maxFrames", 30, 3600
                ),
                "settleFrames": _bounded_int(
                    item.get("settleFrames", 30), f"{label}.settleFrames", 0, 600
                ),
                "userArguments": _arguments(
                    item.get("userArguments", []), f"{label}.userArguments"
                ),
                "requiredActions": _normalise_required_actions(
                    item.get("requiredActions", []), journey_index
                ),
                "steps": steps,
                "assertions": assertions,
                "ux": _normalise_ux(item.get("ux", {}), journey_index),
            }
        )
    return result


def read_profile(path: Path) -> dict[str, Any]:
    data = _load_object(path)
    profile_version = str(data.get("schemaVersion", ""))
    if profile_version not in ALLOWED_PROFILE_VERSIONS:
        raise ProfileError(
            "Linux sandbox profile schemaVersion must be 1.0 or 2.0."
        )

    project_subpath = _canonical_relative_path(
        data.get("projectSubpath", "."),
        "projectSubpath",
        allow_dot=True,
    )
    minimum_version = str(data.get("minimumGodotVersion", "4.6.2")).strip()
    if not VERSION_RE.fullmatch(minimum_version):
        raise ProfileError(
            "minimumGodotVersion must be an explicit Godot 4.x.y version."
        )

    engine_flavor = str(data.get("engineFlavor", "auto")).strip().lower()
    if engine_flavor not in ALLOWED_ENGINE_FLAVORS:
        raise ProfileError("engineFlavor must be auto, standard, or mono.")

    visual_value = data.get("visual", {})
    if not isinstance(visual_value, dict):
        raise ProfileError("visual must be an object.")
    visual_required = _boolean(
        visual_value.get("required"), "visual.required", True
    )
    visual_scene = _scene_path(visual_value.get("scene", ""))
    visual_frames = _bounded_int(
        visual_value.get("frames", 180 if visual_required else 0),
        "visual.frames",
        1 if visual_required else 0,
        1800,
    )
    visual_fps = _bounded_int(
        visual_value.get("fps", 30), "visual.fps", 1, 120
    )
    visual_width = _bounded_int(
        visual_value.get("width", 1280), "visual.width", 320, 3840
    )
    visual_height = _bounded_int(
        visual_value.get("height", 720), "visual.height", 180, 2160
    )
    rendering_method = str(
        visual_value.get("renderingMethod", "gl_compatibility")
    ).strip()
    if rendering_method not in ALLOWED_RENDERING_METHODS:
        raise ProfileError(
            "visual.renderingMethod must be gl_compatibility, mobile, or forward_plus."
        )
    user_arguments = _arguments(visual_value.get("userArguments", []))

    export_value = data.get("export", {})
    if not isinstance(export_value, dict):
        raise ProfileError("export must be an object.")
    export_required = _boolean(export_value.get("required"), "export.required", False)
    export_preset = str(export_value.get("preset", "")).strip()
    if export_required and not export_preset:
        raise ProfileError("export.preset is required when export.required is true.")
    if (
        len(export_preset.encode("utf-8")) > 128
        or "\x00" in export_preset
        or "\n" in export_preset
        or "\r" in export_preset
    ):
        raise ProfileError("export.preset is invalid.")

    journeys = _normalise_journeys(data.get("journeys"), profile_version)
    return {
        "schemaVersion": profile_version,
        "projectSubpath": project_subpath,
        "minimumGodotVersion": minimum_version,
        "engineFlavor": engine_flavor,
        "visual": {
            "required": visual_required,
            "scene": visual_scene,
            "frames": visual_frames,
            "fps": visual_fps,
            "width": visual_width,
            "height": visual_height,
            "renderingMethod": rendering_method,
            "userArguments": user_arguments,
        },
        "export": {"required": export_required, "preset": export_preset},
        "journeys": journeys,
    }


def _write_github_outputs(
    path: Path,
    profile: dict[str, Any],
) -> None:
    visual = dict(profile["visual"])
    export = dict(profile["export"])
    journeys = list(profile.get("journeys", []))
    values = {
        "profile_schema_version": profile["schemaVersion"],
        "project_subpath": profile["projectSubpath"],
        "minimum_godot_version": profile["minimumGodotVersion"],
        "engine_flavor": profile["engineFlavor"],
        "visual_required": str(bool(visual["required"])).lower(),
        "visual_scene": visual["scene"],
        "visual_frames": str(visual["frames"]),
        "visual_fps": str(visual["fps"]),
        "visual_width": str(visual["width"]),
        "visual_height": str(visual["height"]),
        "rendering_method": visual["renderingMethod"],
        "visual_arguments_json": json.dumps(
            visual["userArguments"], ensure_ascii=False, separators=(",", ":")
        ),
        "export_required": str(bool(export["required"])).lower(),
        "export_preset": export["preset"],
        "journey_count": str(len(journeys)),
        "required_journey_count": str(
            sum(1 for journey in journeys if bool(journey.get("required", True)))
        ),
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        profile = read_profile(args.profile)
    except ProfileError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, indent=2))
        return 2

    rendered = json.dumps(profile, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.github_output:
        _write_github_outputs(args.github_output, profile)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

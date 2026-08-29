from __future__ import annotations

import math
from typing import Any

from .native_qa_common import (
    _ID_RE,
    _RENDERING_DRIVERS,
    _RENDERING_METHODS,
    _WORKER_ARGUMENT_PREFIXES,
    NativeQaError,
)

_MAX_JOURNEYS = 16
_MAX_STEPS = 256
_MAX_ASSERTIONS = 128
_MAX_REQUIRED_ACTIONS = 128
_MAX_CHECKPOINTS = 32
_MAX_PIXEL_FRAMES_PER_JOURNEY = 8_000_000_000
_MAX_PIXEL_FRAMES_PER_PROFILE = 24_000_000_000
_MAX_DURATION_SECONDS = 600
_SUPPORTED_DEVICES = {
    "keyboard",
    "keyboard_mouse",
    "mouse",
    "semantic",
    "synthetic_gamepad",
}
_SUPPORTED_REQUIRED_DEVICES = {"action", "gamepad", "keyboard", "mouse", "other"}
_TOP_LEVEL_KEYS = {"journeys", "schemaVersion"}
_JOURNEY_KEYS = {
    "assertions",
    "device",
    "fps",
    "gpuIndex",
    "height",
    "id",
    "maxFrames",
    "renderingDriver",
    "renderingMethod",
    "required",
    "requiredActions",
    "scene",
    "settleFrames",
    "steps",
    "userArguments",
    "ux",
    "width",
}
_UX_KEYS = {
    "blackDurationSeconds",
    "captureControlTree",
    "captureUiAtCheckpoints",
    "failOnBlackFrame",
    "failOnFrozenVideo",
    "failOnTruncatedLayoutAnalysis",
    "freezeDurationSeconds",
    "maximumAncestorClippedInteractive",
    "maximumCloseInteractivePairs",
    "maximumOccludedInteractive",
    "maximumOutOfBoundsInteractive",
    "maximumOverlappingInteractivePairs",
    "maximumPairChecks",
    "maximumSmallInteractiveTargets",
    "minimumInteractiveGap",
    "minimumInteractiveHeight",
    "minimumInteractiveWidth",
    "minimumVisibleControls",
    "requireFocusOwner",
}


def _reject_unknown_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise NativeQaError(f"{label} contains unsupported fields: {', '.join(unknown)}")


def _bounded_string(
    value: Any,
    label: str,
    *,
    minimum_bytes: int = 0,
    maximum_bytes: int = 512,
    allow_empty: bool = True,
) -> str:
    if not isinstance(value, str):
        raise NativeQaError(f"{label} must be a string")
    if any(character in value for character in ("\x00", "\n", "\r")):
        raise NativeQaError(f"{label} may not contain control characters")
    encoded = value.encode("utf-8")
    if (not allow_empty and not value) or not minimum_bytes <= len(encoded) <= maximum_bytes:
        raise NativeQaError(
            f"{label} must contain between {minimum_bytes} and {maximum_bytes} UTF-8 bytes"
        )
    return value


def _positive_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise NativeQaError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _finite_number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or not minimum <= float(value) <= maximum
    ):
        raise NativeQaError(f"{label} must be a finite number between {minimum} and {maximum}")
    return float(value)


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise NativeQaError(f"{label} must be boolean")
    return value


def _normalize_user_arguments(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 32:
        raise NativeQaError(f"{label} must be an array of at most 32 strings")
    result: list[str] = []
    for index, item in enumerate(value):
        text = _bounded_string(
            item,
            f"{label}[{index}]",
            minimum_bytes=3,
            maximum_bytes=256,
            allow_empty=False,
        )
        if not text.startswith("--"):
            raise NativeQaError(f"{label}[{index}] must be a --prefixed string")
        owns_lifecycle = any(
            text == option or text.startswith(option + "=")
            for option in _WORKER_ARGUMENT_PREFIXES
        )
        if text == "--" or owns_lifecycle:
            raise NativeQaError(f"{label}[{index}] overrides a worker-owned Godot option")
        result.append(text)
    return result


def _normalize_required_actions(value: Any, label: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > _MAX_REQUIRED_ACTIONS:
        raise NativeQaError(
            f"{label} must contain at most {_MAX_REQUIRED_ACTIONS} entries"
        )
    result: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, item in enumerate(value):
        item_label = f"{label}[{index}]"
        if not isinstance(item, dict):
            raise NativeQaError(f"{item_label} must be an object")
        _reject_unknown_keys(item, {"devices", "name"}, item_label)
        name = _bounded_string(
            item.get("name"),
            f"{item_label}.name",
            minimum_bytes=1,
            maximum_bytes=128,
            allow_empty=False,
        )
        if name in seen_names:
            raise NativeQaError(f"{label} contains a duplicate action: {name}")
        seen_names.add(name)
        devices = item.get("devices", [])
        if not isinstance(devices, list) or len(devices) > len(_SUPPORTED_REQUIRED_DEVICES):
            raise NativeQaError(f"{item_label}.devices must be a bounded array")
        normalized_devices: list[str] = []
        for device in devices:
            if not isinstance(device, str) or device not in _SUPPORTED_REQUIRED_DEVICES:
                raise NativeQaError(f"{item_label}.devices contains an unsupported device")
            if device not in normalized_devices:
                normalized_devices.append(device)
        result.append({"name": name, "devices": normalized_devices})
    return result


def _step_allowed_keys(step_type: str) -> set[str]:
    common = {"type"}
    mapping = {
        "wait": {"frames"},
        "action": {"action", "pressed", "strength"},
        "action_tap": {"action", "holdFrames", "strength"},
        "key": {"physicalKeycode", "pressed"},
        "key_tap": {"holdFrames", "physicalKeycode"},
        "mouse_move": {"relativeX", "relativeY", "x", "y"},
        "mouse_button": {"buttonIndex", "pressed", "x", "y"},
        "mouse_click": {"buttonIndex", "holdFrames", "x", "y"},
        "joy_button": {"buttonIndex", "deviceId", "pressed"},
        "joy_button_tap": {"buttonIndex", "deviceId", "holdFrames"},
        "joy_axis": {"axis", "deviceId", "value"},
        "checkpoint": {"id"},
    }
    return common | mapping.get(step_type, set())


def _normalize_steps(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > _MAX_STEPS:
        raise NativeQaError(f"{label} must contain at most {_MAX_STEPS} entries")
    result: list[dict[str, Any]] = []
    checkpoint_count = 0
    checkpoint_ids: set[str] = set()
    supported = {
        "action",
        "action_tap",
        "checkpoint",
        "joy_axis",
        "joy_button",
        "joy_button_tap",
        "key",
        "key_tap",
        "mouse_button",
        "mouse_click",
        "mouse_move",
        "wait",
    }
    for index, item in enumerate(value):
        item_label = f"{label}[{index}]"
        if not isinstance(item, dict):
            raise NativeQaError(f"{item_label} must be an object")
        step_type = item.get("type")
        if not isinstance(step_type, str) or step_type not in supported:
            raise NativeQaError(f"{item_label}.type is unsupported")
        _reject_unknown_keys(item, _step_allowed_keys(step_type), item_label)
        normalized: dict[str, Any] = {"type": step_type}
        if step_type == "wait":
            normalized["frames"] = _positive_int(
                item.get("frames", 1), f"{item_label}.frames", 0, 1800
            )
        elif step_type in {"action", "action_tap"}:
            normalized["action"] = _bounded_string(
                item.get("action"),
                f"{item_label}.action",
                minimum_bytes=1,
                maximum_bytes=128,
                allow_empty=False,
            )
            normalized["strength"] = _finite_number(
                item.get("strength", 1.0), f"{item_label}.strength", 0.0, 1.0
            )
            if step_type == "action":
                normalized["pressed"] = _boolean(
                    item.get("pressed", True), f"{item_label}.pressed"
                )
            else:
                normalized["holdFrames"] = _positive_int(
                    item.get("holdFrames", 1),
                    f"{item_label}.holdFrames",
                    0,
                    600,
                )
        elif step_type in {"key", "key_tap"}:
            normalized["physicalKeycode"] = _positive_int(
                item.get("physicalKeycode"),
                f"{item_label}.physicalKeycode",
                1,
                0x7FFFFFFF,
            )
            if step_type == "key":
                normalized["pressed"] = _boolean(
                    item.get("pressed", True), f"{item_label}.pressed"
                )
            else:
                normalized["holdFrames"] = _positive_int(
                    item.get("holdFrames", 1),
                    f"{item_label}.holdFrames",
                    0,
                    600,
                )
        elif step_type in {"mouse_move", "mouse_button", "mouse_click"}:
            normalized["x"] = _finite_number(
                item.get("x", 0), f"{item_label}.x", -32768.0, 32768.0
            )
            normalized["y"] = _finite_number(
                item.get("y", 0), f"{item_label}.y", -32768.0, 32768.0
            )
            if step_type == "mouse_move":
                normalized["relativeX"] = _finite_number(
                    item.get("relativeX", 0),
                    f"{item_label}.relativeX",
                    -32768.0,
                    32768.0,
                )
                normalized["relativeY"] = _finite_number(
                    item.get("relativeY", 0),
                    f"{item_label}.relativeY",
                    -32768.0,
                    32768.0,
                )
            else:
                normalized["buttonIndex"] = _positive_int(
                    item.get("buttonIndex"),
                    f"{item_label}.buttonIndex",
                    1,
                    16,
                )
                if step_type == "mouse_button":
                    normalized["pressed"] = _boolean(
                        item.get("pressed", True), f"{item_label}.pressed"
                    )
                else:
                    normalized["holdFrames"] = _positive_int(
                        item.get("holdFrames", 1),
                        f"{item_label}.holdFrames",
                        0,
                        600,
                    )
        elif step_type in {"joy_button", "joy_button_tap", "joy_axis"}:
            normalized["deviceId"] = _positive_int(
                item.get("deviceId", 0), f"{item_label}.deviceId", 0, 15
            )
            if step_type == "joy_axis":
                normalized["axis"] = _positive_int(
                    item.get("axis"), f"{item_label}.axis", 0, 31
                )
                normalized["value"] = _finite_number(
                    item.get("value", 0.0), f"{item_label}.value", -1.0, 1.0
                )
            else:
                normalized["buttonIndex"] = _positive_int(
                    item.get("buttonIndex"),
                    f"{item_label}.buttonIndex",
                    0,
                    127,
                )
                if step_type == "joy_button":
                    normalized["pressed"] = _boolean(
                        item.get("pressed", True), f"{item_label}.pressed"
                    )
                else:
                    normalized["holdFrames"] = _positive_int(
                        item.get("holdFrames", 1),
                        f"{item_label}.holdFrames",
                        0,
                        600,
                    )
        elif step_type == "checkpoint":
            checkpoint = item.get("id")
            if not isinstance(checkpoint, str) or _ID_RE.fullmatch(checkpoint) is None:
                raise NativeQaError(f"{item_label}.id is not a safe checkpoint identifier")
            if checkpoint in checkpoint_ids:
                raise NativeQaError(f"{label} contains a duplicate checkpoint: {checkpoint}")
            checkpoint_ids.add(checkpoint)
            checkpoint_count += 1
            if checkpoint_count > _MAX_CHECKPOINTS:
                raise NativeQaError(
                    f"{label} may contain at most {_MAX_CHECKPOINTS} checkpoints"
                )
            normalized["id"] = checkpoint
        result.append(normalized)
    return result


def _normalize_assertions(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > _MAX_ASSERTIONS:
        raise NativeQaError(f"{label} must contain at most {_MAX_ASSERTIONS} entries")
    supported = {
        "focus_present",
        "input_action_exists",
        "metadata_equals",
        "node_exists",
        "node_visible",
        "scene_loaded",
    }
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        item_label = f"{label}[{index}]"
        if not isinstance(item, dict):
            raise NativeQaError(f"{item_label} must be an object")
        assertion_type = item.get("type")
        if not isinstance(assertion_type, str) or assertion_type not in supported:
            raise NativeQaError(f"{item_label}.type is unsupported")
        allowed = {"type"}
        if assertion_type == "input_action_exists":
            allowed.add("action")
        elif assertion_type in {"node_exists", "node_visible"}:
            allowed.add("path")
        elif assertion_type == "metadata_equals":
            allowed.update({"key", "path", "value"})
        _reject_unknown_keys(item, allowed, item_label)
        normalized = dict(item)
        if "action" in allowed:
            normalized["action"] = _bounded_string(
                item.get("action"),
                f"{item_label}.action",
                minimum_bytes=1,
                maximum_bytes=128,
                allow_empty=False,
            )
        if "path" in allowed:
            normalized["path"] = _bounded_string(
                item.get("path"),
                f"{item_label}.path",
                minimum_bytes=1,
                maximum_bytes=512,
                allow_empty=False,
            )
        if "key" in allowed:
            normalized["key"] = _bounded_string(
                item.get("key"),
                f"{item_label}.key",
                minimum_bytes=1,
                maximum_bytes=128,
                allow_empty=False,
            )
        result.append(normalized)
    return result


def _normalize_ux(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise NativeQaError(f"{label} must be an object")
    _reject_unknown_keys(value, _UX_KEYS, label)
    return {
        "captureControlTree": _boolean(
            value.get("captureControlTree", True), f"{label}.captureControlTree"
        ),
        "captureUiAtCheckpoints": _boolean(
            value.get("captureUiAtCheckpoints", True),
            f"{label}.captureUiAtCheckpoints",
        ),
        "failOnBlackFrame": _boolean(
            value.get("failOnBlackFrame", False), f"{label}.failOnBlackFrame"
        ),
        "failOnFrozenVideo": _boolean(
            value.get("failOnFrozenVideo", False), f"{label}.failOnFrozenVideo"
        ),
        "failOnTruncatedLayoutAnalysis": _boolean(
            value.get("failOnTruncatedLayoutAnalysis", False),
            f"{label}.failOnTruncatedLayoutAnalysis",
        ),
        "blackDurationSeconds": _finite_number(
            value.get("blackDurationSeconds", 2.0),
            f"{label}.blackDurationSeconds",
            0.1,
            60.0,
        ),
        "freezeDurationSeconds": _finite_number(
            value.get("freezeDurationSeconds", 5.0),
            f"{label}.freezeDurationSeconds",
            0.1,
            120.0,
        ),
        "minimumVisibleControls": _positive_int(
            value.get("minimumVisibleControls", 0),
            f"{label}.minimumVisibleControls",
            0,
            512,
        ),
        "maximumOutOfBoundsInteractive": _positive_int(
            value.get("maximumOutOfBoundsInteractive", 0),
            f"{label}.maximumOutOfBoundsInteractive",
            0,
            192,
        ),
        "maximumAncestorClippedInteractive": _positive_int(
            value.get("maximumAncestorClippedInteractive", 0),
            f"{label}.maximumAncestorClippedInteractive",
            0,
            192,
        ),
        "maximumOccludedInteractive": _positive_int(
            value.get("maximumOccludedInteractive", 0),
            f"{label}.maximumOccludedInteractive",
            0,
            192,
        ),
        "maximumOverlappingInteractivePairs": _positive_int(
            value.get("maximumOverlappingInteractivePairs", 0),
            f"{label}.maximumOverlappingInteractivePairs",
            0,
            1024,
        ),
        "maximumCloseInteractivePairs": _positive_int(
            value.get("maximumCloseInteractivePairs", 32),
            f"{label}.maximumCloseInteractivePairs",
            0,
            1024,
        ),
        "maximumPairChecks": _positive_int(
            value.get("maximumPairChecks", 50_000),
            f"{label}.maximumPairChecks",
            0,
            50_000,
        ),
        "requireFocusOwner": _boolean(
            value.get("requireFocusOwner", False), f"{label}.requireFocusOwner"
        ),
        "minimumInteractiveWidth": _finite_number(
            value.get("minimumInteractiveWidth", 24),
            f"{label}.minimumInteractiveWidth",
            0.0,
            4096.0,
        ),
        "minimumInteractiveHeight": _finite_number(
            value.get("minimumInteractiveHeight", 24),
            f"{label}.minimumInteractiveHeight",
            0.0,
            4096.0,
        ),
        "minimumInteractiveGap": _finite_number(
            value.get("minimumInteractiveGap", 8),
            f"{label}.minimumInteractiveGap",
            0.0,
            4096.0,
        ),
        "maximumSmallInteractiveTargets": _positive_int(
            value.get("maximumSmallInteractiveTargets", 8),
            f"{label}.maximumSmallInteractiveTargets",
            0,
            192,
        ),
    }


def _estimated_step_frames(steps: list[dict[str, Any]]) -> int:
    total = 0
    for step in steps:
        step_type = step["type"]
        if step_type == "wait":
            total += int(step["frames"])
        elif step_type in {
            "action_tap",
            "joy_button_tap",
            "key_tap",
            "mouse_click",
        }:
            total += int(step["holdFrames"]) + 2
        elif step_type == "checkpoint":
            total += 2
        else:
            total += 1
    return total


def normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_keys(profile, _TOP_LEVEL_KEYS, "native QA profile")
    schema = profile.get("schemaVersion")
    if schema not in {"1.0", "2.0"}:
        raise NativeQaError("native QA profile schemaVersion must be 1.0 or 2.0")
    raw_journeys = profile.get("journeys")
    if not isinstance(raw_journeys, list) or not 1 <= len(raw_journeys) <= _MAX_JOURNEYS:
        raise NativeQaError(
            f"native QA profile must contain 1 to {_MAX_JOURNEYS} journeys"
        )

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_pixel_frames = 0
    for index, raw in enumerate(raw_journeys):
        label = f"journeys[{index}]"
        if not isinstance(raw, dict):
            raise NativeQaError(f"{label} must be an object")
        _reject_unknown_keys(raw, _JOURNEY_KEYS, label)
        journey_id = raw.get("id")
        if not isinstance(journey_id, str) or _ID_RE.fullmatch(journey_id) is None:
            raise NativeQaError(f"{label}.id is invalid")
        if journey_id in seen:
            raise NativeQaError(f"journey id is duplicated: {journey_id}")
        seen.add(journey_id)

        required = _boolean(raw.get("required", True), f"{label}.required")
        scene = _bounded_string(raw.get("scene", ""), f"{label}.scene").strip()
        device = raw.get("device", "semantic")
        if not isinstance(device, str) or device not in _SUPPORTED_DEVICES:
            raise NativeQaError(f"{label}.device is unsupported")
        method = raw.get("renderingMethod", "forward_plus")
        driver = raw.get("renderingDriver", "vulkan")
        if not isinstance(method, str) or method not in _RENDERING_METHODS:
            raise NativeQaError(f"{label}.renderingMethod is unsupported")
        if not isinstance(driver, str) or driver not in _RENDERING_DRIVERS:
            raise NativeQaError(f"{label}.renderingDriver is unsupported")
        if method == "gl_compatibility" and driver != "opengl3":
            raise NativeQaError(
                "gl_compatibility requires renderingDriver opengl3 for deterministic QA"
            )
        if method != "gl_compatibility" and driver == "opengl3":
            raise NativeQaError("forward_plus and mobile require vulkan or d3d12")

        max_frames = _positive_int(
            raw.get("maxFrames", 900), f"{label}.maxFrames", 30, 7200
        )
        fps = _positive_int(raw.get("fps", 30), f"{label}.fps", 1, 60)
        width = _positive_int(raw.get("width", 1280), f"{label}.width", 320, 3840)
        height = _positive_int(raw.get("height", 720), f"{label}.height", 180, 2160)
        if max_frames / fps > _MAX_DURATION_SECONDS:
            raise NativeQaError(
                f"{label} exceeds the {_MAX_DURATION_SECONDS}-second journey duration limit"
            )
        pixel_frames = width * height * max_frames
        if pixel_frames > _MAX_PIXEL_FRAMES_PER_JOURNEY:
            raise NativeQaError(
                f"{label} exceeds the bounded resolution-by-frame budget"
            )
        total_pixel_frames += pixel_frames
        if total_pixel_frames > _MAX_PIXEL_FRAMES_PER_PROFILE:
            raise NativeQaError("native QA profile exceeds its total pixel-frame budget")

        gpu_index = _positive_int(raw.get("gpuIndex", 0), f"{label}.gpuIndex", 0, 31)
        if method == "gl_compatibility" and gpu_index != 0:
            raise NativeQaError(
                "gpuIndex is only available for forward_plus and mobile journeys"
            )

        settle_frames = _positive_int(
            raw.get("settleFrames", 30), f"{label}.settleFrames", 0, 600
        )
        steps = _normalize_steps(raw.get("steps", []), f"{label}.steps")
        estimated_frames = settle_frames + _estimated_step_frames(steps) + 2
        if estimated_frames > max_frames:
            raise NativeQaError(
                f"{label} steps require approximately {estimated_frames} frames but "
                f"maxFrames is {max_frames}"
            )

        normalized.append(
            {
                "id": journey_id,
                "required": required,
                "scene": scene,
                "device": device,
                "settleFrames": settle_frames,
                "maxFrames": max_frames,
                "estimatedFrames": estimated_frames,
                "fps": fps,
                "width": width,
                "height": height,
                "renderingMethod": method,
                "renderingDriver": driver,
                "gpuIndex": gpu_index,
                "userArguments": _normalize_user_arguments(
                    raw.get("userArguments", []), f"{label}.userArguments"
                ),
                "requiredActions": _normalize_required_actions(
                    raw.get("requiredActions", []), f"{label}.requiredActions"
                ),
                "steps": steps,
                "assertions": _normalize_assertions(
                    raw.get("assertions", []), f"{label}.assertions"
                ),
                "ux": _normalize_ux(raw.get("ux", {}), f"{label}.ux"),
                "pixelFrames": pixel_frames,
            }
        )
    return {"schemaVersion": "2.0", "journeys": normalized}

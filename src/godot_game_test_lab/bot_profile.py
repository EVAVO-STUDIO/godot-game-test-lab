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

_MAX_CAMPAIGNS = 12
_MAX_STATES = 64
_MAX_DEPTH = 8
_MAX_RUNS = 256
_MAX_ACTIONS_PER_STATE = 32
_MAX_LIST_ITEMS = 128
_MAX_TOTAL_PIXEL_FRAMES = 64_000_000_000
_DEFAULT_BLOCKED_TEXT = [
    "buy",
    "checkout",
    "delete",
    "erase",
    "format",
    "overwrite",
    "purchase",
    "quit",
    "reset",
    "uninstall",
]
_DEFAULT_DENIED_ACTIONS = [
    "delete",
    "erase",
    "format",
    "purchase",
    "quit",
    "reset",
    "uninstall",
]
_DEVICES = {"gamepad", "keyboard", "mouse", "semantic"}
_MODES = {"action_fuzz", "mixed", "ui_graph"}
_TOP_LEVEL_KEYS = {"campaigns", "schemaVersion"}
_CAMPAIGN_KEYS = {
    "actionAllowlist",
    "actionDenylist",
    "blockedText",
    "checkpointEveryState",
    "devices",
    "fps",
    "gpuIndex",
    "height",
    "id",
    "maxActionsPerState",
    "maxDepth",
    "maxFrames",
    "maxRepresentativePaths",
    "maxRuns",
    "maxStates",
    "mode",
    "recordRepresentativePaths",
    "renderingDriver",
    "renderingMethod",
    "required",
    "scene",
    "seed",
    "settleFrames",
    "stallLimit",
    "userArguments",
    "ux",
    "width",
}
_UX_KEYS = {
    "blackDurationSeconds",
    "captureControlTree",
    "failOnBlackFrame",
    "failOnFrozenVideo",
    "freezeDurationSeconds",
    "maximumOutOfBoundsInteractive",
    "maximumOverlappingInteractivePairs",
    "maximumSmallInteractiveTargets",
    "minimumInteractiveHeight",
    "minimumInteractiveWidth",
    "minimumVisibleControls",
    "requireFocusOwner",
}


def _reject_unknown_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise NativeQaError(f"{label} contains unsupported fields: {', '.join(unknown)}")


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise NativeQaError(f"{label} must be boolean")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise NativeQaError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or not minimum <= float(value) <= maximum
    ):
        raise NativeQaError(f"{label} must be a finite number between {minimum} and {maximum}")
    return float(value)


def _string(
    value: Any,
    label: str,
    *,
    maximum_bytes: int = 512,
    allow_empty: bool = True,
) -> str:
    if not isinstance(value, str):
        raise NativeQaError(f"{label} must be a string")
    if any(character in value for character in ("\x00", "\n", "\r")):
        raise NativeQaError(f"{label} may not contain control characters")
    if (not allow_empty and not value) or len(value.encode("utf-8")) > maximum_bytes:
        raise NativeQaError(f"{label} must be a bounded UTF-8 string")
    return value


def _string_list(
    value: Any,
    label: str,
    *,
    maximum_items: int = _MAX_LIST_ITEMS,
    maximum_bytes: int = 128,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum_items:
        raise NativeQaError(f"{label} must contain at most {maximum_items} strings")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        text = _string(
            item,
            f"{label}[{index}]",
            maximum_bytes=maximum_bytes,
            allow_empty=False,
        ).strip()
        identity = text.casefold()
        if identity not in seen:
            seen.add(identity)
            result.append(text)
    return result


def _normalize_user_arguments(value: Any, label: str) -> list[str]:
    values = _string_list(value, label, maximum_items=32, maximum_bytes=256)
    for index, item in enumerate(values):
        if not item.startswith("--"):
            raise NativeQaError(f"{label}[{index}] must be --prefixed")
        owns_lifecycle = any(
            item == option or item.startswith(option + "=")
            for option in _WORKER_ARGUMENT_PREFIXES
        )
        if item == "--" or owns_lifecycle:
            raise NativeQaError(f"{label}[{index}] overrides a worker-owned Godot option")
    return values


def _normalize_devices(value: Any, label: str) -> list[str]:
    if value is None:
        value = ["mouse", "keyboard", "gamepad", "semantic"]
    if not isinstance(value, list) or not 1 <= len(value) <= len(_DEVICES):
        raise NativeQaError(f"{label} must contain 1 to {len(_DEVICES)} devices")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or item not in _DEVICES:
            raise NativeQaError(f"{label}[{index}] is unsupported")
        if item not in result:
            result.append(item)
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
        "failOnBlackFrame": _boolean(
            value.get("failOnBlackFrame", False), f"{label}.failOnBlackFrame"
        ),
        "failOnFrozenVideo": _boolean(
            value.get("failOnFrozenVideo", False), f"{label}.failOnFrozenVideo"
        ),
        "blackDurationSeconds": _number(
            value.get("blackDurationSeconds", 2.0),
            f"{label}.blackDurationSeconds",
            0.1,
            60.0,
        ),
        "freezeDurationSeconds": _number(
            value.get("freezeDurationSeconds", 5.0),
            f"{label}.freezeDurationSeconds",
            0.1,
            120.0,
        ),
        "minimumVisibleControls": _integer(
            value.get("minimumVisibleControls", 0),
            f"{label}.minimumVisibleControls",
            0,
            512,
        ),
        "maximumOutOfBoundsInteractive": _integer(
            value.get("maximumOutOfBoundsInteractive", 0),
            f"{label}.maximumOutOfBoundsInteractive",
            0,
            192,
        ),
        "maximumOverlappingInteractivePairs": _integer(
            value.get("maximumOverlappingInteractivePairs", 0),
            f"{label}.maximumOverlappingInteractivePairs",
            0,
            1024,
        ),
        "requireFocusOwner": _boolean(
            value.get("requireFocusOwner", False), f"{label}.requireFocusOwner"
        ),
        "minimumInteractiveWidth": _number(
            value.get("minimumInteractiveWidth", 24.0),
            f"{label}.minimumInteractiveWidth",
            0.0,
            4096.0,
        ),
        "minimumInteractiveHeight": _number(
            value.get("minimumInteractiveHeight", 24.0),
            f"{label}.minimumInteractiveHeight",
            0.0,
            4096.0,
        ),
        "maximumSmallInteractiveTargets": _integer(
            value.get("maximumSmallInteractiveTargets", 8),
            f"{label}.maximumSmallInteractiveTargets",
            0,
            192,
        ),
    }


def normalize_bot_profile(profile: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_keys(profile, _TOP_LEVEL_KEYS, "bot QA profile")
    if profile.get("schemaVersion") != "1.0":
        raise NativeQaError("bot QA profile schemaVersion must be 1.0")
    raw_campaigns = profile.get("campaigns")
    if not isinstance(raw_campaigns, list) or not 1 <= len(raw_campaigns) <= _MAX_CAMPAIGNS:
        raise NativeQaError(f"bot QA profile must contain 1 to {_MAX_CAMPAIGNS} campaigns")

    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    total_pixel_frames = 0
    for index, raw in enumerate(raw_campaigns):
        label = f"campaigns[{index}]"
        if not isinstance(raw, dict):
            raise NativeQaError(f"{label} must be an object")
        _reject_unknown_keys(raw, _CAMPAIGN_KEYS, label)
        campaign_id = raw.get("id")
        if not isinstance(campaign_id, str) or _ID_RE.fullmatch(campaign_id) is None:
            raise NativeQaError(f"{label}.id is invalid")
        if campaign_id in seen_ids:
            raise NativeQaError(f"campaign id is duplicated: {campaign_id}")
        seen_ids.add(campaign_id)

        mode = raw.get("mode", "mixed")
        if not isinstance(mode, str) or mode not in _MODES:
            raise NativeQaError(f"{label}.mode is unsupported")
        method = raw.get("renderingMethod", "forward_plus")
        driver = raw.get("renderingDriver", "vulkan")
        if method not in _RENDERING_METHODS or driver not in _RENDERING_DRIVERS:
            raise NativeQaError(f"{label} renderer or driver is unsupported")
        if method == "gl_compatibility" and driver != "opengl3":
            raise NativeQaError("gl_compatibility requires renderingDriver opengl3")
        if method != "gl_compatibility" and driver == "opengl3":
            raise NativeQaError("forward_plus and mobile require vulkan or d3d12")

        max_states = _integer(raw.get("maxStates", 16), f"{label}.maxStates", 1, _MAX_STATES)
        max_depth = _integer(raw.get("maxDepth", 4), f"{label}.maxDepth", 0, _MAX_DEPTH)
        max_runs = _integer(raw.get("maxRuns", 48), f"{label}.maxRuns", 1, _MAX_RUNS)
        if max_runs < max_states:
            raise NativeQaError(f"{label}.maxRuns must be at least maxStates")
        max_frames = _integer(raw.get("maxFrames", 900), f"{label}.maxFrames", 60, 7200)
        fps = _integer(raw.get("fps", 30), f"{label}.fps", 1, 60)
        width = _integer(raw.get("width", 1280), f"{label}.width", 320, 3840)
        height = _integer(raw.get("height", 720), f"{label}.height", 180, 2160)
        pixel_frames = width * height * max_frames * max_runs
        total_pixel_frames += pixel_frames
        if total_pixel_frames > _MAX_TOTAL_PIXEL_FRAMES:
            raise NativeQaError("bot QA profile exceeds its total pixel-frame budget")

        allowlist = _string_list(raw.get("actionAllowlist", []), f"{label}.actionAllowlist")
        denylist = _string_list(
            raw.get("actionDenylist", _DEFAULT_DENIED_ACTIONS),
            f"{label}.actionDenylist",
        )
        blocked = _string_list(
            raw.get("blockedText", _DEFAULT_BLOCKED_TEXT),
            f"{label}.blockedText",
            maximum_items=64,
            maximum_bytes=64,
        )
        result.append(
            {
                "id": campaign_id,
                "required": _boolean(raw.get("required", True), f"{label}.required"),
                "scene": _string(raw.get("scene", ""), f"{label}.scene").strip(),
                "mode": mode,
                "seed": _integer(raw.get("seed", 1871), f"{label}.seed", 0, 2_147_483_647),
                "devices": _normalize_devices(raw.get("devices"), f"{label}.devices"),
                "maxStates": max_states,
                "maxDepth": max_depth,
                "maxRuns": max_runs,
                "maxActionsPerState": _integer(
                    raw.get("maxActionsPerState", 12),
                    f"{label}.maxActionsPerState",
                    1,
                    _MAX_ACTIONS_PER_STATE,
                ),
                "settleFrames": _integer(
                    raw.get("settleFrames", 20), f"{label}.settleFrames", 1, 300
                ),
                "stallLimit": _integer(
                    raw.get("stallLimit", 12), f"{label}.stallLimit", 1, 128
                ),
                "checkpointEveryState": _boolean(
                    raw.get("checkpointEveryState", True),
                    f"{label}.checkpointEveryState",
                ),
                "recordRepresentativePaths": _boolean(
                    raw.get("recordRepresentativePaths", True),
                    f"{label}.recordRepresentativePaths",
                ),
                "maxRepresentativePaths": _integer(
                    raw.get("maxRepresentativePaths", 4),
                    f"{label}.maxRepresentativePaths",
                    0,
                    16,
                ),
                "maxFrames": max_frames,
                "fps": fps,
                "width": width,
                "height": height,
                "renderingMethod": method,
                "renderingDriver": driver,
                "gpuIndex": _integer(
                    raw.get("gpuIndex", 0), f"{label}.gpuIndex", 0, 31
                ),
                "userArguments": _normalize_user_arguments(
                    raw.get("userArguments", []), f"{label}.userArguments"
                ),
                "actionAllowlist": allowlist,
                "actionDenylist": denylist,
                "blockedText": blocked,
                "ux": _normalize_ux(raw.get("ux", {}), f"{label}.ux"),
                "pixelFrames": pixel_frames,
            }
        )
    return {"schemaVersion": "1.0", "campaigns": result}


__all__ = ["normalize_bot_profile"]

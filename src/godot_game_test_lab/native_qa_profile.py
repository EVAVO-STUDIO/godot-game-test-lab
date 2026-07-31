from __future__ import annotations

from typing import Any

from .native_qa_common import (
    NativeQaError,
    _ID_RE,
    _RENDERING_DRIVERS,
    _RENDERING_METHODS,
    _WORKER_ARGUMENT_PREFIXES,
)


def _normalize_user_arguments(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 32:
        raise NativeQaError(f"{label} must be an array of at most 32 strings")
    result: list[str] = []
    for index, item in enumerate(value):
        if (
            not isinstance(item, str)
            or not item.startswith("--")
            or "\x00" in item
            or "\n" in item
            or "\r" in item
            or len(item.encode("utf-8")) > 256
        ):
            raise NativeQaError(f"{label}[{index}] must be a bounded --prefixed string")
        owns_lifecycle = any(
            item == option or item.startswith(option + "=")
            for option in _WORKER_ARGUMENT_PREFIXES
        )
        if item == "--" or owns_lifecycle:
            raise NativeQaError(f"{label}[{index}] overrides a worker-owned Godot option")
        result.append(item)
    return result


def _positive_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise NativeQaError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    schema = profile.get("schemaVersion")
    if schema not in {"1.0", "2.0"}:
        raise NativeQaError("native QA profile schemaVersion must be 1.0 or 2.0")
    raw_journeys = profile.get("journeys")
    if not isinstance(raw_journeys, list) or not 1 <= len(raw_journeys) <= 64:
        raise NativeQaError("native QA profile must contain 1 to 64 journeys")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_journeys):
        if not isinstance(raw, dict):
            raise NativeQaError(f"journeys[{index}] must be an object")
        journey_id = raw.get("id")
        if not isinstance(journey_id, str) or _ID_RE.fullmatch(journey_id) is None:
            raise NativeQaError(f"journeys[{index}].id is invalid")
        if journey_id in seen:
            raise NativeQaError(f"journey id is duplicated: {journey_id}")
        seen.add(journey_id)
        required = raw.get("required", True)
        if not isinstance(required, bool):
            raise NativeQaError(f"journeys[{index}].required must be boolean")
        scene = raw.get("scene", "")
        if not isinstance(scene, str):
            raise NativeQaError(f"journeys[{index}].scene must be a string")
        steps = raw.get("steps", [])
        assertions = raw.get("assertions", [])
        if not isinstance(steps, list) or len(steps) > 512:
            raise NativeQaError(f"journeys[{index}].steps must contain at most 512 entries")
        if not isinstance(assertions, list) or len(assertions) > 256:
            raise NativeQaError(
                f"journeys[{index}].assertions must contain at most 256 entries"
            )
        ux = raw.get("ux", {})
        if not isinstance(ux, dict):
            raise NativeQaError(f"journeys[{index}].ux must be an object")
        method = raw.get("renderingMethod", "forward_plus")
        driver = raw.get("renderingDriver", "vulkan")
        if method not in _RENDERING_METHODS:
            raise NativeQaError(f"journeys[{index}].renderingMethod is unsupported")
        if driver not in _RENDERING_DRIVERS:
            raise NativeQaError(f"journeys[{index}].renderingDriver is unsupported")
        if method == "gl_compatibility" and driver != "opengl3":
            raise NativeQaError(
                "gl_compatibility requires renderingDriver opengl3 for deterministic QA"
            )
        if method != "gl_compatibility" and driver == "opengl3":
            raise NativeQaError("forward_plus and mobile require vulkan or d3d12")
        raw_gpu_index = raw.get("gpuIndex", 0)
        gpu_index = _positive_int(
            raw_gpu_index, f"journeys[{index}].gpuIndex", 0, 31
        )
        if method == "gl_compatibility" and gpu_index != 0:
            raise NativeQaError(
                "gpuIndex is only available for forward_plus and mobile journeys"
            )
        normalized.append(
            {
                **raw,
                "id": journey_id,
                "required": required,
                "scene": scene.strip(),
                "device": str(raw.get("device", "semantic")),
                "settleFrames": _positive_int(
                    raw.get("settleFrames", 30),
                    f"journeys[{index}].settleFrames",
                    0,
                    1800,
                ),
                "maxFrames": _positive_int(
                    raw.get("maxFrames", 900),
                    f"journeys[{index}].maxFrames",
                    30,
                    18000,
                ),
                "fps": _positive_int(raw.get("fps", 30), f"journeys[{index}].fps", 1, 120),
                "width": _positive_int(
                    raw.get("width", 1280), f"journeys[{index}].width", 320, 7680
                ),
                "height": _positive_int(
                    raw.get("height", 720), f"journeys[{index}].height", 180, 4320
                ),
                "renderingMethod": method,
                "renderingDriver": driver,
                "gpuIndex": gpu_index,
                "userArguments": _normalize_user_arguments(
                    raw.get("userArguments", []), f"journeys[{index}].userArguments"
                ),
                "steps": steps,
                "assertions": assertions,
                "ux": ux,
            }
        )
    return {"schemaVersion": "1.0", "journeys": normalized}

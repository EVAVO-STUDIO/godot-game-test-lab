from __future__ import annotations

from copy import deepcopy
from typing import Any

from .native_qa_common import NativeQaError
from .native_qa_profile import normalize_profile as _normalize_base_profile

_EXTRA_UX_KEYS = {
    "captureUiAtCheckpoints",
    "failOnTruncatedLayoutAnalysis",
    "maximumAncestorClippedInteractive",
    "maximumCloseInteractivePairs",
    "maximumOccludedInteractive",
    "maximumPairChecks",
    "minimumInteractiveGap",
}


def _boolean(value: Any, label: str, default: bool) -> bool:
    resolved = default if value is None else value
    if not isinstance(resolved, bool):
        raise NativeQaError(f"{label} must be boolean")
    return resolved


def _bounded_integer(
    value: Any,
    label: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    resolved = default if value is None else value
    if (
        not isinstance(resolved, int)
        or isinstance(resolved, bool)
        or not minimum <= resolved <= maximum
    ):
        raise NativeQaError(
            f"{label} must be an integer between {minimum} and {maximum}"
        )
    return resolved


def _bounded_number(
    value: Any,
    label: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    resolved = default if value is None else value
    if isinstance(resolved, bool) or not isinstance(resolved, int | float):
        raise NativeQaError(
            f"{label} must be a finite number between {minimum} and {maximum}"
        )
    number = float(resolved)
    if number != number or number in {float("inf"), float("-inf")}:
        raise NativeQaError(
            f"{label} must be a finite number between {minimum} and {maximum}"
        )
    if not minimum <= number <= maximum:
        raise NativeQaError(
            f"{label} must be a finite number between {minimum} and {maximum}"
        )
    return number


def _normalize_visual_ux(value: dict[str, Any], label: str) -> dict[str, Any]:
    return {
        "captureUiAtCheckpoints": _boolean(
            value.get("captureUiAtCheckpoints"),
            f"{label}.captureUiAtCheckpoints",
            True,
        ),
        "minimumInteractiveGap": _bounded_number(
            value.get("minimumInteractiveGap"),
            f"{label}.minimumInteractiveGap",
            default=8.0,
            minimum=0.0,
            maximum=4096.0,
        ),
        "maximumPairChecks": _bounded_integer(
            value.get("maximumPairChecks"),
            f"{label}.maximumPairChecks",
            default=50_000,
            minimum=0,
            maximum=50_000,
        ),
        "maximumAncestorClippedInteractive": _bounded_integer(
            value.get("maximumAncestorClippedInteractive"),
            f"{label}.maximumAncestorClippedInteractive",
            default=0,
            minimum=0,
            maximum=192,
        ),
        "maximumOccludedInteractive": _bounded_integer(
            value.get("maximumOccludedInteractive"),
            f"{label}.maximumOccludedInteractive",
            default=0,
            minimum=0,
            maximum=192,
        ),
        "maximumCloseInteractivePairs": _bounded_integer(
            value.get("maximumCloseInteractivePairs"),
            f"{label}.maximumCloseInteractivePairs",
            default=32,
            minimum=0,
            maximum=1024,
        ),
        "failOnTruncatedLayoutAnalysis": _boolean(
            value.get("failOnTruncatedLayoutAnalysis"),
            f"{label}.failOnTruncatedLayoutAnalysis",
            False,
        ),
    }


def normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Normalize the native QA profile plus governed visual-layout controls.

    The established native profile normalizer remains authoritative for the
    existing schema. This wrapper removes only the known visual extension
    fields before delegating, then appends validated, bounded defaults to each
    normalized journey. Unknown fields continue to fail closed in the base
    normalizer.
    """

    candidate = deepcopy(profile)
    raw_journeys = candidate.get("journeys")
    if not isinstance(raw_journeys, list):
        return _normalize_base_profile(candidate)

    extensions: list[dict[str, Any]] = []
    for index, raw_journey in enumerate(raw_journeys):
        if not isinstance(raw_journey, dict):
            extensions.append(_normalize_visual_ux({}, f"journeys[{index}].ux"))
            continue
        raw_ux = raw_journey.get("ux", {})
        if raw_ux is None:
            raw_ux = {}
        if not isinstance(raw_ux, dict):
            # Let the base normalizer produce the canonical type failure.
            extensions.append(_normalize_visual_ux({}, f"journeys[{index}].ux"))
            continue
        extensions.append(
            _normalize_visual_ux(raw_ux, f"journeys[{index}].ux")
        )
        raw_journey["ux"] = {
            key: value for key, value in raw_ux.items() if key not in _EXTRA_UX_KEYS
        }

    normalized = _normalize_base_profile(candidate)
    normalized_journeys = normalized.get("journeys")
    if not isinstance(normalized_journeys, list) or len(normalized_journeys) != len(
        extensions
    ):
        raise NativeQaError(
            "native QA profile normalization changed the journey cardinality"
        )
    for journey, extension in zip(normalized_journeys, extensions, strict=True):
        if not isinstance(journey, dict) or not isinstance(journey.get("ux"), dict):
            raise NativeQaError("normalized native QA journey has no UX object")
        journey["ux"].update(extension)
    return normalized

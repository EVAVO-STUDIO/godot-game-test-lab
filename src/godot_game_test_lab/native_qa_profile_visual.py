from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from .native_qa_common import NativeQaError
from .native_qa_profile import normalize_profile as _normalize_base_profile

_VISUAL_UX_KEYS = {
    "captureUiAtCheckpoints",
    "failOnTruncatedLayoutAnalysis",
    "maximumAncestorClippedInteractive",
    "maximumCloseInteractivePairs",
    "maximumIssues",
    "maximumOccludedInteractive",
    "maximumPairChecks",
    "minimumInteractiveGap",
}


def _boolean(value: Any, fallback: bool, label: str) -> bool:
    candidate = fallback if value is None else value
    if not isinstance(candidate, bool):
        raise NativeQaError(f"{label} must be boolean")
    return candidate


def _integer(
    value: Any,
    fallback: int,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    candidate = fallback if value is None else value
    if (
        not isinstance(candidate, int)
        or isinstance(candidate, bool)
        or not minimum <= candidate <= maximum
    ):
        raise NativeQaError(
            f"{label} must be an integer between {minimum} and {maximum}"
        )
    return candidate


def _finite_number(
    value: Any,
    fallback: float,
    minimum: float,
    maximum: float,
    label: str,
) -> float:
    candidate = fallback if value is None else value
    if (
        not isinstance(candidate, int | float)
        or isinstance(candidate, bool)
        or not math.isfinite(float(candidate))
        or not minimum <= float(candidate) <= maximum
    ):
        raise NativeQaError(
            f"{label} must be a finite number between {minimum} and {maximum}"
        )
    return float(candidate)


def _normalize_visual_ux(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise NativeQaError(f"{label} must be an object")
    return {
        "captureUiAtCheckpoints": _boolean(
            value.get("captureUiAtCheckpoints"),
            True,
            f"{label}.captureUiAtCheckpoints",
        ),
        "minimumInteractiveGap": _finite_number(
            value.get("minimumInteractiveGap"),
            8.0,
            0.0,
            1024.0,
            f"{label}.minimumInteractiveGap",
        ),
        "maximumCloseInteractivePairs": _integer(
            value.get("maximumCloseInteractivePairs"),
            32,
            0,
            1024,
            f"{label}.maximumCloseInteractivePairs",
        ),
        "maximumAncestorClippedInteractive": _integer(
            value.get("maximumAncestorClippedInteractive"),
            0,
            0,
            512,
            f"{label}.maximumAncestorClippedInteractive",
        ),
        "maximumOccludedInteractive": _integer(
            value.get("maximumOccludedInteractive"),
            0,
            0,
            512,
            f"{label}.maximumOccludedInteractive",
        ),
        "maximumPairChecks": _integer(
            value.get("maximumPairChecks"),
            50_000,
            0,
            50_000,
            f"{label}.maximumPairChecks",
        ),
        "maximumIssues": _integer(
            value.get("maximumIssues"),
            1_024,
            1,
            10_000,
            f"{label}.maximumIssues",
        ),
        "failOnTruncatedLayoutAnalysis": _boolean(
            value.get("failOnTruncatedLayoutAnalysis"),
            False,
            f"{label}.failOnTruncatedLayoutAnalysis",
        ),
    }


def normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Normalize a native QA profile including the visual-layout v3 UX controls.

    The legacy normalizer remains the authority for the existing schema. This
    wrapper removes only the explicitly governed visual keys, delegates every
    established validation rule, and then merges the bounded visual settings
    back into the normalized journey records. Unknown keys still reach the
    legacy normalizer and remain rejected.
    """

    if not isinstance(profile, dict):
        raise NativeQaError("native QA profile must be an object")
    raw_journeys = profile.get("journeys")
    if not isinstance(raw_journeys, list):
        return _normalize_base_profile(profile)

    sanitized = deepcopy(profile)
    sanitized_journeys = sanitized.get("journeys")
    visual_settings: list[dict[str, Any]] = []
    for index, raw_journey in enumerate(raw_journeys):
        label = f"journeys[{index}].ux"
        raw_ux = raw_journey.get("ux", {}) if isinstance(raw_journey, dict) else {}
        visual_settings.append(_normalize_visual_ux(raw_ux, label))
        if not isinstance(raw_journey, dict):
            continue
        sanitized_journey = sanitized_journeys[index]
        sanitized_ux = sanitized_journey.get("ux")
        if isinstance(sanitized_ux, dict):
            for key in _VISUAL_UX_KEYS:
                sanitized_ux.pop(key, None)

    normalized = _normalize_base_profile(sanitized)
    journeys = normalized.get("journeys")
    if not isinstance(journeys, list) or len(journeys) != len(visual_settings):
        raise NativeQaError("normalized native QA journeys do not match the source profile")
    for journey, settings in zip(journeys, visual_settings, strict=True):
        ux = journey.get("ux")
        if not isinstance(ux, dict):
            raise NativeQaError("normalized native QA journey is missing its UX policy")
        ux.update(settings)
    return normalized

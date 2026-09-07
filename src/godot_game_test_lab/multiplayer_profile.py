from __future__ import annotations

from typing import Any

from .native_qa_common import _ID_RE, NativeQaError
from .native_qa_profile import _bounded_string, normalize_profile

_MAX_ROLES = 8
_MAX_START_DELAY_MS = 120_000
_TOP_LEVEL_KEYS = {"roles", "schemaVersion"}
_ROLE_KEYS = {"id", "journey", "personaId", "required", "startDelayMs"}
_CAPTURE_ASSERTION_TYPE = "metadata_capture"
_CAPTURE_ASSERTION_KEYS = {"key", "path", "type"}


def _reject_unknown_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise NativeQaError(f"{label} contains unsupported fields: {', '.join(unknown)}")


def _prepare_capture_assertions(
    journey: dict[str, Any], label: str
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    raw_assertions = journey.get("assertions", [])
    if not isinstance(raw_assertions, list):
        return journey, {}

    captures: dict[int, dict[str, Any]] = {}
    prepared_assertions: list[Any] = []
    for index, assertion in enumerate(raw_assertions):
        assertion_label = f"{label}.assertions[{index}]"
        if not isinstance(assertion, dict) or assertion.get("type") != _CAPTURE_ASSERTION_TYPE:
            prepared_assertions.append(assertion)
            continue
        _reject_unknown_keys(assertion, _CAPTURE_ASSERTION_KEYS, assertion_label)
        path = _bounded_string(
            assertion.get("path"),
            f"{assertion_label}.path",
            minimum_bytes=1,
            maximum_bytes=512,
            allow_empty=False,
        )
        key = _bounded_string(
            assertion.get("key"),
            f"{assertion_label}.key",
            minimum_bytes=1,
            maximum_bytes=128,
            allow_empty=False,
        )
        captures[index] = {
            "type": _CAPTURE_ASSERTION_TYPE,
            "path": path,
            "key": key,
        }
        # Reuse the native assertion normalizer for path/count/order validation
        # without advertising metadata_capture to standalone native QA.
        prepared_assertions.append({"type": "node_exists", "path": path})

    prepared = dict(journey)
    prepared["assertions"] = prepared_assertions
    return prepared, captures


def _restore_capture_assertions(
    journey: dict[str, Any], captures: dict[int, dict[str, Any]], label: str
) -> dict[str, Any]:
    if not captures:
        return journey
    assertions = journey.get("assertions")
    if not isinstance(assertions, list):
        raise NativeQaError(f"{label}.assertions normalization lost its assertion array")
    restored = [dict(item) if isinstance(item, dict) else item for item in assertions]
    for index, capture in captures.items():
        if index >= len(restored):
            raise NativeQaError(f"{label}.assertions normalization changed capture ordering")
        placeholder = restored[index]
        if (
            not isinstance(placeholder, dict)
            or placeholder.get("type") != "node_exists"
            or placeholder.get("path") != capture["path"]
        ):
            raise NativeQaError(f"{label}.assertions normalization changed capture identity")
        restored[index] = dict(capture)
    result = dict(journey)
    result["assertions"] = restored
    return result


def normalize_multiplayer_profile(profile: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_keys(profile, _TOP_LEVEL_KEYS, "multiplayer QA profile")
    if profile.get("schemaVersion") != "1.0":
        raise NativeQaError("multiplayer QA profile schemaVersion must be 1.0")
    raw_roles = profile.get("roles")
    if not isinstance(raw_roles, list) or not 2 <= len(raw_roles) <= _MAX_ROLES:
        raise NativeQaError(f"multiplayer QA profile must contain 2 to {_MAX_ROLES} roles")

    seen: set[str] = set()
    normalized_roles: list[dict[str, Any]] = []
    for index, raw_role in enumerate(raw_roles):
        label = f"roles[{index}]"
        if not isinstance(raw_role, dict):
            raise NativeQaError(f"{label} must be an object")
        _reject_unknown_keys(raw_role, _ROLE_KEYS, label)
        role_id = raw_role.get("id")
        if not isinstance(role_id, str) or _ID_RE.fullmatch(role_id) is None:
            raise NativeQaError(f"{label}.id is invalid")
        if role_id in seen:
            raise NativeQaError(f"multiplayer role id is duplicated: {role_id}")
        seen.add(role_id)

        persona_id = raw_role.get("personaId")
        if persona_id is not None:
            if (
                not isinstance(persona_id, str)
                or not persona_id.strip()
                or len(persona_id.encode("utf-8")) > 128
                or any(character in persona_id for character in ("\x00", "\n", "\r"))
            ):
                raise NativeQaError(f"{label}.personaId must be a bounded single-line string")
            persona_id = persona_id.strip()

        required = raw_role.get("required", True)
        if not isinstance(required, bool):
            raise NativeQaError(f"{label}.required must be boolean")
        start_delay_ms = raw_role.get("startDelayMs", 0)
        if (
            not isinstance(start_delay_ms, int)
            or isinstance(start_delay_ms, bool)
            or not 0 <= start_delay_ms <= _MAX_START_DELAY_MS
        ):
            raise NativeQaError(
                f"{label}.startDelayMs must be an integer between 0 and {_MAX_START_DELAY_MS}"
            )

        raw_journey = raw_role.get("journey")
        if not isinstance(raw_journey, dict):
            raise NativeQaError(f"{label}.journey must be an object")
        if "id" in raw_journey and raw_journey.get("id") != role_id:
            raise NativeQaError(f"{label}.journey.id must match the multiplayer role id")
        journey = dict(raw_journey)
        journey["id"] = role_id
        journey["required"] = required
        prepared_journey, captures = _prepare_capture_assertions(journey, f"{label}.journey")
        normalized_journey = normalize_profile(
            {"schemaVersion": "2.0", "journeys": [prepared_journey]}
        )["journeys"][0]
        normalized_journey = _restore_capture_assertions(
            normalized_journey, captures, f"{label}.journey"
        )
        normalized_roles.append(
            {
                "id": role_id,
                "personaId": persona_id,
                "required": required,
                "startDelayMs": start_delay_ms,
                "journey": normalized_journey,
            }
        )

    return {
        "schemaVersion": "1.0",
        "roles": normalized_roles,
        "truthBoundary": (
            "Role and persona labels describe test intent. A passing session proves only "
            "the exact concurrent runtime journeys and retained evidence; "
            "it does not prove human judgement, game feel or complete multiplayer correctness."
        ),
    }

from __future__ import annotations

from typing import Any

from .attended_multiplayer_common import is_record, safe_id

_MAX_ROLES = 8
_MAX_OBSERVED_PEERS = 32
_MAX_SESSION_BYTES = 256
_ALLOWED_ROLE_FIELDS = {
    "id",
    "sessionId",
    "localPeerId",
    "observedPeerIds",
    "authorityPeerId",
    "dynamicRequiredMetadataCaptured",
    "reservedAssertionsAccepted",
}


class PeerExchangeMatrixError(ValueError):
    """Raised when a peer-exchange matrix is structurally inadmissible."""


def _fail(message: str) -> None:
    raise PeerExchangeMatrixError(message)


def positive_peer_id(value: object, label: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > 2**31 - 1
    ):
        _fail(f"{label} must be a positive peer id")
    return value


def bounded_session_id(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value.encode("utf-8")) > _MAX_SESSION_BYTES
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        _fail(f"{label} must be a bounded non-empty single-line session id")
    return value


def _strict_optional_bool(role: dict[str, Any], key: str, default: bool, role_id: str) -> bool:
    if key not in role:
        return default
    value = role[key]
    if not isinstance(value, bool):
        _fail(f"role {role_id} {key} must be boolean")
    return value


def validate_peer_matrix(
    roles: object,
    *,
    truth_boundary: str,
    dynamic_capture_role_count: int = 0,
    require_authority_participant: bool = True,
) -> dict[str, Any]:
    if not isinstance(roles, list) or not 2 <= len(roles) <= _MAX_ROLES:
        _fail("peer-exchange matrix must contain between two and eight roles")
    if (
        not isinstance(dynamic_capture_role_count, int)
        or isinstance(dynamic_capture_role_count, bool)
        or dynamic_capture_role_count < 0
        or dynamic_capture_role_count > len(roles)
    ):
        _fail("dynamic capture role count is invalid")
    if not isinstance(require_authority_participant, bool):
        _fail("require_authority_participant must be boolean")
    if not isinstance(truth_boundary, str) or truth_boundary != truth_boundary.strip() or not truth_boundary:
        _fail("peer-exchange truth boundary must be a trimmed non-empty string")
    if len(truth_boundary.encode("utf-8")) > 4096 or any(
        character in truth_boundary for character in ("\x00", "\r")
    ):
        _fail("peer-exchange truth boundary is invalid")

    normalized: list[dict[str, Any]] = []
    seen_role_ids: set[str] = set()
    session_values: dict[str, str] = {}
    local_peer_ids: dict[str, int] = {}
    observed_peer_ids: dict[str, list[int]] = {}
    authority_peer_ids: dict[str, int] = {}
    actual_dynamic_capture_count = 0
    rejected_assertion_roles: list[str] = []

    for index, raw in enumerate(roles):
        if not is_record(raw):
            _fail(f"peer-exchange role {index} must be an object")
        role = dict(raw)
        unexpected = sorted(set(role) - _ALLOWED_ROLE_FIELDS)
        if unexpected:
            _fail(
                f"peer-exchange role {index} has unexpected fields: {', '.join(unexpected)}"
            )
        role_id = safe_id(role.get("id"), "PEER_EXCHANGE_MATRIX_ROLE_ID_INVALID")
        if role_id in seen_role_ids:
            _fail("peer-exchange role id is duplicated")
        seen_role_ids.add(role_id)

        session_id = bounded_session_id(role.get("sessionId"), f"role {role_id} session id")
        local_peer = positive_peer_id(role.get("localPeerId"), f"role {role_id} local peer id")
        observed_raw = role.get("observedPeerIds")
        if not isinstance(observed_raw, list) or len(observed_raw) > _MAX_OBSERVED_PEERS:
            _fail(f"role {role_id} observed peer ids must be a bounded array")
        observed = [
            positive_peer_id(value, f"role {role_id} observed peer id")
            for value in observed_raw
        ]
        if len(set(observed)) != len(observed):
            _fail(f"role {role_id} observed peer ids contain duplicates")
        if local_peer in observed:
            _fail(f"role {role_id} observed peer ids include its local peer id")

        authority_value = role.get("authorityPeerId")
        authority_peer: int | None = None
        if authority_value is not None:
            authority_peer = positive_peer_id(
                authority_value, f"role {role_id} authority peer id"
            )
            authority_peer_ids[role_id] = authority_peer

        dynamic_captured = _strict_optional_bool(
            role, "dynamicRequiredMetadataCaptured", False, role_id
        )
        assertions_accepted = _strict_optional_bool(
            role, "reservedAssertionsAccepted", True, role_id
        )
        if dynamic_captured:
            actual_dynamic_capture_count += 1
        if not assertions_accepted:
            rejected_assertion_roles.append(role_id)

        session_values[role_id] = session_id
        local_peer_ids[role_id] = local_peer
        observed_peer_ids[role_id] = observed
        normalized.append(
            {
                "id": role_id,
                "sessionId": session_id,
                "localPeerId": local_peer,
                "observedPeerIds": observed,
                "authorityPeerId": authority_peer,
                "dynamicRequiredMetadataCaptured": dynamic_captured,
                "reservedAssertionsAccepted": assertions_accepted,
            }
        )

    if actual_dynamic_capture_count != dynamic_capture_role_count:
        _fail(
            "dynamic capture role count disagrees with role evidence: "
            f"declared={dynamic_capture_role_count} actual={actual_dynamic_capture_count}"
        )

    findings: list[str] = []
    if rejected_assertion_roles:
        findings.append(
            "reserved multiplayer assertions were not accepted for roles: "
            + ", ".join(sorted(rejected_assertion_roles))
        )
    if len(set(session_values.values())) != 1:
        findings.append("required roles did not report one shared multiplayer session id")
    if len(set(local_peer_ids.values())) != len(local_peer_ids):
        findings.append("required roles did not report unique local peer ids")

    expected_peer_ids = set(local_peer_ids.values())
    for role_id, local_peer in local_peer_ids.items():
        required_remote_ids = expected_peer_ids - {local_peer}
        if not required_remote_ids.issubset(set(observed_peer_ids[role_id])):
            findings.append(
                f"role {role_id} did not report every other required peer as observed"
            )

    authority_count = len(authority_peer_ids)
    if authority_count not in {0, len(normalized)}:
        findings.append(
            "authority peer evidence is only partially configured across required roles"
        )
    elif authority_count == len(normalized):
        shared_authorities = set(authority_peer_ids.values())
        if len(shared_authorities) != 1:
            findings.append("required roles did not report one shared authority peer id")
        elif require_authority_participant and next(iter(shared_authorities)) not in expected_peer_ids:
            findings.append("shared authority peer id is not a participating required peer")

    proven = not findings
    return {
        "schemaVersion": 1,
        "configured": True,
        "proven": proven,
        "requiredRoleCount": len(normalized),
        "authorityObserved": authority_count == len(normalized) and proven,
        "dynamicCaptureRoleCount": actual_dynamic_capture_count,
        "roles": normalized,
        "findings": sorted(set(findings)),
        "truthBoundary": truth_boundary,
    }

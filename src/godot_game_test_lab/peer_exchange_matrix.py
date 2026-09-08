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
    if not isinstance(truth_boundary, str) or not truth_boundary.strip():
        _fail("peer-exchange truth boundary must be non-empty")

    normalized: list[dict[str, Any]] = []
    seen_role_ids: set[str] = set()
    session_values: dict[str, str] = {}
    local_peer_ids: dict[str, int] = {}
    observed_peer_ids: dict[str, list[int]] = {}
    authority_peer_ids: dict[str, int] = {}

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
                "dynamicRequiredMetadataCaptured": bool(
                    role.get("dynamicRequiredMetadataCaptured", False)
                ),
                "reservedAssertionsAccepted": bool(
                    role.get("reservedAssertionsAccepted", True)
                ),
            }
        )

    findings: list[str] = []
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
        "dynamicCaptureRoleCount": dynamic_capture_role_count,
        "roles": normalized,
        "findings": sorted(set(findings)),
        "truthBoundary": truth_boundary.strip(),
    }

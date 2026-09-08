from __future__ import annotations

from pathlib import Path
from typing import Any

from .attended_multiplayer_common import is_record, load_json_bytes, safe_id

SOURCE_RECEIPT_NAME = "authority-peer-exchange-lifecycle.json"
_MAX_ROLES = 8
_MAX_SESSION_BYTES = 256
_EXPECTED_PHASES = ("single", "reciprocal", "departure", "reconnect")


class AuthorityPeerExchangeSourceError(ValueError):
    """Raised when retained authority peer-exchange source evidence is inadmissible."""


def _fail(message: str) -> None:
    raise AuthorityPeerExchangeSourceError(message)


def _bounded_session(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value.encode("utf-8")) > _MAX_SESSION_BYTES
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        _fail(f"{label} must be a bounded non-empty single-line session id")
    return value


def _positive_peer_id(value: object, label: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > 2**31 - 1
    ):
        _fail(f"{label} must be a positive peer id")
    return value


def _normalize_role(raw: object, *, label: str) -> dict[str, Any]:
    if not is_record(raw):
        _fail(f"{label} must be an object")
    role = dict(raw)
    if set(role) != {"id", "sessionId", "localPeerId", "observedPeerIds"}:
        _fail(f"{label} has unexpected fields")
    role_id = safe_id(role.get("id"), "AUTHORITY_PEER_EXCHANGE_ROLE_ID_INVALID")
    session_id = _bounded_session(role.get("sessionId"), f"{label}.sessionId")
    local_peer_id = _positive_peer_id(role.get("localPeerId"), f"{label}.localPeerId")
    observed_raw = role.get("observedPeerIds")
    if not isinstance(observed_raw, list) or len(observed_raw) > 32:
        _fail(f"{label}.observedPeerIds must be a bounded array")
    observed = [
        _positive_peer_id(value, f"{label}.observedPeerIds") for value in observed_raw
    ]
    if len(set(observed)) != len(observed):
        _fail(f"{label}.observedPeerIds contains duplicates")
    if local_peer_id in observed:
        _fail(f"{label}.observedPeerIds contains the local peer")
    return {
        "id": role_id,
        "sessionId": session_id,
        "localPeerId": local_peer_id,
        "observedPeerIds": observed,
    }


def _normalize_phase(raw: object, *, expected_id: str) -> list[dict[str, Any]]:
    if not is_record(raw):
        _fail(f"authority peer exchange phase {expected_id} must be an object")
    phase = dict(raw)
    if set(phase) != {"id", "roles"} or phase.get("id") != expected_id:
        _fail(f"authority peer exchange phase {expected_id} is invalid")
    roles_raw = phase.get("roles")
    if not isinstance(roles_raw, list) or not 1 <= len(roles_raw) <= _MAX_ROLES:
        _fail(f"authority peer exchange phase {expected_id} role inventory is invalid")
    roles = [
        _normalize_role(role, label=f"phase {expected_id} role {index}")
        for index, role in enumerate(roles_raw)
    ]
    ids = [role["id"] for role in roles]
    peers = [role["localPeerId"] for role in roles]
    if len(set(ids)) != len(ids):
        _fail(f"authority peer exchange phase {expected_id} role ids are duplicated")
    if len(set(peers)) != len(peers):
        _fail(f"authority peer exchange phase {expected_id} local peer ids are duplicated")
    sessions = {role["sessionId"] for role in roles}
    if len(sessions) != 1:
        _fail(f"authority peer exchange phase {expected_id} sessions disagree")
    return roles


def _assert_complete_reciprocal(roles: list[dict[str, Any]], *, label: str) -> None:
    if len(roles) < 2:
        _fail(f"{label} requires at least two roles")
    expected = {role["localPeerId"] for role in roles}
    for role in roles:
        observed = set(role["observedPeerIds"])
        required = expected - {role["localPeerId"]}
        if observed != required:
            _fail(f"{label} is not complete reciprocal peer observation")


def verify_authority_peer_exchange_source(path: Path) -> dict[str, Any]:
    receipt, _bytes, receipt_path = load_json_bytes(path, "AUTHORITY_PEER_EXCHANGE_SOURCE")
    if receipt_path.name != SOURCE_RECEIPT_NAME:
        _fail(f"authority peer exchange source must be named {SOURCE_RECEIPT_NAME}")
    expected_fields = {
        "schemaVersion",
        "kind",
        "gameId",
        "authority",
        "protocol",
        "sessionId",
        "departedRoleId",
        "phases",
        "privacy",
        "authoritySafety",
        "truthBoundary",
    }
    if set(receipt) != expected_fields:
        _fail("authority peer exchange source has unexpected top-level fields")
    if receipt.get("schemaVersion") != "2.0":
        _fail("authority peer exchange source schema is invalid")
    if receipt.get("kind") != "evavo-authority-peer-exchange-lifecycle":
        _fail("authority peer exchange source kind is invalid")
    if receipt.get("authority") != "GalacticCycleRoom":
        _fail("authority peer exchange source authority is invalid")
    if receipt.get("protocol") != "galactic-cycle.v1":
        _fail("authority peer exchange source protocol is invalid")
    game_id = safe_id(receipt.get("gameId"), "AUTHORITY_PEER_EXCHANGE_GAME_ID_INVALID")
    session_id = _bounded_session(receipt.get("sessionId"), "authority source sessionId")
    departed_role_id = safe_id(
        receipt.get("departedRoleId"), "AUTHORITY_PEER_EXCHANGE_DEPARTED_ROLE_ID_INVALID"
    )

    privacy = receipt.get("privacy")
    if not is_record(privacy) or set(privacy) != {
        "rawPlayerIdsTransmitted",
        "runtimeSessionIdsTransmitted",
        "credentialsTransmitted",
    }:
        _fail("authority peer exchange privacy receipt is invalid")
    if any(privacy.get(key) is not False for key in privacy):
        _fail("authority peer exchange privacy boundary was not preserved")

    safety = receipt.get("authoritySafety")
    if not is_record(safety) or set(safety) != {
        "supersededSocketRetired",
        "staleSocketSendRejected",
        "staleSocketMessageRejected",
    }:
        _fail("authority peer exchange safety receipt is invalid")
    if any(safety.get(key) is not True for key in safety):
        _fail("authority peer exchange stale-socket safety was not proven")

    truth = receipt.get("truthBoundary")
    if (
        not isinstance(truth, str)
        or truth != truth.strip()
        or not truth
        or len(truth.encode("utf-8")) > 2048
        or any(character in truth for character in ("\x00", "\r"))
    ):
        _fail("authority peer exchange truth boundary is invalid")

    phases_raw = receipt.get("phases")
    if not isinstance(phases_raw, list) or len(phases_raw) != len(_EXPECTED_PHASES):
        _fail("authority peer exchange phase inventory is invalid")
    phases = {
        phase_id: _normalize_phase(phases_raw[index], expected_id=phase_id)
        for index, phase_id in enumerate(_EXPECTED_PHASES)
    }

    if len(phases["single"]) != 1 or phases["single"][0]["observedPeerIds"] != []:
        _fail("authority peer exchange single phase is invalid")
    _assert_complete_reciprocal(phases["reciprocal"], label="reciprocal phase")
    _assert_complete_reciprocal(phases["reconnect"], label="reconnect phase")

    reciprocal_by_id = {role["id"]: role for role in phases["reciprocal"]}
    reconnect_by_id = {role["id"]: role for role in phases["reconnect"]}
    if reciprocal_by_id != reconnect_by_id:
        _fail("authority peer exchange reconnect did not restore reciprocal role evidence")
    if departed_role_id not in reciprocal_by_id:
        _fail("authority peer exchange departed role was not present before departure")

    departure = phases["departure"]
    expected_departure_ids = set(reciprocal_by_id) - {departed_role_id}
    if {role["id"] for role in departure} != expected_departure_ids:
        _fail("authority peer exchange departure phase role inventory is invalid")
    expected_departure_peers = {role["localPeerId"] for role in departure}
    for role in departure:
        if set(role["observedPeerIds"]) != expected_departure_peers - {role["localPeerId"]}:
            _fail("authority peer exchange departure did not revoke the departed peer")

    for phase_id, roles in phases.items():
        if any(role["sessionId"] != session_id for role in roles):
            _fail(f"authority peer exchange phase {phase_id} session disagrees with receipt")

    return {
        "schemaVersion": 1,
        "sourceBound": True,
        "gameId": game_id,
        "sessionId": session_id,
        "requiredRoleCount": len(phases["reconnect"]),
        "roles": phases["reconnect"],
        "departedRoleId": departed_role_id,
        "authoritySafety": dict(safety),
        "truthBoundary": truth,
    }

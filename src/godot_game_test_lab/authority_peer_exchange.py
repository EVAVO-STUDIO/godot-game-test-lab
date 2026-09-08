from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .attended_multiplayer_common import (
    AttendedMultiplayerError,
    assert_no_symlink_chain,
    load_json_bytes,
)

_MAX_ROLES = 32
_MAX_SESSION_BYTES = 256
_MAX_LABEL_BYTES = 64
_MAX_RECEIPT_BYTES = 128 * 1024
_PHASES = ("single", "reciprocal", "departure", "reconnect")
_AUTHORITY_SAFETY_KEYS = {
    "supersededSocketRetired",
    "staleSocketSendRejected",
}
_V1_FIELDS = {
    "schemaVersion",
    "kind",
    "gameId",
    "authority",
    "protocol",
    "sessionId",
    "departedRoleId",
    "phases",
    "privacy",
    "truthBoundary",
}
_V2_FIELDS = _V1_FIELDS | {"authoritySafety"}


class AuthorityPeerExchangeError(ValueError):
    """Raised when an authority peer-exchange receipt is inadmissible."""


def _fail(message: str) -> None:
    raise AuthorityPeerExchangeError(message)


def _bounded_text(value: object, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value.encode("utf-8")) > maximum
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        _fail(f"{label} must be bounded non-empty single-line text")
    return value


def _peer_id(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 2**31 - 1:
        _fail(f"{label} must be a positive peer id")
    return value


def _role_map(phase: dict[str, Any], session_id: str) -> dict[str, dict[str, Any]]:
    raw_roles = phase.get("roles")
    if not isinstance(raw_roles, list) or not 1 <= len(raw_roles) <= _MAX_ROLES:
        _fail(f"phase {phase.get('id')} has an invalid role inventory")
    result: dict[str, dict[str, Any]] = {}
    peer_ids: set[int] = set()
    for raw in raw_roles:
        if not isinstance(raw, dict) or set(raw) != {"id", "sessionId", "localPeerId", "observedPeerIds"}:
            _fail(f"phase {phase.get('id')} has an invalid role record")
        role_id = _bounded_text(raw.get("id"), "role id", _MAX_LABEL_BYTES)
        if role_id in result:
            _fail(f"phase {phase.get('id')} duplicates role {role_id}")
        if _bounded_text(raw.get("sessionId"), f"role {role_id} session", _MAX_SESSION_BYTES) != session_id:
            _fail(f"role {role_id} does not report the shared session")
        local_peer = _peer_id(raw.get("localPeerId"), f"role {role_id} local peer")
        if local_peer in peer_ids:
            _fail(f"phase {phase.get('id')} duplicates local peer ids")
        peer_ids.add(local_peer)
        observed_raw = raw.get("observedPeerIds")
        if not isinstance(observed_raw, list) or len(observed_raw) > _MAX_ROLES - 1:
            _fail(f"role {role_id} observed peer ids are invalid")
        observed = [_peer_id(value, f"role {role_id} observed peer") for value in observed_raw]
        if len(set(observed)) != len(observed) or local_peer in observed:
            _fail(f"role {role_id} observed peer ids are ambiguous")
        result[role_id] = {
            "id": role_id,
            "sessionId": session_id,
            "localPeerId": local_peer,
            "observedPeerIds": observed,
        }
    return result


def _require_reciprocal(roles: dict[str, dict[str, Any]], label: str) -> None:
    expected = {int(role["localPeerId"]) for role in roles.values()}
    for role in roles.values():
        local_peer = int(role["localPeerId"])
        if set(role["observedPeerIds"]) != expected - {local_peer}:
            _fail(f"{label} role {role['id']} does not report the exact reciprocal peer set")


def _peer_mapping(roles: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {role_id: int(role["localPeerId"]) for role_id, role in roles.items()}


def _load_receipt(receipt_path: Path) -> tuple[dict[str, Any], int]:
    try:
        requested = assert_no_symlink_chain(receipt_path)
        resolved = requested.resolve(strict=True)
        stat = resolved.stat()
    except (OSError, AttendedMultiplayerError) as error:
        raise AuthorityPeerExchangeError("authority peer-exchange receipt is unreadable") from error
    if not resolved.is_file() or resolved.is_symlink() or stat.st_size < 2 or stat.st_size > _MAX_RECEIPT_BYTES:
        _fail("authority peer-exchange receipt size is invalid")
    try:
        raw, payload, loaded = load_json_bytes(resolved, "AUTHORITY_PEER_EXCHANGE")
    except AttendedMultiplayerError as error:
        message = str(error)
        if "JSON_INVALID" in message or "BOM_REJECTED" in message:
            raise AuthorityPeerExchangeError("authority peer-exchange receipt encoding is invalid") from error
        raise AuthorityPeerExchangeError("authority peer-exchange receipt is unreadable") from error
    if loaded != resolved or len(payload) != stat.st_size:
        _fail("authority peer-exchange receipt changed during verification")
    return raw, stat.st_size


def _receipt_schema(raw: dict[str, Any]) -> tuple[int, bool]:
    schema = raw.get("schemaVersion")
    if schema == "1.0":
        if set(raw) != _V1_FIELDS:
            _fail("authority peer-exchange receipt has unexpected fields")
        return 1, False
    if schema == "2.0":
        if set(raw) != _V2_FIELDS:
            _fail("authority peer-exchange receipt has unexpected fields")
        safety = raw.get("authoritySafety")
        if not isinstance(safety, dict) or set(safety) != _AUTHORITY_SAFETY_KEYS:
            _fail("authority peer-exchange authority safety statement is invalid")
        if any(type(safety[key]) is not bool for key in _AUTHORITY_SAFETY_KEYS):
            _fail("authority peer-exchange authority safety values must be booleans")
        if any(safety[key] is not True for key in _AUTHORITY_SAFETY_KEYS):
            _fail("authority peer-exchange receipt does not prove stale-socket authority retirement")
        return 2, True
    _fail("authority peer-exchange receipt schema is unsupported")
    raise AssertionError("unreachable")


def verify_authority_peer_exchange(receipt_path: Path) -> dict[str, Any]:
    raw, receipt_bytes = _load_receipt(receipt_path)
    receipt_schema, authority_safety_proven = _receipt_schema(raw)
    if raw.get("kind") != "evavo-authority-peer-exchange-lifecycle":
        _fail("authority peer-exchange receipt schema is unsupported")

    game_id = _bounded_text(raw.get("gameId"), "game id", _MAX_LABEL_BYTES)
    authority = _bounded_text(raw.get("authority"), "authority", _MAX_LABEL_BYTES)
    protocol = _bounded_text(raw.get("protocol"), "protocol", _MAX_LABEL_BYTES)
    session_id = _bounded_text(raw.get("sessionId"), "session id", _MAX_SESSION_BYTES)
    departed_role = _bounded_text(raw.get("departedRoleId"), "departed role id", _MAX_LABEL_BYTES)
    _bounded_text(raw.get("truthBoundary"), "truth boundary", 1024)

    privacy = raw.get("privacy")
    privacy_keys = {
        "rawPlayerIdsTransmitted",
        "runtimeSessionIdsTransmitted",
        "credentialsTransmitted",
    }
    if not isinstance(privacy, dict) or set(privacy) != privacy_keys:
        _fail("authority peer-exchange privacy statement is invalid")
    if any(type(privacy[key]) is not bool for key in privacy_keys):
        _fail("authority peer-exchange privacy values must be booleans")
    if any(privacy[key] is not False for key in privacy_keys):
        _fail("authority peer-exchange receipt reports identity or credential leakage")

    phases = raw.get("phases")
    if not isinstance(phases, list) or len(phases) != len(_PHASES):
        _fail("authority peer-exchange lifecycle must contain four phases")
    by_id: dict[str, dict[str, Any]] = {}
    encountered: list[str] = []
    for raw_phase in phases:
        if not isinstance(raw_phase, dict) or set(raw_phase) != {"id", "roles"}:
            _fail("authority peer-exchange phase is invalid")
        phase_id = raw_phase.get("id")
        if phase_id not in _PHASES or phase_id in by_id:
            _fail("authority peer-exchange phase ids are invalid")
        encountered.append(str(phase_id))
        by_id[str(phase_id)] = _role_map(raw_phase, session_id)
    if tuple(encountered) != _PHASES:
        _fail("authority peer-exchange phases are out of order")

    single = by_id["single"]
    reciprocal = by_id["reciprocal"]
    departure = by_id["departure"]
    reconnect = by_id["reconnect"]
    if len(single) != 1:
        _fail("single phase must contain exactly one role")
    only_single = next(iter(single.values()))
    survivor_role = str(only_single["id"])
    if only_single["observedPeerIds"]:
        _fail("single phase must not observe another peer")
    if not 2 <= len(reciprocal) <= _MAX_ROLES:
        _fail("reciprocal phase must contain at least two roles")
    if survivor_role not in reciprocal:
        _fail("single phase role is not present in reciprocal phase")
    _require_reciprocal(reciprocal, "reciprocal phase")
    if departed_role not in reciprocal:
        _fail("departed role was not present in reciprocal phase")
    if departed_role == survivor_role:
        _fail("departed role cannot be the single-phase survivor role")
    if set(departure) != set(reciprocal) - {departed_role}:
        _fail("departure phase does not remove exactly the departed role")
    _require_reciprocal(departure, "departure phase")
    if set(reconnect) != set(reciprocal):
        _fail("reconnect phase does not restore the reciprocal role inventory")
    _require_reciprocal(reconnect, "reconnect phase")

    reciprocal_mapping = _peer_mapping(reciprocal)
    reconnect_mapping = _peer_mapping(reconnect)
    if reconnect_mapping != reciprocal_mapping:
        _fail("reconnect phase changed the reciprocal peer mapping")
    for role_id, role in departure.items():
        if int(role["localPeerId"]) != reciprocal_mapping[role_id]:
            _fail(f"departure phase changed peer id for surviving role {role_id}")
    if int(only_single["localPeerId"]) != reciprocal_mapping[survivor_role]:
        _fail("single phase survivor peer id disagrees with reciprocal mapping")

    return {
        "schemaVersion": 1,
        "receiptSchemaVersion": receipt_schema,
        "proven": True,
        "authorityLifecycleProven": True,
        "reciprocalPeerSemanticsProven": True,
        "departureRevocationProven": True,
        "reconnectPeerSemanticsProven": True,
        "transportProven": False,
        "browserTransportProven": False,
        "gameId": game_id,
        "authority": authority,
        "protocol": protocol,
        "sessionId": session_id,
        "requiredRoleCount": len(reciprocal),
        "departedRoleId": departed_role,
        "survivorRoleId": survivor_role,
        "phases": list(_PHASES),
        "privacySafe": True,
        "stablePeerMapping": True,
        "authoritySafetyProven": authority_safety_proven,
        "receiptBytes": receipt_bytes,
        "truthBoundary": (
            "This proves the retained server-authority lifecycle receipt has one shared session, "
            "exact reciprocal peer observation, departure revocation, reconnect restoration with "
            "a stable ephemeral peer mapping, and no declared raw identity or credential "
            "transmission. Receipt v2 additionally binds superseded-socket retirement and stale "
            "socket send rejection. It does not by itself prove a browser or native client "
            "traversed the production transport path."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify an EVAVO authority peer-exchange lifecycle receipt.")
    parser.add_argument("receipt", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_authority_peer_exchange(args.receipt)
    except AuthorityPeerExchangeError as error:
        print(f"EVAVO_AUTHORITY_PEER_EXCHANGE=FAIL reason={error}")
        return 1
    print(json.dumps(result, sort_keys=True))
    print(f"EVAVO_AUTHORITY_PEER_EXCHANGE=PASS roles={result['requiredRoleCount']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

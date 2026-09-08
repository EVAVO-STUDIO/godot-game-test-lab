from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .attended_multiplayer_common import AttendedMultiplayerError, assert_no_symlink_chain, load_json_bytes

_MAX_RECEIPT_BYTES = 256 * 1024
_MAX_ROLES = 8
_MAX_TEXT_BYTES = 256
_PHASES = ("single", "reciprocal", "departure", "reconnect")
_CHANNELS = {"development", "preview", "production"}
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_CAPABILITIES = {
    "authoritative-room-presence",
    "stale-socket-send-rejection",
    "source-bound-deployment",
}
_EXPECTED_FIELDS = {
    "schemaVersion",
    "kind",
    "gameId",
    "protocol",
    "roomId",
    "phases",
    "transportProven",
    "browserTransportProven",
    "privacy",
    "truthBoundary",
    "runtimeOrigin",
    "authorityOrigin",
    "authoritySourceSha",
    "releaseId",
    "releaseChannel",
    "runtimeSessionIssuerProven",
    "boundTicketAdmissionProven",
    "reconnectIdentityContinuityProven",
    "runtimeSessionRotationProven",
    "authorityCapabilities",
}
_ROLE_FIELDS = {"id", "sessionId", "localPeerId", "observedPeerIds", "connectedCount"}
_PRIVACY_FIELDS = {
    "rawPlayerIdsRetained",
    "runtimeSessionIdsRetained",
    "ticketsRetained",
    "installationIdsRetained",
}


class RuntimeAuthorityPeerExchangeError(ValueError):
    """Raised when runtime-to-authority transport evidence is inadmissible."""


def _fail(message: str) -> None:
    raise RuntimeAuthorityPeerExchangeError(message)


def _bounded_text(value: object, label: str, maximum: int = _MAX_TEXT_BYTES) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value.encode("utf-8")) > maximum
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        _fail(f"{label} must be bounded non-empty single-line text")
    return value


def _literal_bool(value: object, label: str, expected: bool) -> None:
    if type(value) is not bool or value is not expected:
        _fail(f"{label} must be {str(expected).lower()}")


def _peer_id(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1024:
        _fail(f"{label} must be a bounded positive peer id")
    return value


def _origin(value: object, label: str, websocket: bool) -> str:
    text = _bounded_text(value, label, 2048)
    try:
        parsed = urlsplit(text)
    except ValueError as error:
        raise RuntimeAuthorityPeerExchangeError(f"{label} is invalid") from error
    expected = {"ws", "wss"} if websocket else {"http", "https"}
    if (
        parsed.scheme not in expected
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or text.rstrip("/") != f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    ):
        _fail(f"{label} must be a credential-free root origin")
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    secure_scheme = "wss" if websocket else "https"
    if parsed.scheme != secure_scheme and not loopback:
        _fail(f"{label} must use {secure_scheme} outside loopback development")
    return text.rstrip("/")


def _role_map(phase: dict[str, Any], session_id: str) -> dict[str, dict[str, Any]]:
    raw_roles = phase.get("roles")
    if not isinstance(raw_roles, list) or not 1 <= len(raw_roles) <= _MAX_ROLES:
        _fail(f"phase {phase.get('id')} has an invalid role inventory")
    result: dict[str, dict[str, Any]] = {}
    peers: set[int] = set()
    for raw in raw_roles:
        if not isinstance(raw, dict) or set(raw) != _ROLE_FIELDS:
            _fail(f"phase {phase.get('id')} has an invalid role record")
        role_id = _bounded_text(raw.get("id"), "role id", 64)
        if role_id in result:
            _fail(f"phase {phase.get('id')} duplicates role {role_id}")
        role_session = _bounded_text(raw.get("sessionId"), f"role {role_id} session", 64)
        if role_session != session_id:
            _fail(f"role {role_id} does not report the shared room session")
        local_peer = _peer_id(raw.get("localPeerId"), f"role {role_id} local peer")
        if local_peer in peers:
            _fail(f"phase {phase.get('id')} duplicates local peer ids")
        peers.add(local_peer)
        connected_count = raw.get("connectedCount")
        if (
            not isinstance(connected_count, int)
            or isinstance(connected_count, bool)
            or not 1 <= connected_count <= _MAX_ROLES
        ):
            _fail(f"role {role_id} connected count is invalid")
        observed_raw = raw.get("observedPeerIds")
        if not isinstance(observed_raw, list) or len(observed_raw) > _MAX_ROLES - 1:
            _fail(f"role {role_id} observed peer ids are invalid")
        observed = [_peer_id(value, f"role {role_id} observed peer") for value in observed_raw]
        if len(set(observed)) != len(observed) or local_peer in observed:
            _fail(f"role {role_id} observed peer ids are ambiguous")
        result[role_id] = {
            "id": role_id,
            "sessionId": role_session,
            "localPeerId": local_peer,
            "observedPeerIds": observed,
            "connectedCount": connected_count,
        }
    return result


def _require_complete_room(roles: dict[str, dict[str, Any]], label: str) -> None:
    if not roles:
        _fail(f"{label} phase is empty")
    expected_count = len(roles)
    expected_peers = {int(role["localPeerId"]) for role in roles.values()}
    if expected_peers != set(range(1, expected_count + 1)):
        _fail(f"{label} phase local peer ids do not cover the complete ephemeral room mapping")
    for role in roles.values():
        if int(role["connectedCount"]) != expected_count:
            _fail(f"{label} phase does not cover the complete connected room")
        local_peer = int(role["localPeerId"])
        if set(role["observedPeerIds"]) != expected_peers - {local_peer}:
            _fail(f"{label} phase does not contain exact reciprocal peer observation")


def _load_receipt(path: Path) -> tuple[dict[str, Any], int]:
    try:
        requested = assert_no_symlink_chain(path)
        resolved = requested.resolve(strict=True)
        stat = resolved.stat()
    except (OSError, AttendedMultiplayerError) as error:
        raise RuntimeAuthorityPeerExchangeError("runtime authority peer-exchange receipt is unreadable") from error
    if not resolved.is_file() or resolved.is_symlink() or not 2 <= stat.st_size <= _MAX_RECEIPT_BYTES:
        _fail("runtime authority peer-exchange receipt size is invalid")
    try:
        raw, payload, loaded = load_json_bytes(resolved, "RUNTIME_AUTHORITY_PEER_EXCHANGE")
    except AttendedMultiplayerError as error:
        raise RuntimeAuthorityPeerExchangeError("runtime authority peer-exchange receipt encoding is invalid") from error
    if loaded != resolved or len(payload) != stat.st_size:
        _fail("runtime authority peer-exchange receipt changed during verification")
    return raw, stat.st_size


def verify_runtime_authority_peer_exchange(receipt_path: Path) -> dict[str, Any]:
    raw, receipt_bytes = _load_receipt(receipt_path)
    if set(raw) != _EXPECTED_FIELDS:
        _fail("runtime authority peer-exchange receipt has unexpected fields")
    if raw.get("schemaVersion") != 1 or raw.get("kind") != "evavo-runtime-authority-peer-exchange-transport":
        _fail("runtime authority peer-exchange receipt schema is unsupported")
    game_id = _bounded_text(raw.get("gameId"), "game id", 96)
    if game_id != "galactic-cycle-online":
        _fail("runtime authority peer-exchange game id is unsupported")
    protocol = _bounded_text(raw.get("protocol"), "protocol", 96)
    if protocol != "galactic-cycle.v1":
        _fail("runtime authority peer-exchange protocol is unsupported")
    room_id = _bounded_text(raw.get("roomId"), "room id", 64)
    release_id = _bounded_text(raw.get("releaseId"), "release id", 128)
    release_channel = _bounded_text(raw.get("releaseChannel"), "release channel", 32)
    if release_channel not in _CHANNELS:
        _fail("runtime authority peer-exchange release channel is invalid")
    runtime_origin = _origin(raw.get("runtimeOrigin"), "runtime origin", websocket=False)
    authority_origin = _origin(raw.get("authorityOrigin"), "authority origin", websocket=True)
    if urlsplit(runtime_origin).netloc == urlsplit(authority_origin).netloc:
        _fail("runtime and game authority origins must remain distinct")
    authority_source_sha = raw.get("authoritySourceSha")
    if not isinstance(authority_source_sha, str) or _SHA_RE.fullmatch(authority_source_sha) is None:
        _fail("runtime authority peer-exchange authority source SHA is invalid")

    for field in (
        "transportProven",
        "runtimeSessionIssuerProven",
        "boundTicketAdmissionProven",
        "reconnectIdentityContinuityProven",
        "runtimeSessionRotationProven",
    ):
        _literal_bool(raw.get(field), field, True)
    _literal_bool(raw.get("browserTransportProven"), "browserTransportProven", False)

    privacy = raw.get("privacy")
    if not isinstance(privacy, dict) or set(privacy) != _PRIVACY_FIELDS:
        _fail("runtime authority peer-exchange privacy statement is invalid")
    for field in _PRIVACY_FIELDS:
        _literal_bool(privacy.get(field), f"privacy.{field}", False)

    capabilities = raw.get("authorityCapabilities")
    if not isinstance(capabilities, list) or len(capabilities) != len(_REQUIRED_CAPABILITIES):
        _fail("runtime authority peer-exchange capability evidence is invalid")
    normalized_capabilities = [_bounded_text(value, "authority capability", 96) for value in capabilities]
    if len(set(normalized_capabilities)) != len(normalized_capabilities) or set(normalized_capabilities) != _REQUIRED_CAPABILITIES:
        _fail("runtime authority peer-exchange required capabilities are missing or ambiguous")

    phases = raw.get("phases")
    if not isinstance(phases, list) or len(phases) != len(_PHASES):
        _fail("runtime authority peer-exchange lifecycle must contain four phases")
    by_id: dict[str, dict[str, dict[str, Any]]] = {}
    encountered: list[str] = []
    for raw_phase in phases:
        if not isinstance(raw_phase, dict) or set(raw_phase) != {"id", "roles"}:
            _fail("runtime authority peer-exchange phase is invalid")
        phase_id = raw_phase.get("id")
        if phase_id not in _PHASES or phase_id in by_id:
            _fail("runtime authority peer-exchange phase ids are invalid")
        encountered.append(str(phase_id))
        by_id[str(phase_id)] = _role_map(raw_phase, room_id)
    if tuple(encountered) != _PHASES:
        _fail("runtime authority peer-exchange phases are out of order")

    single = by_id["single"]
    reciprocal = by_id["reciprocal"]
    departure = by_id["departure"]
    reconnect = by_id["reconnect"]
    if len(single) != 1:
        _fail("single phase must contain exactly one role")
    survivor_role = next(iter(single))
    _require_complete_room(single, "single")
    if len(reciprocal) < 2:
        _fail("reciprocal phase must contain at least two roles")
    _require_complete_room(reciprocal, "reciprocal")
    if survivor_role not in reciprocal:
        _fail("single-phase survivor is absent from reciprocal phase")
    if int(single[survivor_role]["localPeerId"]) != int(reciprocal[survivor_role]["localPeerId"]):
        _fail("single-phase survivor peer id changed before reciprocal phase")

    departed_roles = set(reciprocal) - set(departure)
    if len(departed_roles) != 1 or set(departure) != set(reciprocal) - departed_roles:
        _fail("departure phase must remove exactly one role")
    departed_role = next(iter(departed_roles))
    if departed_role == survivor_role:
        _fail("departure phase removed the single-phase survivor")
    _require_complete_room(departure, "departure")
    for role_id, role in departure.items():
        if int(role["localPeerId"]) != int(reciprocal[role_id]["localPeerId"]):
            _fail(f"departure phase changed peer id for surviving role {role_id}")

    if set(reconnect) != set(reciprocal):
        _fail("reconnect phase did not restore the reciprocal role inventory")
    _require_complete_room(reconnect, "reconnect")
    for role_id, before in reciprocal.items():
        if int(reconnect[role_id]["localPeerId"]) != int(before["localPeerId"]):
            _fail("reconnect phase changed the stable ephemeral peer mapping")

    truth_boundary = _bounded_text(raw.get("truthBoundary"), "truth boundary", 2048)
    if "does not prove" not in truth_boundary.lower() or "browser" not in truth_boundary.lower():
        _fail("runtime authority peer-exchange truth boundary must preserve the browser distinction")

    return {
        "schemaVersion": 1,
        "proven": True,
        "transportProven": True,
        "browserTransportProven": False,
        "runtimeSessionIssuerProven": True,
        "boundTicketAdmissionProven": True,
        "reconnectIdentityContinuityProven": True,
        "runtimeSessionRotationProven": True,
        "completeRoomCoverageProven": True,
        "deploymentSourceBound": True,
        "privacySafe": True,
        "gameId": game_id,
        "protocol": protocol,
        "roomId": room_id,
        "releaseId": release_id,
        "releaseChannel": release_channel,
        "runtimeOrigin": runtime_origin,
        "authorityOrigin": authority_origin,
        "authoritySourceSha": authority_source_sha,
        "requiredRoleCount": len(reciprocal),
        "departedRoleId": departed_role,
        "survivorRoleId": survivor_role,
        "receiptBytes": receipt_bytes,
        "authorityCapabilities": sorted(normalized_capabilities),
        "truthBoundary": (
            "This proves a retained EVAVO runtime-to-authority WebSocket lifecycle receipt has runtime-issued "
            "bound admission, exact deployed-authority source provenance, complete-room reciprocal presence, "
            "departure revocation, reconnect identity continuity with runtime-session rotation, and privacy-safe "
            "retained evidence. It does not prove that a browser-hosted Godot player traversed the production path."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify EVAVO runtime-to-authority peer-exchange transport evidence.")
    parser.add_argument("receipt", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_runtime_authority_peer_exchange(args.receipt)
    except RuntimeAuthorityPeerExchangeError as error:
        print(f"EVAVO_RUNTIME_AUTHORITY_PEER_EXCHANGE_VERIFY=FAIL reason={error}")
        return 1
    print(json.dumps(result, sort_keys=True))
    print(f"EVAVO_RUNTIME_AUTHORITY_PEER_EXCHANGE_VERIFY=PASS roles={result['requiredRoleCount']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

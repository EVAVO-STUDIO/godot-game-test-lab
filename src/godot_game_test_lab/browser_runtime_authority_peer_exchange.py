from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from . import runtime_authority_peer_exchange as base

_MAX_BROWSER_VERSION_BYTES = 64
_EXPECTED_FIELDS = base._EXPECTED_FIELDS | {
    "browserEngine",
    "browserVersion",
    "browserParticipantContextCount",
    "browserIsolationContextCount",
    "browserNativeFetchProven",
    "browserNativeWebSocketProven",
    "browserHostileOriginRejectionProven",
}
_BROWSER_ENGINE = "chromium"
_PARTICIPANT_CONTEXT_COUNT = 2
_ISOLATION_CONTEXT_COUNT = 3


class BrowserRuntimeAuthorityPeerExchangeError(base.RuntimeAuthorityPeerExchangeError):
    """Raised when browser runtime-to-authority evidence is inadmissible."""


def _fail(message: str) -> None:
    raise BrowserRuntimeAuthorityPeerExchangeError(message)


def _literal_int(value: object, label: str, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        _fail(f"{label} must be {expected}")


def _verify_lifecycle(raw: dict[str, Any], room_id: str) -> tuple[int, str, str]:
    phases = raw.get("phases")
    if not isinstance(phases, list) or len(phases) != len(base._PHASES):
        _fail("browser runtime authority peer-exchange lifecycle must contain four phases")

    by_id: dict[str, dict[str, dict[str, Any]]] = {}
    encountered: list[str] = []
    for raw_phase in phases:
        if not isinstance(raw_phase, dict) or set(raw_phase) != {"id", "roles"}:
            _fail("browser runtime authority peer-exchange phase is invalid")
        phase_id = raw_phase.get("id")
        if phase_id not in base._PHASES or phase_id in by_id:
            _fail("browser runtime authority peer-exchange phase ids are invalid")
        encountered.append(str(phase_id))
        by_id[str(phase_id)] = base._role_map(raw_phase, room_id)
    if tuple(encountered) != base._PHASES:
        _fail("browser runtime authority peer-exchange phases are out of order")

    single = by_id["single"]
    reciprocal = by_id["reciprocal"]
    departure = by_id["departure"]
    reconnect = by_id["reconnect"]

    if len(single) != 1:
        _fail("single phase must contain exactly one role")
    survivor_role = next(iter(single))
    base._require_complete_room(single, "single")

    if len(reciprocal) != _PARTICIPANT_CONTEXT_COUNT:
        _fail("reciprocal phase must contain exactly two browser participant roles")
    base._require_complete_room(reciprocal, "reciprocal")
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
    base._require_complete_room(departure, "departure")
    for role_id, role in departure.items():
        if int(role["localPeerId"]) != int(reciprocal[role_id]["localPeerId"]):
            _fail(f"departure phase changed peer id for surviving role {role_id}")

    if set(reconnect) != set(reciprocal):
        _fail("reconnect phase did not restore the reciprocal role inventory")
    base._require_complete_room(reconnect, "reconnect")
    for role_id, before in reciprocal.items():
        if int(reconnect[role_id]["localPeerId"]) != int(before["localPeerId"]):
            _fail("reconnect phase changed the stable ephemeral peer mapping")

    return len(reciprocal), departed_role, survivor_role


def _verify(receipt_path: Path) -> dict[str, Any]:
    raw, receipt_bytes = base._load_receipt(receipt_path)
    if set(raw) != _EXPECTED_FIELDS:
        _fail("browser runtime authority peer-exchange receipt has unexpected fields")
    if raw.get("schemaVersion") != 1:
        _fail("browser runtime authority peer-exchange schema is unsupported")
    if raw.get("kind") != "evavo-browser-runtime-authority-peer-exchange-transport":
        _fail("browser runtime authority peer-exchange kind is unsupported")

    game_id = base._bounded_text(raw.get("gameId"), "game id", 96)
    if game_id != "galactic-cycle-online":
        _fail("browser runtime authority peer-exchange game id is unsupported")
    protocol = base._bounded_text(raw.get("protocol"), "protocol", 96)
    if protocol != "galactic-cycle.v1":
        _fail("browser runtime authority peer-exchange protocol is unsupported")
    room_id = base._bounded_text(raw.get("roomId"), "room id", 64)

    release_id = base._bounded_text(raw.get("releaseId"), "release id", 128)
    release_channel = base._bounded_text(raw.get("releaseChannel"), "release channel", 32)
    if release_channel not in base._CHANNELS:
        _fail("browser runtime authority peer-exchange release channel is invalid")

    runtime_origin = base._origin(raw.get("runtimeOrigin"), "runtime origin", websocket=False)
    authority_origin = base._origin(raw.get("authorityOrigin"), "authority origin", websocket=True)
    from urllib.parse import urlsplit

    if urlsplit(runtime_origin).netloc == urlsplit(authority_origin).netloc:
        _fail("runtime and game authority origins must remain distinct")

    authority_source_sha = raw.get("authoritySourceSha")
    if not isinstance(authority_source_sha, str) or base._SHA_RE.fullmatch(authority_source_sha) is None:
        _fail("browser runtime authority peer-exchange authority source SHA is invalid")

    for field in (
        "transportProven",
        "browserTransportProven",
        "runtimeSessionIssuerProven",
        "boundTicketAdmissionProven",
        "reconnectIdentityContinuityProven",
        "runtimeSessionRotationProven",
        "browserNativeFetchProven",
        "browserNativeWebSocketProven",
        "browserHostileOriginRejectionProven",
    ):
        base._literal_bool(raw.get(field), field, True)

    browser_engine = base._bounded_text(raw.get("browserEngine"), "browser engine", 32)
    if browser_engine != _BROWSER_ENGINE:
        _fail("browser runtime authority peer-exchange engine must be chromium")
    browser_version = base._bounded_text(
        raw.get("browserVersion"), "browser version", _MAX_BROWSER_VERSION_BYTES
    )
    _literal_int(
        raw.get("browserParticipantContextCount"),
        "browserParticipantContextCount",
        _PARTICIPANT_CONTEXT_COUNT,
    )
    _literal_int(
        raw.get("browserIsolationContextCount"),
        "browserIsolationContextCount",
        _ISOLATION_CONTEXT_COUNT,
    )

    privacy = raw.get("privacy")
    if not isinstance(privacy, dict) or set(privacy) != base._PRIVACY_FIELDS:
        _fail("browser runtime authority peer-exchange privacy statement is invalid")
    for field in base._PRIVACY_FIELDS:
        base._literal_bool(privacy.get(field), f"privacy.{field}", False)

    capabilities = raw.get("authorityCapabilities")
    if not isinstance(capabilities, list) or len(capabilities) != len(base._REQUIRED_CAPABILITIES):
        _fail("browser runtime authority peer-exchange capability evidence is invalid")
    normalized_capabilities = [
        base._bounded_text(value, "authority capability", 96) for value in capabilities
    ]
    if (
        len(set(normalized_capabilities)) != len(normalized_capabilities)
        or set(normalized_capabilities) != base._REQUIRED_CAPABILITIES
    ):
        _fail("browser runtime authority peer-exchange required capabilities are missing or ambiguous")

    required_role_count, departed_role, survivor_role = _verify_lifecycle(raw, room_id)
    if required_role_count != _PARTICIPANT_CONTEXT_COUNT:
        _fail("browser participant context count disagrees with reciprocal peer evidence")

    truth_boundary = base._bounded_text(raw.get("truthBoundary"), "truth boundary", 2048)
    lowered_boundary = truth_boundary.lower()
    if (
        "does not prove" not in lowered_boundary
        or "godot" not in lowered_boundary
        or "gameplay" not in lowered_boundary
        or "release" not in lowered_boundary
    ):
        _fail(
            "browser runtime authority peer-exchange truth boundary must preserve the Godot gameplay and release distinction"
        )

    return {
        "schemaVersion": 1,
        "proven": True,
        "transportProven": True,
        "browserTransportProven": True,
        "godotPlayerTransportProven": False,
        "browserNativeFetchProven": True,
        "browserNativeWebSocketProven": True,
        "browserOpaqueHostileOriginRejectionProven": True,
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
        "browserEngine": browser_engine,
        "browserVersion": browser_version,
        "browserParticipantContextCount": _PARTICIPANT_CONTEXT_COUNT,
        "browserIsolationContextCount": _ISOLATION_CONTEXT_COUNT,
        "requiredRoleCount": required_role_count,
        "departedRoleId": departed_role,
        "survivorRoleId": survivor_role,
        "receiptBytes": receipt_bytes,
        "authorityCapabilities": sorted(normalized_capabilities),
        "truthBoundary": (
            "This proves a retained Chromium browser-to-EVAVO-runtime-to-source-bound-authority "
            "multiplayer lifecycle using browser-native same-origin fetch and WebSocket APIs, "
            "including reciprocal presence, departure revocation, reconnect restoration, and an "
            "opaque hostile-origin rejection check. It does not prove a Godot web player consumed "
            "the session, rendered correctly, executed gameplay correctly, or is release-ready."
        ),
    }


def verify_browser_runtime_authority_peer_exchange(receipt_path: Path) -> dict[str, Any]:
    try:
        return _verify(receipt_path)
    except BrowserRuntimeAuthorityPeerExchangeError:
        raise
    except base.RuntimeAuthorityPeerExchangeError as error:
        raise BrowserRuntimeAuthorityPeerExchangeError(str(error)) from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify EVAVO Chromium browser runtime-to-authority peer-exchange evidence."
    )
    parser.add_argument("receipt", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_browser_runtime_authority_peer_exchange(args.receipt)
    except BrowserRuntimeAuthorityPeerExchangeError as error:
        print(f"EVAVO_BROWSER_RUNTIME_AUTHORITY_PEER_EXCHANGE_VERIFY=FAIL reason={error}")
        return 1
    print(
        "EVAVO_BROWSER_RUNTIME_AUTHORITY_PEER_EXCHANGE_VERIFY=PASS "
        f"roles={result['requiredRoleCount']} browser={result['browserEngine']} "
        f"authority_sha={result['authoritySourceSha']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

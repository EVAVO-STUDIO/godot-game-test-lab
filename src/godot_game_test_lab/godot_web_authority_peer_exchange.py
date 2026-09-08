from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .attended_multiplayer_common import AttendedMultiplayerError, assert_no_symlink_chain, load_json_bytes

_MAX_RECEIPT_BYTES = 256 * 1024
_MAX_TEXT_BYTES = 2048
_MAX_ROLES = 8
_CHANNELS = {"development", "preview", "production"}
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_EXPECTED_FIELDS = {
    "schemaVersion",
    "kind",
    "gameId",
    "releaseId",
    "releaseChannel",
    "runtimeOrigin",
    "authorityOrigin",
    "authoritySourceSha",
    "browserEngine",
    "browserVersion",
    "browserContextCount",
    "browserTransportProven",
    "browserLifecycleErrorsAbsentProven",
    "godotWebExportProven",
    "godotRuntimeRunningProven",
    "runtimeHandoffConsumedByGodot",
    "godotPeerEvidenceBridgeProven",
    "runtimeSessionIssuerProven",
    "boundTicketAdmissionProven",
    "mountedReleaseProven",
    "signedReleaseDescriptorEnvelopeProven",
    "reciprocalPeerObservationProven",
    "departureRevocationProven",
    "reconnectRestorationProven",
    "reconnectIdentityContinuityProven",
    "runtimeSessionRotationProven",
    "authorityPeerClaimedByClient",
    "roomId",
    "phases",
    "truthBoundary",
}
_TRUE_FIELDS = {
    "browserTransportProven",
    "browserLifecycleErrorsAbsentProven",
    "godotWebExportProven",
    "godotRuntimeRunningProven",
    "runtimeHandoffConsumedByGodot",
    "godotPeerEvidenceBridgeProven",
    "runtimeSessionIssuerProven",
    "boundTicketAdmissionProven",
    "mountedReleaseProven",
    "signedReleaseDescriptorEnvelopeProven",
    "reciprocalPeerObservationProven",
    "departureRevocationProven",
    "reconnectRestorationProven",
    "reconnectIdentityContinuityProven",
    "runtimeSessionRotationProven",
}
_ROLE_FIELDS = {"id", "sessionId", "localPeerId", "observedPeerIds"}
_PHASES = ("single", "reciprocal", "departure", "reconnect")
_FORBIDDEN_RETAINED_KEYS = {
    "playerId",
    "runtimeSessionId",
    "ticket",
    "installationId",
    "credentials",
    "accessToken",
    "refreshToken",
}


class GodotWebAuthorityPeerExchangeError(ValueError):
    """Raised when a Godot Web authority peer-exchange receipt is inadmissible."""


def _fail(message: str) -> None:
    raise GodotWebAuthorityPeerExchangeError(message)


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


def _origin(value: object, label: str, websocket: bool, channel: str) -> str:
    text = _bounded_text(value, label, 2048)
    try:
        parsed = urlsplit(text)
    except ValueError as error:
        raise GodotWebAuthorityPeerExchangeError(f"{label} is invalid") from error
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
    secure = "wss" if websocket else "https"
    if (channel != "development" or not loopback) and parsed.scheme != secure:
        _fail(f"{label} must use {secure} outside loopback development")
    return text.rstrip("/")


def _peer_id(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1024:
        _fail(f"{label} must be a bounded positive peer id")
    return value


def _roles(value: object, phase: str, room_id: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_ROLES:
        _fail(f"{phase} phase has an invalid role inventory")
    result: dict[str, dict[str, Any]] = {}
    peer_ids: set[int] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != _ROLE_FIELDS:
            _fail(f"{phase} phase has an invalid role record")
        role_id = _bounded_text(raw.get("id"), f"{phase} role id", 64)
        if role_id in result:
            _fail(f"{phase} phase duplicates role {role_id}")
        session_id = _bounded_text(raw.get("sessionId"), f"{phase} role session", 64)
        if session_id != room_id:
            _fail(f"{phase} role {role_id} disagrees on the shared room")
        local_peer = _peer_id(raw.get("localPeerId"), f"{phase} role {role_id} local peer")
        if local_peer in peer_ids:
            _fail(f"{phase} phase duplicates local peer ids")
        peer_ids.add(local_peer)
        observed_raw = raw.get("observedPeerIds")
        if not isinstance(observed_raw, list) or len(observed_raw) > _MAX_ROLES - 1:
            _fail(f"{phase} role {role_id} observed peer ids are invalid")
        observed = [_peer_id(entry, f"{phase} role {role_id} observed peer") for entry in observed_raw]
        if len(set(observed)) != len(observed) or local_peer in observed:
            _fail(f"{phase} role {role_id} observed peer ids are ambiguous")
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


def _scan_forbidden_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in _FORBIDDEN_RETAINED_KEYS:
                _fail(f"receipt retains forbidden private field {key}")
            _scan_forbidden_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _scan_forbidden_keys(nested)


def _load_receipt(path: Path) -> tuple[dict[str, Any], int]:
    try:
        requested = assert_no_symlink_chain(path)
        resolved = requested.resolve(strict=True)
        stat = resolved.stat()
    except (OSError, AttendedMultiplayerError) as error:
        raise GodotWebAuthorityPeerExchangeError("Godot Web peer-exchange receipt is unreadable") from error
    if not resolved.is_file() or resolved.is_symlink() or not 2 <= stat.st_size <= _MAX_RECEIPT_BYTES:
        _fail("Godot Web peer-exchange receipt size is invalid")
    try:
        raw, payload, loaded = load_json_bytes(resolved, "GODOT_WEB_AUTHORITY_PEER_EXCHANGE")
    except AttendedMultiplayerError as error:
        raise GodotWebAuthorityPeerExchangeError("Godot Web peer-exchange receipt encoding is invalid") from error
    if loaded != resolved or len(payload) != stat.st_size:
        _fail("Godot Web peer-exchange receipt changed during verification")
    return raw, stat.st_size


def verify_godot_web_authority_peer_exchange(receipt_path: Path) -> dict[str, Any]:
    raw, receipt_bytes = _load_receipt(receipt_path)
    if set(raw) != _EXPECTED_FIELDS:
        _fail("Godot Web peer-exchange receipt has unexpected fields")
    if raw.get("schemaVersion") != 1 or raw.get("kind") != "evavo-godot-web-authority-peer-exchange":
        _fail("Godot Web peer-exchange receipt schema is unsupported")
    _scan_forbidden_keys(raw)

    game_id = _bounded_text(raw.get("gameId"), "game id", 96)
    if game_id != "galactic-cycle-online":
        _fail("Godot Web peer-exchange game id is unsupported")
    release_id = _bounded_text(raw.get("releaseId"), "release id", 128)
    release_channel = _bounded_text(raw.get("releaseChannel"), "release channel", 32)
    if release_channel not in _CHANNELS:
        _fail("Godot Web peer-exchange release channel is invalid")
    room_id = _bounded_text(raw.get("roomId"), "room id", 64)
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", room_id) is None:
        _fail("Godot Web peer-exchange room id is invalid")

    runtime_origin = _origin(raw.get("runtimeOrigin"), "runtime origin", False, release_channel)
    authority_origin = _origin(raw.get("authorityOrigin"), "authority origin", True, release_channel)
    if urlsplit(runtime_origin).netloc == urlsplit(authority_origin).netloc:
        _fail("runtime and game authority origins must remain distinct")
    authority_source_sha = raw.get("authoritySourceSha")
    if not isinstance(authority_source_sha, str) or _SHA_RE.fullmatch(authority_source_sha) is None:
        _fail("Godot Web peer-exchange authority source SHA is invalid")

    browser_engine = _bounded_text(raw.get("browserEngine"), "browser engine", 32)
    if browser_engine != "chromium":
        _fail("Godot Web peer-exchange browser engine must be chromium")
    browser_version = _bounded_text(raw.get("browserVersion"), "browser version", 80)
    if raw.get("browserContextCount") != 2 or isinstance(raw.get("browserContextCount"), bool):
        _fail("Godot Web peer-exchange must use exactly two isolated browser contexts")

    for field in _TRUE_FIELDS:
        _literal_bool(raw.get(field), field, True)
    _literal_bool(raw.get("authorityPeerClaimedByClient"), "authorityPeerClaimedByClient", False)

    phases = raw.get("phases")
    if not isinstance(phases, dict) or set(phases) != set(_PHASES):
        _fail("Godot Web peer-exchange lifecycle phases are invalid")
    single = _roles(phases.get("single"), "single", room_id)
    reciprocal = _roles(phases.get("reciprocal"), "reciprocal", room_id)
    departure = _roles(phases.get("departure"), "departure", room_id)
    reconnect = _roles(phases.get("reconnect"), "reconnect", room_id)

    if len(single) != 1 or len(reciprocal) != 2 or len(departure) != 1 or len(reconnect) != 2:
        _fail("Godot Web peer-exchange lifecycle role counts are invalid")
    survivor = next(iter(single))
    if single[survivor]["observedPeerIds"]:
        _fail("single phase must not observe another peer")
    if survivor not in reciprocal or survivor not in departure or survivor not in reconnect:
        _fail("single-phase survivor is missing from a later lifecycle phase")
    _require_reciprocal(reciprocal, "reciprocal phase")
    _require_reciprocal(reconnect, "reconnect phase")
    departed = set(reciprocal) - set(departure)
    if len(departed) != 1 or set(departure) != set(reciprocal) - departed:
        _fail("departure phase must remove exactly one peer")
    departed_role = next(iter(departed))
    if departed_role == survivor:
        _fail("departure phase removed the single-phase survivor")
    if departure[survivor]["observedPeerIds"]:
        _fail("departure phase did not revoke the departed peer")
    if set(reconnect) != set(reciprocal):
        _fail("reconnect phase did not restore the reciprocal role inventory")

    for role_id, role in reciprocal.items():
        if int(reconnect[role_id]["localPeerId"]) != int(role["localPeerId"]):
            _fail("reconnect phase changed the stable ephemeral peer mapping")
    if int(single[survivor]["localPeerId"]) != int(reciprocal[survivor]["localPeerId"]):
        _fail("single-phase survivor peer id changed before reciprocal exchange")
    if int(departure[survivor]["localPeerId"]) != int(reciprocal[survivor]["localPeerId"]):
        _fail("surviving peer id changed during departure revocation")

    truth_boundary = _bounded_text(raw.get("truthBoundary"), "truth boundary", 4096)
    lowered = truth_boundary.lower()
    for required in ("does not", "cryptographically verify", "gameplay", "performance", "release readiness"):
        if required not in lowered:
            _fail("Godot Web peer-exchange truth boundary is too broad")

    return {
        "schemaVersion": 1,
        "proven": True,
        "browserTransportProven": True,
        "godotWebPlayerTransportProven": True,
        "runtimeHandoffConsumedByGodotProven": True,
        "reciprocalPeerObservationProven": True,
        "departureRevocationProven": True,
        "reconnectRestorationProven": True,
        "reconnectIdentityContinuityProven": True,
        "runtimeSessionRotationProven": True,
        "deploymentSourceBound": True,
        "privacySafe": True,
        "descriptorSignatureEnvelopeObserved": True,
        "descriptorSignatureCryptographicallyVerifiedByThisProbe": False,
        "gameId": game_id,
        "releaseId": release_id,
        "releaseChannel": release_channel,
        "roomId": room_id,
        "runtimeOrigin": runtime_origin,
        "authorityOrigin": authority_origin,
        "authoritySourceSha": authority_source_sha,
        "browserEngine": browser_engine,
        "browserVersion": browser_version,
        "requiredRoleCount": len(reciprocal),
        "departedRoleId": departed_role,
        "survivorRoleId": survivor,
        "receiptBytes": receipt_bytes,
        "truthBoundary": (
            "This proves the retained receipt reports the mounted Galactic Cycle Godot Web export consumed "
            "EVAVO runtime multiplayer handoff and observed source-bound authoritative reciprocal presence, "
            "departure revocation, and reconnect restoration in two Chromium contexts. It does not independently "
            "cryptographically verify the descriptor signature and does not certify gameplay, adverse-network "
            "resilience, rendering/performance quality, or release readiness."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify EVAVO Galactic Cycle Godot Web peer-exchange evidence.")
    parser.add_argument("receipt", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_godot_web_authority_peer_exchange(args.receipt)
    except GodotWebAuthorityPeerExchangeError as error:
        print(f"EVAVO_GODOT_WEB_AUTHORITY_PEER_EXCHANGE_VERIFY=FAIL reason={error}")
        return 1
    print(json.dumps(result, sort_keys=True))
    print(
        "EVAVO_GODOT_WEB_AUTHORITY_PEER_EXCHANGE_VERIFY=PASS "
        f"roles={result['requiredRoleCount']} browser={result['browserEngine']} authority_sha={result['authoritySourceSha']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

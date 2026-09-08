from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .attended_multiplayer_common import AttendedMultiplayerError, load_json_bytes
from .authority_peer_exchange import (
    AuthorityPeerExchangeError,
    verify_authority_peer_exchange,
)
from .multiplayer_peer_exchange import (
    PeerExchangeEvidenceError,
    verify_peer_exchange,
)
from .peer_exchange_matrix import PeerExchangeMatrixError, validate_peer_matrix

_SOURCE_RECEIPT = "authority-peer-exchange-lifecycle.json"
_SUMMARY = "multiplayer-agent-summary.json"
_MAX_ROLES = 32


class AuthorityPeerExchangeCrosscheckError(ValueError):
    """Raised when authority and standard peer-exchange evidence disagree."""


def _fail(message: str) -> None:
    raise AuthorityPeerExchangeCrosscheckError(message)


def _authority_reconnect_roles(receipt_path: Path) -> dict[str, dict[str, Any]]:
    raw, _payload, _loaded = load_json_bytes(receipt_path, "AUTHORITY_PEER_EXCHANGE_CROSSCHECK")
    phases = raw.get("phases")
    if not isinstance(phases, list) or len(phases) > 8:
        _fail("authority lifecycle phase inventory is invalid")
    reconnect = next(
        (phase for phase in phases if isinstance(phase, dict) and phase.get("id") == "reconnect"),
        None,
    )
    if not isinstance(reconnect, dict):
        _fail("authority lifecycle reconnect phase is missing")
    roles = reconnect.get("roles")
    if not isinstance(roles, list) or not 2 <= len(roles) <= _MAX_ROLES:
        _fail("authority lifecycle reconnect role inventory is invalid")
    result: dict[str, dict[str, Any]] = {}
    for raw_role in roles:
        if not isinstance(raw_role, dict):
            _fail("authority lifecycle reconnect role is invalid")
        role_id = raw_role.get("id")
        if not isinstance(role_id, str) or not role_id or role_id in result:
            _fail("authority lifecycle reconnect role id is invalid or duplicated")
        result[role_id] = {
            "id": role_id,
            "sessionId": raw_role.get("sessionId"),
            "localPeerId": raw_role.get("localPeerId"),
            "observedPeerIds": raw_role.get("observedPeerIds"),
        }
    return result


def _standard_roles(peer_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    roles = peer_result.get("roles")
    if not isinstance(roles, list) or not 2 <= len(roles) <= _MAX_ROLES:
        _fail("standard peer-exchange role inventory is invalid")
    result: dict[str, dict[str, Any]] = {}
    for raw_role in roles:
        if not isinstance(raw_role, dict):
            _fail("standard peer-exchange role is invalid")
        role_id = raw_role.get("id")
        if not isinstance(role_id, str) or not role_id or role_id in result:
            _fail("standard peer-exchange role id is invalid or duplicated")
        result[role_id] = {
            "id": role_id,
            "sessionId": raw_role.get("sessionId"),
            "localPeerId": raw_role.get("localPeerId"),
            "observedPeerIds": raw_role.get("observedPeerIds"),
        }
    return result


def verify_authority_peer_exchange_crosscheck(artifact_root: Path) -> dict[str, Any]:
    root = artifact_root.resolve(strict=True)
    if not root.is_dir():
        _fail("authority peer-exchange cross-check artifact root must be a directory")

    receipt_path = root / _SOURCE_RECEIPT
    summary_path = root / _SUMMARY
    authority_result = verify_authority_peer_exchange(receipt_path)
    peer_result = verify_peer_exchange(summary_path=summary_path, artifact_root=root)

    if authority_result.get("receiptSchemaVersion") != 2:
        _fail("authority peer-exchange cross-check requires a v2 lifecycle receipt")
    if authority_result.get("authoritySafetyProven") is not True:
        _fail("authority peer-exchange cross-check requires stale-socket authority safety")
    if authority_result.get("authorityLifecycleProven") is not True:
        _fail("authority peer-exchange lifecycle is not proven")
    if authority_result.get("transportProven") is not False:
        _fail("authority lifecycle verifier truth boundary changed unexpectedly")
    if peer_result.get("configured") is not True or peer_result.get("proven") is not True:
        _fail("standard peer-exchange evidence is not proven")

    required_roles = authority_result.get("requiredRoleCount")
    if (
        not isinstance(required_roles, int)
        or isinstance(required_roles, bool)
        or not 2 <= required_roles <= _MAX_ROLES
    ):
        _fail("authority peer-exchange required role count is invalid")
    if peer_result.get("requiredRoleCount") != required_roles:
        _fail("authority and standard peer-exchange role counts disagree")
    if peer_result.get("dynamicCaptureRoleCount") != required_roles:
        _fail("cross-check requires dynamic metadata capture for every required role")

    try:
        peer_matrix = validate_peer_matrix(
            peer_result.get("roles"),
            truth_boundary=(
                "Standard Test Lab client evidence is revalidated as one shared session with "
                "unique peers, reciprocal observation, accepted reserved assertions, and exact "
                "dynamic-capture accounting before comparison with authority lifecycle evidence."
            ),
            dynamic_capture_role_count=required_roles,
            require_authority_participant=False,
        )
    except PeerExchangeMatrixError as error:
        _fail(f"shared peer-exchange matrix rejected standard evidence: {error}")
    if (
        peer_matrix.get("proven") is not True
        or peer_matrix.get("requiredRoleCount") != required_roles
        or peer_matrix.get("dynamicCaptureRoleCount") != required_roles
    ):
        _fail("shared peer-exchange matrix did not reproduce the standard peer evidence proof")

    authority_roles = _authority_reconnect_roles(receipt_path)
    standard_roles = _standard_roles(peer_matrix)
    if set(authority_roles) != set(standard_roles):
        _fail("authority and standard peer-exchange role ids disagree")

    session_id = authority_result.get("sessionId")
    mismatches: list[str] = []
    for role_id in sorted(authority_roles):
        authority_role = authority_roles[role_id]
        standard_role = standard_roles[role_id]
        if authority_role["sessionId"] != session_id or standard_role["sessionId"] != session_id:
            mismatches.append(f"role {role_id} session id disagrees")
        if authority_role["localPeerId"] != standard_role["localPeerId"]:
            mismatches.append(f"role {role_id} local peer id disagrees")
        authority_observed = authority_role["observedPeerIds"]
        standard_observed = standard_role["observedPeerIds"]
        if not isinstance(authority_observed, list) or not isinstance(standard_observed, list):
            mismatches.append(f"role {role_id} observed peer set is invalid")
        elif sorted(authority_observed) != sorted(standard_observed):
            mismatches.append(f"role {role_id} observed peer set disagrees")
    if mismatches:
        _fail("; ".join(mismatches))

    return {
        "schemaVersion": 1,
        "proven": True,
        "gameId": authority_result.get("gameId"),
        "authority": authority_result.get("authority"),
        "protocol": authority_result.get("protocol"),
        "sessionId": session_id,
        "requiredRoleCount": required_roles,
        "authorityReceiptSchemaVersion": 2,
        "authorityLifecycleProven": True,
        "authoritySafetyProven": True,
        "standardPeerExchangeProven": True,
        "dynamicCaptureRoleCount": peer_matrix.get("dynamicCaptureRoleCount"),
        "semanticViewsAgree": True,
        "transportProven": False,
        "browserTransportProven": False,
        "roles": [standard_roles[role_id] for role_id in sorted(standard_roles)],
        "truthBoundary": (
            "This cross-check proves the retained GalacticCycleRoom authority lifecycle receipt and "
            "the standard Test Lab dynamic peer-exchange evidence describe the same shared session, "
            "role inventory, local peer ids, and reciprocal observations. It also requires v2 stale-"
            "socket authority retirement. It does not prove that a browser or native client traversed "
            "the deployed production transport path, WAN behavior, game feel, or release readiness."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cross-check an authority lifecycle receipt against standard Test Lab peer-exchange evidence."
    )
    parser.add_argument("artifacts", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_authority_peer_exchange_crosscheck(args.artifacts)
    except (
        AuthorityPeerExchangeCrosscheckError,
        AuthorityPeerExchangeError,
        PeerExchangeEvidenceError,
        PeerExchangeMatrixError,
        AttendedMultiplayerError,
        FileNotFoundError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        print(f"EVAVO_AUTHORITY_PEER_EXCHANGE_CROSSCHECK=FAIL reason={error}")
        return 2

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    print(
        "EVAVO_AUTHORITY_PEER_EXCHANGE_CROSSCHECK=PASS "
        f"roles={result['requiredRoleCount']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

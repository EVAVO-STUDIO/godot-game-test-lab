from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .attended_multiplayer_common import (
    AttendedMultiplayerError,
    is_record,
    load_json_bytes,
    sha256_file,
)
from .authority_peer_exchange import (
    AuthorityPeerExchangeError,
    verify_authority_peer_exchange,
)
from .multiplayer_peer_exchange import (
    PeerExchangeEvidenceError,
    verify_peer_exchange,
)

SOURCE_RECEIPT = "authority-peer-exchange-lifecycle.json"
SUMMARY = "multiplayer-agent-summary.json"
PROFILE = "profile.normalized.json"
EVIDENCE_CLASS = "authority-fixture"


class AuthorityPeerExchangeBundleError(ValueError):
    """Raised when an authority-backed Test Lab peer bundle is inadmissible."""


def _fail(message: str) -> None:
    raise AuthorityPeerExchangeBundleError(message)


def _reconnect_roles(source: dict[str, Any]) -> list[dict[str, Any]]:
    phases = source.get("phases")
    if not isinstance(phases, list):
        _fail("authority source receipt phases are invalid")
    matches = [phase for phase in phases if is_record(phase) and phase.get("id") == "reconnect"]
    if len(matches) != 1:
        _fail("authority source receipt reconnect phase is missing or duplicated")
    raw_roles = matches[0].get("roles")
    if not isinstance(raw_roles, list) or not 2 <= len(raw_roles) <= 32:
        _fail("authority source receipt reconnect roles are invalid")
    roles: list[dict[str, Any]] = []
    for raw in raw_roles:
        if not is_record(raw):
            _fail("authority source reconnect role is invalid")
        role = dict(raw)
        if set(role) != {"id", "sessionId", "localPeerId", "observedPeerIds"}:
            _fail("authority source reconnect role has unexpected fields")
        roles.append(
            {
                "id": role.get("id"),
                "sessionId": role.get("sessionId"),
                "localPeerId": role.get("localPeerId"),
                "observedPeerIds": role.get("observedPeerIds"),
            }
        )
    roles.sort(key=lambda role: str(role["id"]).casefold())
    return roles


def _converted_roles(peer_result: dict[str, Any]) -> list[dict[str, Any]]:
    raw_roles = peer_result.get("roles")
    if not isinstance(raw_roles, list):
        _fail("converted Test Lab peer roles are invalid")
    roles = [
        {
            "id": role.get("id"),
            "sessionId": role.get("sessionId"),
            "localPeerId": role.get("localPeerId"),
            "observedPeerIds": role.get("observedPeerIds"),
        }
        for role in raw_roles
        if is_record(role)
    ]
    if len(roles) != len(raw_roles):
        _fail("converted Test Lab peer roles contain invalid records")
    roles.sort(key=lambda role: str(role["id"]).casefold())
    return roles


def verify_authority_peer_exchange_bundle(*, artifact_root: Path) -> dict[str, Any]:
    root = artifact_root.resolve(strict=True)
    if not root.is_dir():
        _fail("authority peer-exchange bundle root is not a directory")

    source_path = root / SOURCE_RECEIPT
    summary_path = root / SUMMARY
    profile_path = root / PROFILE
    if not source_path.is_file() or not summary_path.is_file() or not profile_path.is_file():
        _fail("authority peer-exchange bundle is missing required retained artifacts")

    try:
        authority_result = verify_authority_peer_exchange(source_path)
        peer_result = verify_peer_exchange(summary_path=summary_path, artifact_root=root)
    except (AuthorityPeerExchangeError, PeerExchangeEvidenceError, AttendedMultiplayerError) as error:
        raise AuthorityPeerExchangeBundleError(str(error)) from error

    if authority_result.get("receiptSchemaVersion") != 3:
        _fail("authority peer-exchange bundle requires a schema-3 source receipt")
    if authority_result.get("authoritySafetyProven") is not True:
        _fail("authority peer-exchange bundle does not prove stale-socket retirement")
    if authority_result.get("staleSocketInboundRejectedProven") is not True:
        _fail("authority peer-exchange bundle does not prove stale inbound rejection")
    if peer_result.get("configured") is not True or peer_result.get("proven") is not True:
        _fail("converted Test Lab peer-exchange evidence is not proven")

    summary, _summary_bytes, _ = load_json_bytes(summary_path, "AUTHORITY_PEER_BUNDLE_SUMMARY")
    if summary.get("peerExchangeEvidenceClass") != EVIDENCE_CLASS:
        _fail("authority peer-exchange bundle is missing the authority-fixture evidence class")
    if summary.get("peerExchangeSourceReceipt") != SOURCE_RECEIPT:
        _fail("authority peer-exchange bundle source receipt binding is invalid")

    source, _source_bytes, _ = load_json_bytes(source_path, "AUTHORITY_PEER_BUNDLE_SOURCE")
    source_roles = _reconnect_roles(source)
    converted_roles = _converted_roles(peer_result)
    if converted_roles != source_roles:
        _fail("converted Test Lab peer evidence does not match the retained source reconnect phase")

    required_roles = authority_result.get("requiredRoleCount")
    if (
        not isinstance(required_roles, int)
        or isinstance(required_roles, bool)
        or peer_result.get("requiredRoleCount") != required_roles
        or peer_result.get("dynamicCaptureRoleCount") != required_roles
    ):
        _fail("authority peer-exchange bundle role counts or capture provenance are inconsistent")

    return {
        "schemaVersion": 1,
        "status": "passed",
        "evidenceClass": EVIDENCE_CLASS,
        "gameId": authority_result.get("gameId"),
        "authority": authority_result.get("authority"),
        "protocol": authority_result.get("protocol"),
        "sessionId": authority_result.get("sessionId"),
        "requiredRoleCount": required_roles,
        "peerExchangeProven": True,
        "authorityLifecycleProven": True,
        "departureRevocationProven": True,
        "reconnectRestorationProven": True,
        "staleSocketRetirementProven": True,
        "staleSocketInboundRejectedProven": True,
        "fixtureConvertedToTestLabShape": True,
        "nativeGodotJourneyObserved": False,
        "browserJourneyObserved": False,
        "transportProven": False,
        "browserTransportProven": False,
        "sourceReceipt": SOURCE_RECEIPT,
        "sourceReceiptSha256": sha256_file(source_path),
        "roles": converted_roles,
        "truthBoundary": (
            "This PASS is source-bound authority-fixture evidence. The retained schema-3 "
            "GalacticCycleRoom lifecycle receipt is independently validated and the converted "
            "Test Lab metadata-capture values must exactly match its reconnect phase. It proves "
            "reciprocal authority presence, departure revocation, reconnect restoration, stale "
            "socket retirement, stale inbound rejection, and the declared privacy boundary. It "
            "does not mean Godot metadata_capture ran in a native game process, and it does not "
            "prove browser/WebSocket transport, deployed Cloudflare behavior, WAN resilience, "
            "latency, packet loss, or game feel."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a source-bound authority peer-exchange Test Lab bundle."
    )
    parser.add_argument("artifact_root", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_authority_peer_exchange_bundle(artifact_root=args.artifact_root)
    except (AuthorityPeerExchangeBundleError, OSError) as error:
        print(f"EVAVO_AUTHORITY_PEER_EXCHANGE_BUNDLE=FAIL reason={error}")
        return 1
    print(json.dumps(result, sort_keys=True))
    print(
        "EVAVO_AUTHORITY_PEER_EXCHANGE_BUNDLE=PASS "
        f"roles={result['requiredRoleCount']} evidence_class={result['evidenceClass']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

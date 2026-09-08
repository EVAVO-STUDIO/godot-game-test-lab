from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from .authority_peer_exchange import AuthorityPeerExchangeError, verify_authority_peer_exchange
from .browser_runtime_authority_peer_exchange import (
    BrowserRuntimeAuthorityPeerExchangeError,
    verify_browser_runtime_authority_peer_exchange,
)
from .godot_web_authority_peer_exchange import (
    GodotWebAuthorityPeerExchangeError,
    verify_godot_web_authority_peer_exchange,
)
from .runtime_authority_peer_exchange import (
    RuntimeAuthorityPeerExchangeError,
    verify_runtime_authority_peer_exchange,
)


class MultiplayerEvidenceLadderError(ValueError):
    """Raised when individually valid multiplayer evidence tiers do not describe one deployment."""


def _fail(message: str) -> None:
    raise MultiplayerEvidenceLadderError(message)


def _verified(label: str, verifier: Callable[[Path], dict[str, Any]], path: Path) -> dict[str, Any]:
    try:
        result = verifier(path)
    except (
        AuthorityPeerExchangeError,
        RuntimeAuthorityPeerExchangeError,
        BrowserRuntimeAuthorityPeerExchangeError,
        GodotWebAuthorityPeerExchangeError,
    ) as error:
        raise MultiplayerEvidenceLadderError(f"{label} evidence failed verification: {error}") from error
    if result.get("proven") is not True:
        _fail(f"{label} verifier did not return proven=true")
    return result


def _same(results: list[tuple[str, dict[str, Any]]], field: str) -> Any:
    values = [(label, result.get(field)) for label, result in results]
    first = values[0][1]
    if any(value != first for _, value in values[1:]):
        details = ", ".join(f"{label}={value!r}" for label, value in values)
        _fail(f"multiplayer evidence tiers disagree on {field}: {details}")
    return first


def verify_multiplayer_evidence_ladder(
    authority_receipt: Path,
    runtime_receipt: Path,
    browser_receipt: Path,
    godot_web_receipt: Path,
) -> dict[str, Any]:
    authority = _verified("authority", verify_authority_peer_exchange, authority_receipt)
    runtime = _verified("runtime", verify_runtime_authority_peer_exchange, runtime_receipt)
    browser = _verified("browser", verify_browser_runtime_authority_peer_exchange, browser_receipt)
    godot_web = _verified("godot-web", verify_godot_web_authority_peer_exchange, godot_web_receipt)

    all_tiers = [
        ("authority", authority),
        ("runtime", runtime),
        ("browser", browser),
        ("godot-web", godot_web),
    ]
    transport_tiers = [
        ("runtime", runtime),
        ("browser", browser),
        ("godot-web", godot_web),
    ]

    game_id = _same(all_tiers, "gameId")
    protocol = _same([("authority", authority), ("runtime", runtime), ("browser", browser)], "protocol")
    room_id = _same(transport_tiers, "roomId")
    if authority.get("sessionId") != room_id:
        _fail("authority lifecycle session does not match runtime/browser Godot room id")

    release_id = _same(transport_tiers, "releaseId")
    release_channel = _same(transport_tiers, "releaseChannel")
    runtime_origin = _same(transport_tiers, "runtimeOrigin")
    authority_origin = _same(transport_tiers, "authorityOrigin")
    authority_source_sha = _same(transport_tiers, "authoritySourceSha")
    role_count = _same(all_tiers, "requiredRoleCount")
    departed_role = _same(all_tiers, "departedRoleId")
    survivor_role = _same(all_tiers, "survivorRoleId")

    if runtime.get("transportProven") is not True or runtime.get("browserTransportProven") is not False:
        _fail("runtime evidence tier lost its non-browser transport boundary")
    if browser.get("browserTransportProven") is not True or browser.get("godotPlayerTransportProven") is not False:
        _fail("browser evidence tier lost its non-Godot-player boundary")
    if godot_web.get("browserTransportProven") is not True or godot_web.get("godotWebPlayerTransportProven") is not True:
        _fail("Godot Web evidence tier does not prove browser + Godot-player transport")
    if godot_web.get("runtimeHandoffConsumedByGodotProven") is not True:
        _fail("Godot Web evidence tier does not prove runtime handoff consumption")
    if godot_web.get("descriptorSignatureCryptographicallyVerifiedByThisProbe") is not True:
        _fail("Godot Web top tier requires cryptographic descriptor verification against external trust")

    for label, result in all_tiers:
        if result.get("privacySafe") is not True:
            _fail(f"{label} evidence tier is not privacy-safe")
    if authority.get("authoritySafetyProven") is not True or authority.get("staleSocketInboundRejectedProven") is not True:
        _fail("authority evidence tier lacks the current stale-socket safety contract")
    for label, result in transport_tiers:
        if result.get("deploymentSourceBound") is not True:
            _fail(f"{label} evidence tier is not source-bound")
        if result.get("reconnectIdentityContinuityProven") is not True:
            _fail(f"{label} evidence tier lost reconnect identity continuity")
        if result.get("runtimeSessionRotationProven") is not True:
            _fail(f"{label} evidence tier lost runtime-session rotation")

    return {
        "schemaVersion": 2,
        "proven": True,
        "highestTier": "godot-web-player-cryptographic-release",
        "tierCount": 4,
        "authorityLifecycleProven": True,
        "runtimeTransportProven": True,
        "browserNativeTransportProven": True,
        "godotWebPlayerTransportProven": True,
        "runtimeHandoffConsumedByGodotProven": True,
        "descriptorSignatureCryptographicallyVerified": True,
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
        "requiredRoleCount": role_count,
        "departedRoleId": departed_role,
        "survivorRoleId": survivor_role,
        "truthBoundary": (
            "This proves four independently verified receipts align on one Galactic Cycle multiplayer deployment: "
            "server-authority lifecycle semantics, EVAVO runtime-to-authority transport, Chromium browser-native "
            "transport, and the mounted Godot Web player consuming runtime handoff and observing reciprocal "
            "presence through departure and reconnect. The top Godot-Web receipt also cryptographically verifies "
            "the mounted descriptor against external local release trust. It still does not certify gameplay "
            "correctness, adverse network quality, visual/performance quality, or release readiness."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cross-bind EVAVO multiplayer authority/runtime/browser/Godot evidence.")
    parser.add_argument("authority_receipt", type=Path)
    parser.add_argument("runtime_receipt", type=Path)
    parser.add_argument("browser_receipt", type=Path)
    parser.add_argument("godot_web_receipt", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_multiplayer_evidence_ladder(
            args.authority_receipt,
            args.runtime_receipt,
            args.browser_receipt,
            args.godot_web_receipt,
        )
    except MultiplayerEvidenceLadderError as error:
        print(f"EVAVO_MULTIPLAYER_EVIDENCE_LADDER=FAIL reason={error}")
        return 1
    print(json.dumps(result, sort_keys=True))
    print(
        "EVAVO_MULTIPLAYER_EVIDENCE_LADDER=PASS "
        f"tiers={result['tierCount']} highest={result['highestTier']} authority_sha={result['authoritySourceSha']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

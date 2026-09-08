from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab.godot_web_authority_peer_exchange import (
    GodotWebAuthorityPeerExchangeError,
    verify_godot_web_authority_peer_exchange,
)


def _role(role_id: str, local_peer: int, observed: list[int]) -> dict[str, object]:
    return {
        "id": role_id,
        "sessionId": "persistent-galaxy",
        "localPeerId": local_peer,
        "observedPeerIds": observed,
    }


def _receipt() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "kind": "evavo-godot-web-authority-peer-exchange",
        "gameId": "galactic-cycle-online",
        "releaseId": "0.1.0-dev",
        "releaseChannel": "production",
        "runtimeOrigin": "https://runtime.example.test",
        "authorityOrigin": "wss://authority.example.test",
        "authoritySourceSha": "a" * 40,
        "browserEngine": "chromium",
        "browserVersion": "140.0.0.0",
        "browserContextCount": 2,
        "browserTransportProven": True,
        "browserLifecycleErrorsAbsentProven": True,
        "godotWebExportProven": True,
        "godotRuntimeRunningProven": True,
        "runtimeHandoffConsumedByGodot": True,
        "godotPeerEvidenceBridgeProven": True,
        "runtimeSessionIssuerProven": True,
        "boundTicketAdmissionProven": True,
        "mountedReleaseProven": True,
        "signedReleaseDescriptorEnvelopeProven": True,
        "reciprocalPeerObservationProven": True,
        "departureRevocationProven": True,
        "reconnectRestorationProven": True,
        "reconnectIdentityContinuityProven": True,
        "runtimeSessionRotationProven": True,
        "authorityPeerClaimedByClient": False,
        "roomId": "persistent-galaxy",
        "phases": {
            "single": [_role("alpha", 1, [])],
            "reciprocal": [_role("alpha", 1, [2]), _role("beta", 2, [1])],
            "departure": [_role("alpha", 1, [])],
            "reconnect": [_role("alpha", 1, [2]), _role("beta", 2, [1])],
        },
        "truthBoundary": (
            "This evidence does not independently cryptographically verify the descriptor signature, "
            "and it does not certify gameplay correctness, adverse-network resilience, performance quality, "
            "or release readiness."
        ),
    }


def _write(tmp_path: Path, receipt: dict[str, object]) -> Path:
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


def test_accepts_exact_godot_web_lifecycle_receipt(tmp_path: Path) -> None:
    result = verify_godot_web_authority_peer_exchange(_write(tmp_path, _receipt()))
    assert result["proven"] is True
    assert result["godotWebPlayerTransportProven"] is True
    assert result["privacySafe"] is True
    assert result["requiredRoleCount"] == 2
    assert result["departedRoleId"] == "beta"
    assert result["descriptorSignatureCryptographicallyVerifiedByThisProbe"] is False


def test_rejects_nonreciprocal_peer_observation(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["phases"]["reciprocal"][0]["observedPeerIds"] = []
    with pytest.raises(GodotWebAuthorityPeerExchangeError, match="exact reciprocal peer set"):
        verify_godot_web_authority_peer_exchange(_write(tmp_path, receipt))


def test_rejects_peer_mapping_change_on_reconnect(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["phases"]["reconnect"] = [_role("alpha", 2, [1]), _role("beta", 1, [2])]
    with pytest.raises(GodotWebAuthorityPeerExchangeError, match="stable ephemeral peer mapping"):
        verify_godot_web_authority_peer_exchange(_write(tmp_path, receipt))


def test_rejects_private_runtime_fields(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["ticket"] = "claims.signature"
    with pytest.raises(GodotWebAuthorityPeerExchangeError):
        verify_godot_web_authority_peer_exchange(_write(tmp_path, receipt))


def test_rejects_false_proof_flags(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["runtimeHandoffConsumedByGodot"] = False
    with pytest.raises(GodotWebAuthorityPeerExchangeError, match="runtimeHandoffConsumedByGodot must be true"):
        verify_godot_web_authority_peer_exchange(_write(tmp_path, receipt))


def test_rejects_overbroad_truth_boundary(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["truthBoundary"] = "This proves everything needed for release."
    with pytest.raises(GodotWebAuthorityPeerExchangeError, match="truth boundary is too broad"):
        verify_godot_web_authority_peer_exchange(_write(tmp_path, receipt))

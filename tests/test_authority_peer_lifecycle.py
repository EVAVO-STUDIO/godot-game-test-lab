from __future__ import annotations

import pytest

from godot_game_test_lab.authority_peer_lifecycle import (
    AuthorityPeerLifecycleError,
    verify_authority_peer_lifecycle,
)


def _role(role_id: str, peer_id: int, observed: list[int]) -> dict[str, object]:
    return {
        "id": role_id,
        "sessionId": "persistent-galaxy",
        "localPeerId": peer_id,
        "observedPeerIds": observed,
    }


def _receipt() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "kind": "evavo-authority-peer-exchange-lifecycle",
        "gameId": "galactic-cycle-online",
        "authority": "GalacticCycleRoom",
        "protocol": "galactic-cycle.v1",
        "sessionId": "persistent-galaxy",
        "departedRoleId": "beta",
        "phases": [
            {"id": "single", "roles": [_role("alpha", 1, [])]},
            {
                "id": "reciprocal",
                "roles": [_role("alpha", 1, [2]), _role("beta", 2, [1])],
            },
            {"id": "departure", "roles": [_role("alpha", 1, [])]},
            {
                "id": "reconnect",
                "roles": [_role("alpha", 1, [2]), _role("beta", 2, [1])],
            },
        ],
        "privacy": {
            "rawPlayerIdsTransmitted": False,
            "runtimeSessionIdsTransmitted": False,
            "credentialsTransmitted": False,
        },
        "truthBoundary": (
            "Server-authority lifecycle proof only; this does not claim browser or native client transport traversal."
        ),
    }


def test_verifies_join_departure_and_reconnect_lifecycle_without_transport_claim() -> None:
    result = verify_authority_peer_lifecycle(_receipt())
    assert result["proven"] is True
    assert result["authorityLifecycleProven"] is True
    assert result["reciprocalPeerSemanticsProven"] is True
    assert result["reconnectPeerSemanticsProven"] is True
    assert result["transportProven"] is False
    assert result["browserTransportProven"] is False
    assert result["findings"] == []


def test_fails_if_departed_role_remains_visible() -> None:
    receipt = _receipt()
    receipt["phases"][2] = {
        "id": "departure",
        "roles": [_role("alpha", 1, [2]), _role("beta", 2, [1])],
    }
    result = verify_authority_peer_lifecycle(receipt)
    assert result["proven"] is False
    assert "departed role remained present after departure" in result["findings"]


def test_fails_if_reconnect_does_not_restore_reciprocal_observation() -> None:
    receipt = _receipt()
    receipt["phases"][3] = {
        "id": "reconnect",
        "roles": [_role("alpha", 1, []), _role("beta", 2, [1])],
    }
    result = verify_authority_peer_lifecycle(receipt)
    assert result["proven"] is False
    assert any(str(finding).startswith("reconnect:") for finding in result["findings"])


def test_fails_if_any_phase_changes_session() -> None:
    receipt = _receipt()
    receipt["phases"][3]["roles"][1]["sessionId"] = "other-room"
    result = verify_authority_peer_lifecycle(receipt)
    assert result["proven"] is False
    assert any("different session" in str(finding) for finding in result["findings"])


def test_rejects_identity_or_credential_fields_in_role_evidence() -> None:
    receipt = _receipt()
    receipt["phases"][1]["roles"][0]["playerId"] = "p_secret"
    with pytest.raises(AuthorityPeerLifecycleError, match="unexpected fields"):
        verify_authority_peer_lifecycle(receipt)


def test_rejects_privacy_claim_escalation() -> None:
    receipt = _receipt()
    receipt["privacy"]["credentialsTransmitted"] = True
    with pytest.raises(AuthorityPeerLifecycleError, match="explicitly deny"):
        verify_authority_peer_lifecycle(receipt)

from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab import peer_exchange_semantics as subject


def _evidence() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "evidenceClass": "authority-room-presence-class",
        "source": "galactic-cycle-authority",
        "roles": [
            {
                "id": "alpha",
                "required": True,
                "sessionId": "persistent-galaxy",
                "localPeerId": 1,
                "observedPeerIds": [2],
            },
            {
                "id": "beta",
                "required": True,
                "sessionId": "persistent-galaxy",
                "localPeerId": 2,
                "observedPeerIds": [1],
            },
        ],
    }


def test_proves_portable_reciprocal_peer_observation_without_transport_claim() -> None:
    result = subject.verify_peer_observations(_evidence())

    assert result["configured"] is True
    assert result["proven"] is True
    assert result["transportProven"] is False
    assert result["requiredRoleCount"] == 2
    assert result["authorityObserved"] is False
    assert result["findings"] == []
    assert "does not prove that bytes crossed a real network" in result["truthBoundary"]


def test_missing_reciprocal_observation_fails_closed() -> None:
    evidence = _evidence()
    evidence["roles"][1]["observedPeerIds"] = []  # type: ignore[index]

    result = subject.verify_peer_observations(evidence)

    assert result["proven"] is False
    assert any("every other required peer" in item for item in result["findings"])


def test_mismatched_session_fails_closed() -> None:
    evidence = _evidence()
    evidence["roles"][1]["sessionId"] = "other-room"  # type: ignore[index]

    result = subject.verify_peer_observations(evidence)

    assert result["proven"] is False
    assert any("shared multiplayer session" in item for item in result["findings"])


def test_self_observation_is_structurally_rejected() -> None:
    evidence = _evidence()
    evidence["roles"][0]["observedPeerIds"] = [1, 2]  # type: ignore[index]

    with pytest.raises(subject.PeerObservationEvidenceError, match="local peer id"):
        subject.verify_peer_observations(evidence)


def test_foreign_shared_authority_is_not_accepted() -> None:
    evidence = _evidence()
    for role in evidence["roles"]:  # type: ignore[union-attr]
        role["authorityPeerId"] = 99

    result = subject.verify_peer_observations(evidence)

    assert result["proven"] is False
    assert any("not a participating required peer" in item for item in result["findings"])


def test_partial_authority_evidence_fails_closed() -> None:
    evidence = _evidence()
    evidence["roles"][0]["authorityPeerId"] = 1  # type: ignore[index]

    result = subject.verify_peer_observations(evidence)

    assert result["proven"] is False
    assert any("partially configured" in item for item in result["findings"])


def test_unknown_role_fields_are_rejected() -> None:
    evidence = _evidence()
    evidence["roles"][0]["accessToken"] = "must-not-pass"  # type: ignore[index]

    with pytest.raises(subject.PeerObservationEvidenceError, match="unexpected fields"):
        subject.verify_peer_observations(evidence)


def test_file_loader_is_bounded_and_returns_same_semantics(tmp_path: Path) -> None:
    evidence_path = tmp_path / "peer-evidence.json"
    evidence_path.write_text(json.dumps(_evidence()), encoding="utf-8")

    result = subject.load_and_verify(evidence_path)

    assert result["proven"] is True
    assert result["transportProven"] is False

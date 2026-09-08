from __future__ import annotations

import pytest

from godot_game_test_lab.peer_exchange_matrix import (
    PeerExchangeMatrixError,
    validate_peer_matrix,
)


def _roles() -> list[dict[str, object]]:
    return [
        {
            "id": "alpha",
            "sessionId": "shared-room",
            "localPeerId": 1,
            "observedPeerIds": [2],
            "dynamicRequiredMetadataCaptured": True,
            "reservedAssertionsAccepted": True,
        },
        {
            "id": "beta",
            "sessionId": "shared-room",
            "localPeerId": 2,
            "observedPeerIds": [1],
            "dynamicRequiredMetadataCaptured": True,
            "reservedAssertionsAccepted": True,
        },
    ]


def test_peer_matrix_accepts_reciprocal_dynamic_evidence() -> None:
    result = validate_peer_matrix(
        _roles(),
        truth_boundary="Running clients reported reciprocal game-owned peer evidence.",
        dynamic_capture_role_count=2,
        require_authority_participant=False,
    )
    assert result["proven"] is True
    assert result["dynamicCaptureRoleCount"] == 2
    assert result["requiredRoleCount"] == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dynamicRequiredMetadataCaptured", "false"),
        ("reservedAssertionsAccepted", "true"),
        ("dynamicRequiredMetadataCaptured", 1),
        ("reservedAssertionsAccepted", 0),
    ],
)
def test_peer_matrix_rejects_truthy_non_boolean_evidence_flags(field: str, value: object) -> None:
    roles = _roles()
    roles[0][field] = value
    with pytest.raises(PeerExchangeMatrixError, match="must be boolean"):
        validate_peer_matrix(
            roles,
            truth_boundary="Strict evidence typing.",
            dynamic_capture_role_count=2,
            require_authority_participant=False,
        )


def test_peer_matrix_rejects_forged_dynamic_capture_count() -> None:
    with pytest.raises(PeerExchangeMatrixError, match="disagrees with role evidence"):
        validate_peer_matrix(
            _roles(),
            truth_boundary="Dynamic evidence count must be self-verifying.",
            dynamic_capture_role_count=1,
            require_authority_participant=False,
        )


def test_peer_matrix_does_not_prove_rejected_reserved_assertions() -> None:
    roles = _roles()
    roles[1]["reservedAssertionsAccepted"] = False
    result = validate_peer_matrix(
        roles,
        truth_boundary="Rejected assertions cannot become peer-exchange proof.",
        dynamic_capture_role_count=2,
        require_authority_participant=False,
    )
    assert result["proven"] is False
    assert any("reserved multiplayer assertions were not accepted" in item for item in result["findings"])


def test_peer_matrix_rejects_untrimmed_or_carriage_return_truth_boundary() -> None:
    with pytest.raises(PeerExchangeMatrixError):
        validate_peer_matrix(
            _roles(),
            truth_boundary=" leading space",
            dynamic_capture_role_count=2,
            require_authority_participant=False,
        )
    with pytest.raises(PeerExchangeMatrixError):
        validate_peer_matrix(
            _roles(),
            truth_boundary="line one\rline two",
            dynamic_capture_role_count=2,
            require_authority_participant=False,
        )


def test_peer_matrix_requires_boolean_authority_participant_policy() -> None:
    with pytest.raises(PeerExchangeMatrixError, match="must be boolean"):
        validate_peer_matrix(
            _roles(),
            truth_boundary="Authority policy type must be explicit.",
            dynamic_capture_role_count=2,
            require_authority_participant=1,  # type: ignore[arg-type]
        )

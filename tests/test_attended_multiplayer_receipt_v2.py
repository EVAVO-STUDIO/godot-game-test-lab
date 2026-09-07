from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest

from godot_game_test_lab import attended_multiplayer as subject
from godot_game_test_lab import attended_multiplayer_common as common
from godot_game_test_lab import attended_multiplayer_receipt as receipt_subject

ROOT = Path(__file__).resolve().parents[1]


def _load_fixture():
    path = ROOT / "tests" / "test_attended_multiplayer.py"
    spec = importlib.util.spec_from_file_location("attended_multiplayer_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._fixture


def _evidence_and_attestation(tmp_path: Path):
    fixture = _load_fixture()
    artifacts, summary_path, generated = fixture(tmp_path)
    evidence = subject.verify_multiplayer_summary_sources(
        summary_path=summary_path,
        artifact_root=artifacts,
    )
    attested = generated + timedelta(minutes=2)
    attestation = subject.build_operator_attestation(
        evidence=evidence,
        campaign_id="campaign-v2-001",
        operator_id="Greg Parker",
        windows_session_id=7,
        confirmation="ATTEND multiplayer-test-001",
        now=attested,
    )
    return evidence, attestation, attested


def test_new_receipt_is_v2_and_binds_unconfigured_peer_exchange(tmp_path: Path) -> None:
    evidence, attestation, attested = _evidence_and_attestation(tmp_path)
    assert evidence["peerExchange"]["configured"] is False
    assert evidence["peerExchange"]["proven"] is False

    receipt = subject.compile_attended_multiplayer_receipt(
        evidence=evidence,
        attestation=attestation,
        now=attested + timedelta(minutes=1),
    )
    assert receipt["schemaVersion"] == 2
    assert receipt["contract"] == common.RECEIPT_CONTRACT
    assert receipt["contract"].endswith(".v2")
    assert receipt["peerExchange"] == evidence["peerExchange"]
    assert receipt["sourceVerification"]["peerExchangeContractReverified"] is True
    assert receipt["authority"]["transportPathCertified"] is False

    verified = subject.verify_attended_multiplayer_receipt(
        receipt,
        evidence=evidence,
        attestation=attestation,
    )
    assert verified == receipt


def test_legacy_v1_receipt_remains_verifiable(tmp_path: Path) -> None:
    evidence, attestation, attested = _evidence_and_attestation(tmp_path)
    generated_at = (attested + timedelta(minutes=1)).isoformat()
    verified_attestation = subject.verify_operator_attestation(
        attestation,
        evidence=evidence,
        reference_time=attested + timedelta(minutes=1),
    )
    body = receipt_subject._receipt_body_v1(
        evidence=evidence,
        attestation=verified_attestation,
        generated_at=generated_at,
    )
    digest = common.sha256_object(body)
    legacy = {
        **body,
        "receiptSha256": digest,
        "receiptReference": "evavo-attended-multiplayer-receipt:sha256:" + digest,
    }

    verified = subject.verify_attended_multiplayer_receipt(
        legacy,
        evidence=evidence,
        attestation=attestation,
    )
    assert verified["schemaVersion"] == 1
    assert verified["contract"] == common.RECEIPT_CONTRACT_V1
    assert "peerExchange" not in verified


def test_receipt_compiler_rejects_configured_but_unproven_peer_exchange(
    tmp_path: Path,
) -> None:
    evidence, attestation, attested = _evidence_and_attestation(tmp_path)
    changed = dict(evidence)
    changed["peerExchange"] = {
        "schemaVersion": 1,
        "configured": True,
        "proven": False,
        "requiredRoleCount": 2,
        "authorityObserved": False,
        "roles": [],
        "findings": ["reciprocal peer observation was not established"],
        "truthBoundary": "Configured peer exchange was not proven.",
    }

    with pytest.raises(
        subject.AttendedMultiplayerError,
        match="ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_NOT_PROVEN",
    ):
        subject.compile_attended_multiplayer_receipt(
            evidence=changed,
            attestation=attestation,
            now=attested + timedelta(minutes=1),
        )

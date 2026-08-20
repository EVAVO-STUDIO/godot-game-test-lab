from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .attended_multiplayer_common import (
    ATTESTATION_CONTRACT,
    ATTESTATION_VALIDITY,
    MAX_ATTESTATION_LAG,
    bounded_line,
    digest,
    exact_fields,
    exact_timestamp,
    fail,
    is_record,
    positive_int,
    safe_id,
    sha256_bytes,
    sha256_object,
)


def confirmation_phrase(run_id: str) -> str:
    return f"ATTEND {run_id}"


def _attestation_body(
    *,
    evidence: dict[str, Any],
    campaign_id: str,
    operator_id: str,
    windows_session_id: int,
    attested_at: str,
    expires_at: str,
    confirmation_phrase_sha256: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "contract": ATTESTATION_CONTRACT,
        "attestedAt": attested_at,
        "expiresAt": expires_at,
        "campaignId": campaign_id,
        "runId": evidence["runId"],
        "labSha": evidence["labSha"],
        "targetSha": evidence["targetSha"],
        "sessionLabel": evidence["sessionLabel"],
        "operatorId": operator_id,
        "operatorIdentitySource": "windows-current-principal",
        "operatorIdentityCryptographicallyVerified": False,
        "windowsSessionId": windows_session_id,
        "explorerInSameSession": True,
        "interactiveDesktop": True,
        "confirmationPhraseSha256": confirmation_phrase_sha256,
        "confirmationMatched": True,
        "operatorAttendanceAttested": True,
        "operatorObservedCompleteRun": True,
        "automated": False,
        "humanVisualApprovalClaimed": False,
        "humanGameFeelApprovalClaimed": False,
        "physicalControllerCertified": False,
        "realNetworkConditionsCertified": False,
        "releaseApprovalClaimed": False,
        "sourceMutationAuthority": False,
        "deploymentAuthority": False,
        "publicationAuthority": False,
    }


def build_operator_attestation(
    *,
    evidence: dict[str, Any],
    campaign_id: str,
    operator_id: str,
    windows_session_id: int,
    confirmation: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    campaign = safe_id(campaign_id, "ATTENDED_MULTIPLAYER_CAMPAIGN_ID_INVALID")
    operator = bounded_line(
        operator_id, "ATTENDED_MULTIPLAYER_OPERATOR_ID_INVALID", maximum_bytes=256
    )
    session_id = positive_int(
        windows_session_id,
        "ATTENDED_MULTIPLAYER_ATTESTATION_SESSION_INVALID",
        maximum=2**31 - 1,
    )
    if session_id != evidence.get("windowsSessionId"):
        fail("ATTENDED_MULTIPLAYER_ATTESTATION_SESSION_MISMATCH")
    phrase = confirmation_phrase(str(evidence["runId"]))
    if confirmation != phrase:
        fail("ATTENDED_MULTIPLAYER_CONFIRMATION_MISMATCH")
    instant = (now or datetime.now(UTC)).astimezone(UTC)
    generated_at = evidence.get("generatedAtInstant")
    if not isinstance(generated_at, datetime):
        fail("ATTENDED_MULTIPLAYER_EVIDENCE_GENERATED_AT_INVALID")
    if instant < generated_at or instant - generated_at > MAX_ATTESTATION_LAG:
        fail("ATTENDED_MULTIPLAYER_ATTESTATION_TIME_INVALID")
    body = _attestation_body(
        evidence=evidence,
        campaign_id=campaign,
        operator_id=operator,
        windows_session_id=session_id,
        attested_at=instant.isoformat(),
        expires_at=(instant + ATTESTATION_VALIDITY).isoformat(),
        confirmation_phrase_sha256=sha256_bytes(phrase.encode("utf-8")),
    )
    attestation_digest = sha256_object(body)
    return {
        **body,
        "attestationSha256": attestation_digest,
        "attestationReference": (
            "evavo-attended-multiplayer-operator-attestation:sha256:"
            + attestation_digest
        ),
    }


def verify_operator_attestation(
    value: object,
    *,
    evidence: dict[str, Any],
    reference_time: datetime,
) -> dict[str, Any]:
    if not is_record(value):
        fail("ATTENDED_MULTIPLAYER_ATTESTATION_INVALID")
    attestation = dict(value)
    expected_fields = set(
        _attestation_body(
            evidence=evidence,
            campaign_id="campaign",
            operator_id="operator",
            windows_session_id=1,
            attested_at="2000-01-01T00:00:00+00:00",
            expires_at="2000-01-01T04:15:00+00:00",
            confirmation_phrase_sha256="0" * 64,
        )
    ) | {"attestationSha256", "attestationReference"}
    exact_fields(
        attestation,
        expected_fields,
        "ATTENDED_MULTIPLAYER_ATTESTATION_FIELDS_INVALID",
    )
    if attestation.get("contract") != ATTESTATION_CONTRACT:
        fail("ATTENDED_MULTIPLAYER_ATTESTATION_CONTRACT_INVALID")
    if attestation.get("schemaVersion") != 1:
        fail("ATTENDED_MULTIPLAYER_ATTESTATION_SCHEMA_INVALID")

    campaign = safe_id(
        attestation.get("campaignId"), "ATTENDED_MULTIPLAYER_CAMPAIGN_ID_INVALID"
    )
    operator = bounded_line(
        attestation.get("operatorId"),
        "ATTENDED_MULTIPLAYER_OPERATOR_ID_INVALID",
        256,
    )
    mismatches = {
        "runId": "RUN",
        "labSha": "LAB_SHA",
        "targetSha": "TARGET_SHA",
        "sessionLabel": "SESSION_LABEL",
        "windowsSessionId": "SESSION",
    }
    for field, suffix in mismatches.items():
        if attestation.get(field) != evidence[field]:
            fail(f"ATTENDED_MULTIPLAYER_ATTESTATION_{suffix}_MISMATCH")

    attested_text, attested_at = exact_timestamp(
        attestation.get("attestedAt"), "ATTENDED_MULTIPLAYER_ATTESTED_AT_INVALID"
    )
    expires_text, expires_at = exact_timestamp(
        attestation.get("expiresAt"), "ATTENDED_MULTIPLAYER_EXPIRES_AT_INVALID"
    )
    if expires_at - attested_at != ATTESTATION_VALIDITY:
        fail("ATTENDED_MULTIPLAYER_ATTESTATION_EXPIRY_INVALID")
    generated_at = evidence["generatedAtInstant"]
    if attested_at < generated_at or attested_at - generated_at > MAX_ATTESTATION_LAG:
        fail("ATTENDED_MULTIPLAYER_ATTESTATION_TIME_INVALID")
    checked_at = reference_time.astimezone(UTC)
    if checked_at < attested_at or checked_at > expires_at:
        fail("ATTENDED_MULTIPLAYER_ATTESTATION_NOT_VALID_AT_REFERENCE_TIME")

    phrase_digest = sha256_bytes(confirmation_phrase(str(evidence["runId"])).encode("utf-8"))
    if attestation.get("confirmationPhraseSha256") != phrase_digest:
        fail("ATTENDED_MULTIPLAYER_CONFIRMATION_DIGEST_MISMATCH")
    expected_literals: dict[str, object] = {
        "operatorIdentitySource": "windows-current-principal",
        "operatorIdentityCryptographicallyVerified": False,
        "explorerInSameSession": True,
        "interactiveDesktop": True,
        "confirmationMatched": True,
        "operatorAttendanceAttested": True,
        "operatorObservedCompleteRun": True,
        "automated": False,
        "humanVisualApprovalClaimed": False,
        "humanGameFeelApprovalClaimed": False,
        "physicalControllerCertified": False,
        "realNetworkConditionsCertified": False,
        "releaseApprovalClaimed": False,
        "sourceMutationAuthority": False,
        "deploymentAuthority": False,
        "publicationAuthority": False,
    }
    for field, expected in expected_literals.items():
        if attestation.get(field) != expected:
            fail("ATTENDED_MULTIPLAYER_ATTESTATION_AUTHORITY_INVALID")

    body = _attestation_body(
        evidence=evidence,
        campaign_id=campaign,
        operator_id=operator,
        windows_session_id=evidence["windowsSessionId"],
        attested_at=attested_text,
        expires_at=expires_text,
        confirmation_phrase_sha256=phrase_digest,
    )
    attestation_digest = digest(
        attestation.get("attestationSha256"),
        "ATTENDED_MULTIPLAYER_ATTESTATION_DIGEST_INVALID",
    )
    if attestation_digest != sha256_object(body):
        fail("ATTENDED_MULTIPLAYER_ATTESTATION_DIGEST_MISMATCH")
    expected_reference = (
        "evavo-attended-multiplayer-operator-attestation:sha256:" + attestation_digest
    )
    if attestation.get("attestationReference") != expected_reference:
        fail("ATTENDED_MULTIPLAYER_ATTESTATION_REFERENCE_INVALID")
    return attestation

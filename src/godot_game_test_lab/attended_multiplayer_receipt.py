from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .attended_multiplayer_attestation import verify_operator_attestation
from .attended_multiplayer_common import (
    PRODUCER_REPOSITORY,
    RECEIPT_CONTRACT,
    digest,
    exact_fields,
    exact_timestamp,
    fail,
    is_record,
    sha256_object,
)


def _receipt_body(
    *,
    evidence: dict[str, Any],
    attestation: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    role_evidence = [
        path for role in evidence["roles"] for path in role["requiredEvidence"]
    ]
    return {
        "schemaVersion": 1,
        "contract": RECEIPT_CONTRACT,
        "generatedAt": generated_at,
        "producerRepository": PRODUCER_REPOSITORY,
        "campaignId": attestation["campaignId"],
        "runId": evidence["runId"],
        "labSha": evidence["labSha"],
        "targetSha": evidence["targetSha"],
        "sessionLabel": evidence["sessionLabel"],
        "status": "passed",
        "summary": {
            "bytes": evidence["summaryBytes"],
            "sha256": evidence["summarySha256"],
            "generatedAt": evidence["generatedAt"],
            "durationSeconds": evidence["durationSeconds"],
        },
        "artifacts": {
            "count": evidence["artifactCount"],
            "bytes": evidence["artifactBytes"],
            "inventorySha256": evidence["artifactInventorySha256"],
            "inventoryExact": True,
            "allBytesRehashed": True,
            "requiredRoleEvidence": sorted(set(role_evidence)),
        },
        "desktop": {
            "leaseName": evidence["desktopLeaseName"],
            "windowsSessionId": evidence["windowsSessionId"],
            "interactive": True,
            "explorerInSameSession": True,
        },
        "roles": evidence["roles"],
        "operatorAttestation": {
            "reference": attestation["attestationReference"],
            "sha256": attestation["attestationSha256"],
            "operatorId": attestation["operatorId"],
            "operatorIdentitySource": attestation["operatorIdentitySource"],
            "operatorIdentityCryptographicallyVerified": False,
            "attestedAt": attestation["attestedAt"],
            "expiresAt": attestation["expiresAt"],
            "attendanceOnly": True,
        },
        "sourceVerification": {
            "summaryReopened": True,
            "artifactInventoryRebuilt": True,
            "artifactBytesRehashed": True,
            "targetMutationDetected": False,
        },
        "authority": {
            "deterministicReleaseVerdictAuthority": False,
            "humanVisualApprovalClaimed": False,
            "humanGameFeelApprovalClaimed": False,
            "physicalControllerCertified": False,
            "realNetworkConditionsCertified": False,
            "completeGameplayCoverageClaimed": False,
            "releaseApprovalClaimed": False,
            "sourceMutationAuthority": False,
            "deploymentAuthority": False,
            "publicationAuthority": False,
        },
        "truthBoundary": (
            "This receipt proves exact attended synthetic multiplayer journeys and retained "
            "evidence for one exact Lab and target revision. It does not prove physical "
            "controllers, real network conditions, complete gameplay coverage, human game "
            "feel, release approval, source mutation, deployment or publication."
        ),
    }


def compile_attended_multiplayer_receipt(
    *,
    evidence: dict[str, Any],
    attestation: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    instant = (now or datetime.now(UTC)).astimezone(UTC)
    verified_attestation = verify_operator_attestation(
        attestation,
        evidence=evidence,
        reference_time=instant,
    )
    body = _receipt_body(
        evidence=evidence,
        attestation=verified_attestation,
        generated_at=instant.isoformat(),
    )
    receipt_digest = sha256_object(body)
    return {
        **body,
        "receiptSha256": receipt_digest,
        "receiptReference": (
            "evavo-attended-multiplayer-receipt:sha256:" + receipt_digest
        ),
    }


def verify_attended_multiplayer_receipt(
    value: object,
    *,
    evidence: dict[str, Any],
    attestation: dict[str, Any],
) -> dict[str, Any]:
    if not is_record(value):
        fail("ATTENDED_MULTIPLAYER_RECEIPT_INVALID")
    receipt = dict(value)
    generated_text, generated_at = exact_timestamp(
        receipt.get("generatedAt"),
        "ATTENDED_MULTIPLAYER_RECEIPT_GENERATED_AT_INVALID",
    )
    verified_attestation = verify_operator_attestation(
        attestation,
        evidence=evidence,
        reference_time=generated_at,
    )
    expected_body = _receipt_body(
        evidence=evidence,
        attestation=verified_attestation,
        generated_at=generated_text,
    )
    exact_fields(
        receipt,
        set(expected_body) | {"receiptSha256", "receiptReference"},
        "ATTENDED_MULTIPLAYER_RECEIPT_FIELDS_INVALID",
    )
    if any(receipt.get(field) != item for field, item in expected_body.items()):
        fail("ATTENDED_MULTIPLAYER_RECEIPT_SOURCE_MISMATCH")
    receipt_digest = digest(
        receipt.get("receiptSha256"),
        "ATTENDED_MULTIPLAYER_RECEIPT_DIGEST_INVALID",
    )
    if receipt_digest != sha256_object(expected_body):
        fail("ATTENDED_MULTIPLAYER_RECEIPT_DIGEST_MISMATCH")
    expected_reference = (
        "evavo-attended-multiplayer-receipt:sha256:" + receipt_digest
    )
    if receipt.get("receiptReference") != expected_reference:
        fail("ATTENDED_MULTIPLAYER_RECEIPT_REFERENCE_INVALID")
    return receipt

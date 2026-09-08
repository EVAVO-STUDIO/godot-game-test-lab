from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .attended_multiplayer_attestation import verify_operator_attestation
from .attended_multiplayer_common import (
    PRODUCER_REPOSITORY,
    RECEIPT_CONTRACT,
    RECEIPT_CONTRACT_V1,
    digest,
    exact_fields,
    exact_timestamp,
    fail,
    is_record,
    sha256_object,
)


def _base_receipt_body(
    *,
    evidence: dict[str, Any],
    attestation: dict[str, Any],
    generated_at: str,
    schema_version: int,
    contract: str,
) -> dict[str, Any]:
    role_evidence = [
        path for role in evidence["roles"] for path in role["requiredEvidence"]
    ]
    return {
        "schemaVersion": schema_version,
        "contract": contract,
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
            "boundSummarySha256": attestation["summarySha256"],
            "boundArtifactInventorySha256": attestation["artifactInventorySha256"],
            "boundArtifactCount": attestation["artifactCount"],
            "boundArtifactBytes": attestation["artifactBytes"],
        },
        "sourceVerification": {
            "summaryReopened": True,
            "artifactInventoryRebuilt": True,
            "artifactBytesRehashed": True,
            "operatorAttestationBoundToExactEvidence": True,
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
    }


def _receipt_body_v1(
    *,
    evidence: dict[str, Any],
    attestation: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    body = _base_receipt_body(
        evidence=evidence,
        attestation=attestation,
        generated_at=generated_at,
        schema_version=1,
        contract=RECEIPT_CONTRACT_V1,
    )
    body["truthBoundary"] = (
        "This receipt proves exact attended synthetic multiplayer journeys and retained "
        "evidence for one exact Lab and target revision. The operator attendance attestation "
        "is bound to the exact summary digest and rehashed artifact inventory. It does not "
        "prove physical controllers, real network conditions, complete gameplay coverage, "
        "human game feel, release approval, source mutation, deployment or publication."
    )
    return body


def _verified_peer_exchange(evidence: dict[str, Any]) -> dict[str, Any]:
    value = evidence.get("peerExchange")
    if not is_record(value):
        fail("ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_REQUIRED")
    peer_exchange = dict(value)
    exact_fields(
        peer_exchange,
        {
            "schemaVersion",
            "configured",
            "proven",
            "requiredRoleCount",
            "authorityObserved",
            "dynamicCaptureRoleCount",
            "roles",
            "findings",
            "truthBoundary",
        },
        "ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_FIELDS_INVALID",
    )
    if peer_exchange.get("schemaVersion") != 1:
        fail("ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_SCHEMA_INVALID")
    configured = peer_exchange.get("configured")
    proven = peer_exchange.get("proven")
    authority_observed = peer_exchange.get("authorityObserved")
    if not isinstance(configured, bool) or not isinstance(proven, bool):
        fail("ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_STATUS_INVALID")
    if not isinstance(authority_observed, bool):
        fail("ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_AUTHORITY_INVALID")
    if proven and not configured:
        fail("ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_PROOF_WITHOUT_CONFIG")
    if configured and not proven:
        fail("ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_NOT_PROVEN")
    required_role_count = peer_exchange.get("requiredRoleCount")
    if (
        not isinstance(required_role_count, int)
        or isinstance(required_role_count, bool)
        or not 0 <= required_role_count <= 8
    ):
        fail("ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_ROLE_COUNT_INVALID")
    dynamic_capture_role_count = peer_exchange.get("dynamicCaptureRoleCount")
    if (
        not isinstance(dynamic_capture_role_count, int)
        or isinstance(dynamic_capture_role_count, bool)
        or not 0 <= dynamic_capture_role_count <= required_role_count
    ):
        fail("ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_DYNAMIC_CAPTURE_COUNT_INVALID")
    roles = peer_exchange.get("roles")
    findings = peer_exchange.get("findings")
    truth_boundary = peer_exchange.get("truthBoundary")
    if not isinstance(roles, list) or len(roles) > 8:
        fail("ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_ROLES_INVALID")
    if not isinstance(findings, list) or findings:
        fail("ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_FINDINGS_PRESENT")
    if not isinstance(truth_boundary, str) or not truth_boundary:
        fail("ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_BOUNDARY_INVALID")
    if configured and len(roles) != required_role_count:
        fail("ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_ROLE_EVIDENCE_INCOMPLETE")
    if not configured and roles:
        fail("ATTENDED_MULTIPLAYER_RECEIPT_PEER_EXCHANGE_UNCONFIGURED_ROLES_PRESENT")
    # dynamicCaptureRoleCount is runtime verifier observability, not part of the stable
    # attended receipt v2 wire contract. Validate it above, then strip it so existing
    # v2 receipts remain verifiable byte-for-byte against their original schema.
    peer_exchange.pop("dynamicCaptureRoleCount", None)
    return peer_exchange


def _receipt_body(
    *,
    evidence: dict[str, Any],
    attestation: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    peer_exchange = _verified_peer_exchange(evidence)
    body = _base_receipt_body(
        evidence=evidence,
        attestation=attestation,
        generated_at=generated_at,
        schema_version=2,
        contract=RECEIPT_CONTRACT,
    )
    body["peerExchange"] = peer_exchange
    body["sourceVerification"]["peerExchangeContractReverified"] = True
    body["authority"]["transportPathCertified"] = False
    body["truthBoundary"] = (
        "This receipt proves exact attended synthetic multiplayer journeys and retained "
        "evidence for one exact Lab and target revision. The operator attendance attestation "
        "is bound to the exact summary digest and rehashed artifact inventory. When "
        "peerExchange.proven is true, it additionally proves that configured game-owned "
        "metadata assertions reported one shared session, unique local peer ids and reciprocal "
        "peer observation for the required roles. It does not prove physical controllers, "
        "transport causality, hostile or real-world network conditions, complete gameplay "
        "coverage, human game feel, release approval, source mutation, deployment or publication."
    )
    return body


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
    schema_version = receipt.get("schemaVersion")
    contract = receipt.get("contract")
    if schema_version == 1 and contract == RECEIPT_CONTRACT_V1:
        expected_body = _receipt_body_v1(
            evidence=evidence,
            attestation=verified_attestation,
            generated_at=generated_text,
        )
    elif schema_version == 2 and contract == RECEIPT_CONTRACT:
        expected_body = _receipt_body(
            evidence=evidence,
            attestation=verified_attestation,
            generated_at=generated_text,
        )
    else:
        fail("ATTENDED_MULTIPLAYER_RECEIPT_SCHEMA_OR_CONTRACT_UNSUPPORTED")
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
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .attended_multiplayer_common import (
    AttendedMultiplayerError,
    assert_no_symlink_chain,
    digest,
    exact_sha,
    load_json_bytes,
    positive_int,
    safe_id,
    safe_relative_path,
)
from .authority_peer_exchange import (
    AuthorityPeerExchangeError,
    verify_authority_peer_exchange,
)

_NODE_RE = re.compile(r"^v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
_MANIFEST_FIELDS = {
    "schemaVersion",
    "kind",
    "status",
    "runId",
    "testLab",
    "target",
    "nodeVersion",
    "emitter",
    "receipt",
    "verifier",
    "sourceUnchanged",
}
_REPOSITORY_FIELDS = {"sha", "branch", "dirty"}
_EMITTER_FIELDS = {"relativePath", "marker", "markerOccurrences"}
_RECEIPT_FIELDS = {"path", "sha256", "bytes"}
_VERIFIER_V2_FIELDS = {
    "marker",
    "markerOccurrences",
    "proven",
    "privacySafe",
    "stablePeerMapping",
    "requiredRoleCount",
    "gameId",
    "authority",
    "protocol",
    "sessionId",
}
_VERIFIER_V3_FIELDS = _VERIFIER_V2_FIELDS | {
    "receiptSchemaVersion",
    "authoritySafetyProven",
    "authorityLifecycleProven",
    "transportProven",
    "browserTransportProven",
}
_VERIFIER_V4_FIELDS = _VERIFIER_V3_FIELDS | {
    "staleSocketInboundRejectedProven",
}
_EMITTER_MARKER = "EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS"
_VERIFIER_MARKER_RE = re.compile(r"^EVAVO_AUTHORITY_PEER_EXCHANGE=PASS roles=(?P<roles>\d+)$")
_MAX_MANIFEST_BYTES = 128 * 1024


class AuthorityPeerExchangeAcceptanceError(ValueError):
    """Raised when a retained authority acceptance manifest is inadmissible."""


def _fail(message: str) -> None:
    raise AuthorityPeerExchangeAcceptanceError(message)


def _exact_fields(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        _fail(f"{label} fields are invalid")
    return dict(value)


def _repository(value: object, label: str) -> dict[str, Any]:
    record = _exact_fields(value, _REPOSITORY_FIELDS, label)
    try:
        sha = exact_sha(record.get("sha"), f"AUTHORITY_PEER_EXCHANGE_{label.upper()}_SHA_INVALID")
    except AttendedMultiplayerError as error:
        raise AuthorityPeerExchangeAcceptanceError(str(error)) from error
    if record.get("branch") != "main":
        _fail(f"{label} branch must be main")
    if record.get("dirty") is not False:
        _fail(f"{label} must be recorded clean")
    return {"sha": sha, "branch": "main", "dirty": False}


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_authority_peer_exchange_acceptance(manifest_path: Path) -> dict[str, Any]:
    try:
        requested = assert_no_symlink_chain(manifest_path)
        resolved_manifest = requested.resolve(strict=True)
        size = resolved_manifest.stat().st_size
    except (OSError, AttendedMultiplayerError) as error:
        raise AuthorityPeerExchangeAcceptanceError("authority acceptance manifest is unreadable") from error
    if not resolved_manifest.is_file() or resolved_manifest.is_symlink() or not 2 <= size <= _MAX_MANIFEST_BYTES:
        _fail("authority acceptance manifest size is invalid")
    try:
        manifest, raw_manifest, loaded_manifest = load_json_bytes(
            resolved_manifest, "AUTHORITY_PEER_EXCHANGE_ACCEPTANCE"
        )
    except AttendedMultiplayerError as error:
        raise AuthorityPeerExchangeAcceptanceError(str(error)) from error
    if loaded_manifest != resolved_manifest or len(raw_manifest) != size:
        _fail("authority acceptance manifest changed during verification")
    if set(manifest) != _MANIFEST_FIELDS:
        _fail("authority acceptance manifest fields are invalid")

    manifest_schema = manifest.get("schemaVersion")
    if manifest_schema == "2.0":
        acceptance_schema = 2
        verifier_fields = _VERIFIER_V2_FIELDS
    elif manifest_schema == "3.0":
        acceptance_schema = 3
        verifier_fields = _VERIFIER_V3_FIELDS
    elif manifest_schema == "4.0":
        acceptance_schema = 4
        verifier_fields = _VERIFIER_V4_FIELDS
    else:
        _fail("authority acceptance manifest schemaVersion must be 2.0, 3.0, or 4.0")

    if manifest.get("kind") != "evavo-authority-peer-exchange-acceptance" or manifest.get("status") != "passed":
        _fail("authority acceptance manifest status or kind is invalid")
    try:
        run_id = safe_id(manifest.get("runId"), "AUTHORITY_PEER_EXCHANGE_ACCEPTANCE_RUN_ID_INVALID")
    except AttendedMultiplayerError as error:
        raise AuthorityPeerExchangeAcceptanceError(str(error)) from error

    test_lab = _repository(manifest.get("testLab"), "testLab")
    target = _repository(manifest.get("target"), "target")
    if manifest.get("sourceUnchanged") is not True:
        _fail("authority acceptance did not record unchanged source")

    node_version = manifest.get("nodeVersion")
    match = _NODE_RE.fullmatch(node_version) if isinstance(node_version, str) else None
    if match is None or int(match.group("major")) < 20:
        _fail("authority acceptance Node.js version is invalid")

    emitter = _exact_fields(manifest.get("emitter"), _EMITTER_FIELDS, "emitter")
    try:
        emitter_path = safe_relative_path(
            emitter.get("relativePath"), "AUTHORITY_PEER_EXCHANGE_ACCEPTANCE_EMITTER_PATH_INVALID"
        )
    except AttendedMultiplayerError as error:
        raise AuthorityPeerExchangeAcceptanceError(str(error)) from error
    if not emitter_path.endswith(".mjs"):
        _fail("authority acceptance emitter must be an mjs source path")
    if emitter.get("marker") != _EMITTER_MARKER or emitter.get("markerOccurrences") != 1:
        _fail("authority acceptance emitter marker evidence is invalid")

    receipt = _exact_fields(manifest.get("receipt"), _RECEIPT_FIELDS, "receipt")
    try:
        receipt_relative = safe_relative_path(
            receipt.get("path"), "AUTHORITY_PEER_EXCHANGE_ACCEPTANCE_RECEIPT_PATH_INVALID"
        )
        declared_digest = digest(
            receipt.get("sha256"), "AUTHORITY_PEER_EXCHANGE_ACCEPTANCE_RECEIPT_DIGEST_INVALID"
        )
        declared_bytes = positive_int(
            receipt.get("bytes"), "AUTHORITY_PEER_EXCHANGE_ACCEPTANCE_RECEIPT_BYTES_INVALID", 128 * 1024
        )
    except AttendedMultiplayerError as error:
        raise AuthorityPeerExchangeAcceptanceError(str(error)) from error
    if receipt_relative != "authority-peer-exchange.json":
        _fail("authority acceptance receipt path is not canonical")

    run_root = assert_no_symlink_chain(resolved_manifest.parent).resolve(strict=True)
    receipt_path = assert_no_symlink_chain(run_root / receipt_relative).resolve(strict=True)
    try:
        receipt_path.relative_to(run_root)
    except ValueError as error:
        raise AuthorityPeerExchangeAcceptanceError("authority acceptance receipt escapes run root") from error
    if not receipt_path.is_file() or receipt_path.is_symlink():
        _fail("authority acceptance receipt file is invalid")
    actual_bytes = receipt_path.stat().st_size
    if actual_bytes != declared_bytes:
        _fail("authority acceptance receipt byte count disagrees with retained file")
    if _sha256_file(receipt_path) != declared_digest:
        _fail("authority acceptance receipt digest disagrees with retained file")

    try:
        verified = verify_authority_peer_exchange(receipt_path)
    except AuthorityPeerExchangeError as error:
        raise AuthorityPeerExchangeAcceptanceError(str(error)) from error

    if acceptance_schema >= 3:
        if verified["receiptSchemaVersion"] < 2 or verified["authoritySafetyProven"] is not True:
            _fail("authority acceptance v3+ requires a receipt v2 authority-safety proof")
        if verified["authorityLifecycleProven"] is not True:
            _fail("authority acceptance v3+ requires authority lifecycle proof")
        if verified["transportProven"] is not False or verified["browserTransportProven"] is not False:
            _fail("authority acceptance v3+ cannot escalate authority evidence into transport proof")
    if acceptance_schema >= 4:
        if verified["receiptSchemaVersion"] < 3 or verified["staleSocketInboundRejectedProven"] is not True:
            _fail("authority acceptance v4 requires receipt v3 stale inbound-message rejection proof")

    verifier = _exact_fields(manifest.get("verifier"), verifier_fields, "verifier")
    marker = verifier.get("marker")
    marker_match = _VERIFIER_MARKER_RE.fullmatch(marker) if isinstance(marker, str) else None
    if marker_match is None or verifier.get("markerOccurrences") != 1:
        _fail("authority acceptance verifier marker evidence is invalid")
    if int(marker_match.group("roles")) != verified["requiredRoleCount"]:
        _fail("authority acceptance verifier marker role count disagrees with receipt")

    comparisons: dict[str, object] = {
        "proven": True,
        "privacySafe": True,
        "stablePeerMapping": True,
        "requiredRoleCount": verified["requiredRoleCount"],
        "gameId": verified["gameId"],
        "authority": verified["authority"],
        "protocol": verified["protocol"],
        "sessionId": verified["sessionId"],
    }
    if acceptance_schema >= 3:
        comparisons.update(
            {
                "receiptSchemaVersion": verified["receiptSchemaVersion"],
                "authoritySafetyProven": True,
                "authorityLifecycleProven": True,
                "transportProven": False,
                "browserTransportProven": False,
            }
        )
    if acceptance_schema >= 4:
        comparisons["staleSocketInboundRejectedProven"] = True
    for key, expected in comparisons.items():
        if verifier.get(key) != expected:
            _fail(f"authority acceptance verifier claim disagrees with retained receipt: {key}")

    return {
        "schemaVersion": 1,
        "acceptanceSchemaVersion": acceptance_schema,
        "receiptSchemaVersion": verified["receiptSchemaVersion"],
        "proven": True,
        "authorityLifecycleProven": verified["authorityLifecycleProven"],
        "authoritySafetyProven": verified["authoritySafetyProven"],
        "staleSocketInboundRejectedProven": verified["staleSocketInboundRejectedProven"],
        "transportProven": False,
        "browserTransportProven": False,
        "runId": run_id,
        "testLabSha": test_lab["sha"],
        "targetSha": target["sha"],
        "gameId": verified["gameId"],
        "authority": verified["authority"],
        "protocol": verified["protocol"],
        "requiredRoleCount": verified["requiredRoleCount"],
        "receiptSha256": declared_digest,
        "sourceBound": True,
        "privacySafe": True,
        "stablePeerMapping": True,
        "truthBoundary": (
            "This verifies a retained server-authority lifecycle receipt against its exact bytes "
            "and binds the accepted result to clean main-branch target and Test Lab SHAs recorded "
            "by the runner. Acceptance v3 binds outbound stale-socket authority safety; acceptance "
            "v4 additionally requires receipt-v3 stale inbound-message rejection evidence. It "
            "still does not prove a browser or native client traversed the production transport path."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a retained EVAVO authority peer-exchange acceptance manifest."
    )
    parser.add_argument("manifest", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_authority_peer_exchange_acceptance(args.manifest)
    except AuthorityPeerExchangeAcceptanceError as error:
        print(f"EVAVO_AUTHORITY_PEER_EXCHANGE_ACCEPTANCE_VERIFY=FAIL reason={error}")
        return 1
    print(json.dumps(result, sort_keys=True))
    print(
        "EVAVO_AUTHORITY_PEER_EXCHANGE_ACCEPTANCE_VERIFY=PASS "
        f"target_sha={result['targetSha']} lab_sha={result['testLabSha']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
from .authority_peer_exchange_crosscheck import (
    AuthorityPeerExchangeCrosscheckError,
    verify_authority_peer_exchange_crosscheck,
)

_NODE_RE = re.compile(r"^v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
_BUNDLE_MARKER_RE = re.compile(
    r"^EVAVO_AUTHORITY_TEST_LAB_PEER_EXCHANGE_BUNDLE=PASS required_roles=(?P<roles>\d+) output=(?P<output>.+)$"
)
_VERIFIER_MARKER_RE = re.compile(
    r"^EVAVO_AUTHORITY_PEER_EXCHANGE_CROSSCHECK=PASS roles=(?P<roles>\d+)$"
)
_MANIFEST_FIELDS = {
    "schemaVersion",
    "kind",
    "status",
    "runId",
    "testLab",
    "target",
    "nodeVersion",
    "emitter",
    "verifier",
    "evidence",
    "sourceUnchanged",
    "truthBoundary",
}
_REPOSITORY_FIELDS = {"sha", "branch", "dirty"}
_EMITTER_FIELDS = {"relativePath", "marker", "markerOccurrences", "requiredRoleCount"}
_VERIFIER_FIELDS = {
    "marker",
    "markerOccurrences",
    "requiredRoleCount",
    "dynamicCaptureRoleCount",
    "semanticViewsAgree",
    "authorityLifecycleProven",
    "authoritySafetyProven",
    "standardPeerExchangeProven",
    "transportProven",
    "browserTransportProven",
}
_EVIDENCE_FIELDS = {"authorityReceiptSha256", "profileSha256", "summarySha256"}
_EVIDENCE_FILES = {
    "authorityReceiptSha256": "authority-peer-exchange-lifecycle.json",
    "profileSha256": "profile.normalized.json",
    "summarySha256": "multiplayer-agent-summary.json",
}
_MAX_MANIFEST_BYTES = 128 * 1024
_MAX_TRUTH_BYTES = 4096


class AuthorityPeerExchangeCrosscheckAcceptanceError(ValueError):
    """Raised when a retained semantic crosscheck acceptance is inadmissible."""


def _fail(message: str) -> None:
    raise AuthorityPeerExchangeCrosscheckAcceptanceError(message)


def _exact_fields(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        _fail(f"{label} fields are invalid")
    return dict(value)


def _repository(value: object, label: str) -> dict[str, Any]:
    record = _exact_fields(value, _REPOSITORY_FIELDS, label)
    try:
        sha = exact_sha(record.get("sha"), f"AUTHORITY_CROSSCHECK_{label.upper()}_SHA_INVALID")
    except AttendedMultiplayerError as error:
        raise AuthorityPeerExchangeCrosscheckAcceptanceError(str(error)) from error
    if record.get("branch") != "main" or record.get("dirty") is not False:
        _fail(f"{label} must record a clean main checkout")
    return {"sha": sha, "branch": "main", "dirty": False}


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve(strict=True))) == os.path.normcase(str(right.resolve(strict=True)))


def verify_authority_peer_exchange_crosscheck_acceptance(manifest_path: Path) -> dict[str, Any]:
    try:
        requested = assert_no_symlink_chain(manifest_path)
        resolved_manifest = requested.resolve(strict=True)
        size = resolved_manifest.stat().st_size
    except (OSError, AttendedMultiplayerError) as error:
        raise AuthorityPeerExchangeCrosscheckAcceptanceError(
            "authority crosscheck acceptance manifest is unreadable"
        ) from error
    if not resolved_manifest.is_file() or resolved_manifest.is_symlink() or not 2 <= size <= _MAX_MANIFEST_BYTES:
        _fail("authority crosscheck acceptance manifest size is invalid")
    try:
        manifest, raw_manifest, loaded_manifest = load_json_bytes(
            resolved_manifest, "AUTHORITY_PEER_EXCHANGE_CROSSCHECK_ACCEPTANCE"
        )
    except AttendedMultiplayerError as error:
        raise AuthorityPeerExchangeCrosscheckAcceptanceError(str(error)) from error
    if loaded_manifest != resolved_manifest or len(raw_manifest) != size:
        _fail("authority crosscheck acceptance manifest changed during verification")
    if set(manifest) != _MANIFEST_FIELDS:
        _fail("authority crosscheck acceptance manifest fields are invalid")
    if (
        manifest.get("schemaVersion") != "1.0"
        or manifest.get("kind") != "evavo-authority-peer-exchange-semantic-crosscheck"
        or manifest.get("status") != "passed"
    ):
        _fail("authority crosscheck acceptance schema, kind, or status is invalid")
    try:
        run_id = safe_id(manifest.get("runId"), "AUTHORITY_CROSSCHECK_RUN_ID_INVALID")
    except AttendedMultiplayerError as error:
        raise AuthorityPeerExchangeCrosscheckAcceptanceError(str(error)) from error

    test_lab = _repository(manifest.get("testLab"), "testLab")
    target = _repository(manifest.get("target"), "target")
    if manifest.get("sourceUnchanged") is not True:
        _fail("authority crosscheck acceptance did not record unchanged source")

    node_version = manifest.get("nodeVersion")
    node_match = _NODE_RE.fullmatch(node_version) if isinstance(node_version, str) else None
    if node_match is None or int(node_match.group("major")) < 20:
        _fail("authority crosscheck acceptance Node.js version is invalid")

    run_root = assert_no_symlink_chain(resolved_manifest.parent).resolve(strict=True)
    bundle_root = assert_no_symlink_chain(run_root / "bundle").resolve(strict=True)
    if not bundle_root.is_dir() or bundle_root.is_symlink():
        _fail("authority crosscheck acceptance bundle directory is invalid")

    emitter = _exact_fields(manifest.get("emitter"), _EMITTER_FIELDS, "emitter")
    try:
        emitter_path = safe_relative_path(
            emitter.get("relativePath"), "AUTHORITY_CROSSCHECK_EMITTER_PATH_INVALID"
        )
        emitter_roles = positive_int(
            emitter.get("requiredRoleCount"), "AUTHORITY_CROSSCHECK_EMITTER_ROLE_COUNT_INVALID", 32
        )
    except AttendedMultiplayerError as error:
        raise AuthorityPeerExchangeCrosscheckAcceptanceError(str(error)) from error
    if not emitter_path.endswith(".mjs") or emitter.get("markerOccurrences") != 1:
        _fail("authority crosscheck emitter evidence is invalid")
    marker = emitter.get("marker")
    marker_match = _BUNDLE_MARKER_RE.fullmatch(marker) if isinstance(marker, str) else None
    if marker_match is None or int(marker_match.group("roles")) != emitter_roles:
        _fail("authority crosscheck emitter marker evidence is invalid")
    try:
        marker_output = Path(marker_match.group("output"))
        if not _same_path(marker_output, bundle_root):
            _fail("authority crosscheck emitter marker output does not identify retained bundle")
    except OSError as error:
        raise AuthorityPeerExchangeCrosscheckAcceptanceError(
            "authority crosscheck emitter output path is invalid"
        ) from error

    verifier = _exact_fields(manifest.get("verifier"), _VERIFIER_FIELDS, "verifier")
    verifier_marker = verifier.get("marker")
    verifier_match = (
        _VERIFIER_MARKER_RE.fullmatch(verifier_marker) if isinstance(verifier_marker, str) else None
    )
    if verifier_match is None or verifier.get("markerOccurrences") != 1:
        _fail("authority crosscheck verifier marker evidence is invalid")
    try:
        verifier_roles = positive_int(
            verifier.get("requiredRoleCount"), "AUTHORITY_CROSSCHECK_VERIFIER_ROLE_COUNT_INVALID", 32
        )
        dynamic_roles = positive_int(
            verifier.get("dynamicCaptureRoleCount"), "AUTHORITY_CROSSCHECK_DYNAMIC_ROLE_COUNT_INVALID", 32
        )
    except AttendedMultiplayerError as error:
        raise AuthorityPeerExchangeCrosscheckAcceptanceError(str(error)) from error
    if int(verifier_match.group("roles")) != verifier_roles or emitter_roles != verifier_roles:
        _fail("authority crosscheck role counts disagree")
    expected_verifier_flags = {
        "semanticViewsAgree": True,
        "authorityLifecycleProven": True,
        "authoritySafetyProven": True,
        "standardPeerExchangeProven": True,
        "transportProven": False,
        "browserTransportProven": False,
    }
    for key, expected in expected_verifier_flags.items():
        if verifier.get(key) is not expected:
            _fail(f"authority crosscheck verifier claim is invalid: {key}")
    if dynamic_roles != verifier_roles:
        _fail("authority crosscheck requires dynamic capture for every required role")

    evidence = _exact_fields(manifest.get("evidence"), _EVIDENCE_FIELDS, "evidence")
    before_hashes: dict[str, str] = {}
    for key, filename in _EVIDENCE_FILES.items():
        try:
            declared = digest(evidence.get(key), f"AUTHORITY_CROSSCHECK_{key.upper()}_INVALID")
        except AttendedMultiplayerError as error:
            raise AuthorityPeerExchangeCrosscheckAcceptanceError(str(error)) from error
        path = assert_no_symlink_chain(bundle_root / filename).resolve(strict=True)
        try:
            path.relative_to(bundle_root)
        except ValueError as error:
            raise AuthorityPeerExchangeCrosscheckAcceptanceError(
                "authority crosscheck evidence escapes bundle root"
            ) from error
        if not path.is_file() or path.is_symlink():
            _fail(f"authority crosscheck evidence file is invalid: {filename}")
        actual = _sha256_file(path)
        if actual != declared:
            _fail(f"authority crosscheck evidence digest disagrees with retained file: {filename}")
        before_hashes[filename] = actual

    try:
        verified = verify_authority_peer_exchange_crosscheck(bundle_root)
    except AuthorityPeerExchangeCrosscheckError as error:
        raise AuthorityPeerExchangeCrosscheckAcceptanceError(str(error)) from error

    for filename, before in before_hashes.items():
        if _sha256_file(bundle_root / filename) != before:
            _fail(f"authority crosscheck evidence changed during verification: {filename}")

    comparisons: dict[str, object] = {
        "requiredRoleCount": verifier_roles,
        "dynamicCaptureRoleCount": dynamic_roles,
        "semanticViewsAgree": True,
        "authorityLifecycleProven": True,
        "authoritySafetyProven": True,
        "standardPeerExchangeProven": True,
        "transportProven": False,
        "browserTransportProven": False,
    }
    for key, expected in comparisons.items():
        if verified.get(key) != expected:
            _fail(f"authority crosscheck verifier claim disagrees with retained evidence: {key}")

    truth_boundary = manifest.get("truthBoundary")
    if (
        not isinstance(truth_boundary, str)
        or truth_boundary != truth_boundary.strip()
        or not truth_boundary
        or len(truth_boundary.encode("utf-8")) > _MAX_TRUTH_BYTES
        or truth_boundary != verified.get("truthBoundary")
    ):
        _fail("authority crosscheck truth boundary disagrees with retained verification")

    return {
        "schemaVersion": 1,
        "acceptanceSchemaVersion": 1,
        "proven": True,
        "semanticViewsAgree": True,
        "authorityLifecycleProven": True,
        "authoritySafetyProven": True,
        "standardPeerExchangeProven": True,
        "dynamicCaptureRoleCount": dynamic_roles,
        "transportProven": False,
        "browserTransportProven": False,
        "runId": run_id,
        "testLabSha": test_lab["sha"],
        "targetSha": target["sha"],
        "requiredRoleCount": verifier_roles,
        "gameId": verified.get("gameId"),
        "authority": verified.get("authority"),
        "protocol": verified.get("protocol"),
        "sessionId": verified.get("sessionId"),
        "evidenceBound": True,
        "sourceBound": True,
        "truthBoundary": (
            "This independently reopens the retained authority/Test Lab semantic bundle, verifies "
            "its exact evidence digests, reruns both semantic verifiers, and binds the result to "
            "clean main-branch SHAs recorded by the runner. It still does not prove browser or "
            "native production-transport traversal."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a retained authority peer-exchange semantic crosscheck acceptance."
    )
    parser.add_argument("manifest", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_authority_peer_exchange_crosscheck_acceptance(args.manifest)
    except (AuthorityPeerExchangeCrosscheckAcceptanceError, OSError, ValueError) as error:
        print(f"EVAVO_AUTHORITY_PEER_EXCHANGE_CROSSCHECK_ACCEPTANCE_VERIFY=FAIL reason={error}")
        return 1
    print(json.dumps(result, sort_keys=True))
    print(
        "EVAVO_AUTHORITY_PEER_EXCHANGE_CROSSCHECK_ACCEPTANCE_VERIFY=PASS "
        f"target_sha={result['targetSha']} lab_sha={result['testLabSha']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

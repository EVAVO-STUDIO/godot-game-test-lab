from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .attended_multiplayer_common import (
    AttendedMultiplayerError,
    assert_no_symlink_chain,
    inventory_artifacts,
    is_record,
    load_json_bytes,
    safe_id,
    safe_relative_path,
)

_RESERVED_KEYS = {
    "evavo_peer_session_id",
    "evavo_local_peer_id",
    "evavo_observed_peer_ids",
    "evavo_authority_peer_id",
}
_REQUIRED_KEYS = {
    "evavo_peer_session_id",
    "evavo_local_peer_id",
    "evavo_observed_peer_ids",
}
_RESERVED_ASSERTION_TYPES = {"metadata_capture", "metadata_equals"}
_MAX_ROLES = 8
_MAX_OBSERVED_PEERS = 32
_MAX_SESSION_BYTES = 256
_MAX_PATH_BYTES = 1024


class PeerExchangeEvidenceError(ValueError):
    """Raised when peer-exchange evidence sources are structurally inadmissible."""


def _fail(message: str) -> None:
    raise PeerExchangeEvidenceError(message)


def _positive_peer_id(value: object, label: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > 2**31 - 1
    ):
        _fail(f"{label} must be a positive Godot peer id")
    return value


def _bounded_session(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value.encode("utf-8")) > _MAX_SESSION_BYTES
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        _fail(f"{label} must be a bounded non-empty single-line session id")
    return value


def _bounded_path(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > _MAX_PATH_BYTES
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        _fail(f"{label} must be a bounded node path")
    return value


def _normalize_inventory(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 20_000:
        _fail("summary artifact inventory is invalid")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        if not is_record(raw):
            _fail(f"summary artifact inventory item {index} is invalid")
        item = dict(raw)
        if set(item) != {"path", "bytes", "sha256"}:
            _fail(f"summary artifact inventory item {index} has unexpected fields")
        path = safe_relative_path(
            item.get("path"), "ATTENDED_MULTIPLAYER_PEER_EXCHANGE_ARTIFACT_PATH_INVALID"
        )
        if path in seen:
            _fail("summary artifact inventory contains duplicate paths")
        seen.add(path)
        size = item.get("bytes")
        digest = item.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            _fail("summary artifact inventory contains invalid byte counts")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            _fail("summary artifact inventory contains invalid digests")
        records.append({"path": path, "bytes": size, "sha256": digest})
    return sorted(records, key=lambda record: str(record["path"]).casefold())


def _assertion_records(role: dict[str, Any]) -> dict[int, dict[str, Any]]:
    harness = role.get("harness")
    if not is_record(harness) or harness.get("status") != "passed":
        _fail(f"role {role.get('id')} does not have a passed journey harness")
    raw = harness.get("assertions")
    if not isinstance(raw, list) or len(raw) > 128:
        _fail(f"role {role.get('id')} harness assertions are invalid")
    result: dict[int, dict[str, Any]] = {}
    for item in raw:
        if not is_record(item):
            _fail(f"role {role.get('id')} harness assertion record is invalid")
        record = dict(item)
        index = record.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= 128:
            _fail(f"role {role.get('id')} harness assertion index is invalid")
        if index in result:
            _fail(f"role {role.get('id')} harness assertion index is duplicated")
        result[index] = record
    return result


def _reserved_assertions(journey: dict[str, Any]) -> dict[str, tuple[int, dict[str, Any]]]:
    assertions = journey.get("assertions", [])
    if not isinstance(assertions, list) or len(assertions) > 128:
        _fail("normalized journey assertions are invalid")
    found: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, raw in enumerate(assertions):
        if not is_record(raw):
            _fail("normalized journey assertion must be an object")
        assertion = dict(raw)
        assertion_type = assertion.get("type")
        if assertion_type not in _RESERVED_ASSERTION_TYPES:
            continue
        key = assertion.get("key")
        if key not in _RESERVED_KEYS:
            continue
        if key in found:
            _fail(f"reserved multiplayer assertion is duplicated: {key}")
        _bounded_path(assertion.get("path"), f"{key}.path")
        found[str(key)] = (index, assertion)
    return found


def _accepted_value(
    *,
    role_id: str,
    key: str,
    configured: dict[str, tuple[int, dict[str, Any]]],
    harness: dict[int, dict[str, Any]],
) -> object:
    if key not in configured:
        _fail(f"role {role_id} is missing reserved multiplayer assertion {key}")
    index, assertion = configured[key]
    assertion_type = assertion.get("type")
    observed = harness.get(index)
    if (
        observed is None
        or observed.get("type") != assertion_type
        or observed.get("accepted") is not True
    ):
        _fail(f"role {role_id} did not pass reserved multiplayer assertion {key}")
    if assertion_type == "metadata_capture":
        if "actual" not in observed:
            _fail(f"role {role_id} reserved multiplayer capture {key} has no actual value")
        return observed.get("actual")
    if assertion_type == "metadata_equals":
        return assertion.get("value")
    _fail(f"role {role_id} reserved multiplayer assertion {key} has unsupported type")


def verify_peer_exchange(
    *,
    summary_path: Path,
    artifact_root: Path,
) -> dict[str, Any]:
    summary, _summary_bytes, summary_file = load_json_bytes(summary_path, "PEER_EXCHANGE_SUMMARY")
    root = assert_no_symlink_chain(artifact_root).resolve(strict=True)
    try:
        summary_file.relative_to(root)
    except ValueError as error:
        raise PeerExchangeEvidenceError("multiplayer summary is outside the artifact root") from error
    if summary_file.name != "multiplayer-agent-summary.json":
        _fail("multiplayer summary must be multiplayer-agent-summary.json")
    if summary.get("schemaVersion") != "1.0" or summary.get("status") != "passed":
        _fail("peer-exchange evidence requires a passed multiplayer summary")

    actual_inventory = inventory_artifacts(root)
    declared_inventory = _normalize_inventory(summary.get("artifacts"))
    if actual_inventory != declared_inventory:
        _fail("peer-exchange artifact inventory does not match retained bytes")
    if "profile.normalized.json" not in {str(item["path"]) for item in actual_inventory}:
        _fail("normalized multiplayer profile is missing from retained artifacts")

    profile, _profile_bytes, _ = load_json_bytes(
        root / "profile.normalized.json", "PEER_EXCHANGE_PROFILE"
    )
    if profile.get("schemaVersion") != "1.0":
        _fail("normalized multiplayer profile schema is invalid")
    profile_roles = profile.get("roles")
    summary_roles = summary.get("roles")
    if (
        not isinstance(profile_roles, list)
        or not isinstance(summary_roles, list)
        or not 2 <= len(profile_roles) <= _MAX_ROLES
        or len(profile_roles) != len(summary_roles)
    ):
        _fail("peer-exchange role inventory is invalid")

    profile_by_id: dict[str, dict[str, Any]] = {}
    summary_by_id: dict[str, dict[str, Any]] = {}
    configured_by_id: dict[str, dict[str, tuple[int, dict[str, Any]]]] = {}
    for raw in profile_roles:
        if not is_record(raw):
            _fail("normalized multiplayer profile role is invalid")
        role = dict(raw)
        role_id = safe_id(role.get("id"), "ATTENDED_MULTIPLAYER_PEER_EXCHANGE_ROLE_ID_INVALID")
        if role_id in profile_by_id:
            _fail("normalized multiplayer profile role id is duplicated")
        profile_by_id[role_id] = role
        journey = role.get("journey")
        if journey is None:
            configured_by_id[role_id] = {}
        elif is_record(journey):
            configured_by_id[role_id] = _reserved_assertions(dict(journey))
        else:
            _fail(f"role {role_id} normalized journey is invalid")

    for raw in summary_roles:
        if not is_record(raw):
            _fail("multiplayer summary role is invalid")
        role = dict(raw)
        role_id = safe_id(role.get("id"), "ATTENDED_MULTIPLAYER_PEER_EXCHANGE_ROLE_ID_INVALID")
        if role_id in summary_by_id:
            _fail("multiplayer summary role id is duplicated")
        summary_by_id[role_id] = role
    if set(profile_by_id) != set(summary_by_id):
        _fail("profile and summary multiplayer role ids disagree")

    configured = any(bool(items) for items in configured_by_id.values())
    if not configured:
        return {
            "schemaVersion": 1,
            "configured": False,
            "proven": False,
            "requiredRoleCount": sum(
                1 for role in profile_by_id.values() if role.get("required", True) is True
            ),
            "authorityObserved": False,
            "dynamicCaptureRoleCount": 0,
            "roles": [],
            "findings": [],
            "truthBoundary": (
                "No reserved peer-exchange metadata assertions were configured. Concurrent "
                "client execution must not be described as proof of peer exchange."
            ),
        }

    findings: list[str] = []
    required_ids = [
        role_id
        for role_id, role in profile_by_id.items()
        if role.get("required", True) is True
    ]
    required_ids.sort()
    if len(required_ids) < 2:
        findings.append("fewer than two required roles are available for peer-exchange proof")

    role_evidence: list[dict[str, Any]] = []
    session_values: dict[str, str] = {}
    local_peer_ids: dict[str, int] = {}
    observed_peer_ids: dict[str, list[int]] = {}
    authority_peer_ids: dict[str, int] = {}
    authority_configured_count = 0
    dynamic_capture_role_count = 0

    for role_id in required_ids:
        summary_role = summary_by_id[role_id]
        if summary_role.get("required") is not True or summary_role.get("status") != "passed":
            findings.append(f"required role {role_id} did not pass as required")
            continue
        configured_assertions = configured_by_id[role_id]
        missing = sorted(_REQUIRED_KEYS - set(configured_assertions))
        if missing:
            findings.append(
                f"required role {role_id} is missing reserved assertions: {', '.join(missing)}"
            )
            continue
        try:
            harness = _assertion_records(summary_role)
            capture_keys = sorted(
                key
                for key, (_index, assertion) in configured_assertions.items()
                if assertion.get("type") == "metadata_capture"
            )
            if set(_REQUIRED_KEYS).issubset(capture_keys):
                dynamic_capture_role_count += 1

            session_value = _bounded_session(
                _accepted_value(
                    role_id=role_id,
                    key="evavo_peer_session_id",
                    configured=configured_assertions,
                    harness=harness,
                ),
                f"role {role_id} peer session",
            )
            local_peer = _positive_peer_id(
                _accepted_value(
                    role_id=role_id,
                    key="evavo_local_peer_id",
                    configured=configured_assertions,
                    harness=harness,
                ),
                f"role {role_id} local peer id",
            )
            observed_raw = _accepted_value(
                role_id=role_id,
                key="evavo_observed_peer_ids",
                configured=configured_assertions,
                harness=harness,
            )
            if not isinstance(observed_raw, list) or len(observed_raw) > _MAX_OBSERVED_PEERS:
                _fail(f"role {role_id} observed peer ids must be a bounded array")
            peers = [
                _positive_peer_id(value, f"role {role_id} observed peer id")
                for value in observed_raw
            ]
            if len(set(peers)) != len(peers):
                _fail(f"role {role_id} observed peer ids contain duplicates")
            if local_peer in peers:
                _fail(f"role {role_id} observed peer ids include its local peer id")

            authority_peer: int | None = None
            if "evavo_authority_peer_id" in configured_assertions:
                authority_configured_count += 1
                authority_peer = _positive_peer_id(
                    _accepted_value(
                        role_id=role_id,
                        key="evavo_authority_peer_id",
                        configured=configured_assertions,
                        harness=harness,
                    ),
                    f"role {role_id} authority peer id",
                )
                authority_peer_ids[role_id] = authority_peer

            session_values[role_id] = session_value
            local_peer_ids[role_id] = local_peer
            observed_peer_ids[role_id] = peers
            role_evidence.append(
                {
                    "id": role_id,
                    "sessionId": session_value,
                    "localPeerId": local_peer,
                    "observedPeerIds": peers,
                    "authorityPeerId": authority_peer,
                    "dynamicRequiredMetadataCaptured": set(_REQUIRED_KEYS).issubset(capture_keys),
                    "reservedAssertionsAccepted": True,
                }
            )
        except (PeerExchangeEvidenceError, AttendedMultiplayerError) as error:
            findings.append(str(error))

    if len(session_values) == len(required_ids) and len(set(session_values.values())) != 1:
        findings.append("required roles did not report one shared multiplayer session id")
    if len(local_peer_ids) == len(required_ids):
        if len(set(local_peer_ids.values())) != len(local_peer_ids):
            findings.append("required roles did not report unique local peer ids")
        expected_peer_ids = set(local_peer_ids.values())
        for role_id, local_peer in local_peer_ids.items():
            required_remote_ids = expected_peer_ids - {local_peer}
            observed = set(observed_peer_ids.get(role_id, []))
            if not required_remote_ids.issubset(observed):
                findings.append(
                    f"role {role_id} did not report every other required peer as observed"
                )
        if authority_configured_count == len(required_ids):
            shared_authorities = set(authority_peer_ids.values())
            if len(shared_authorities) == 1:
                shared_authority = next(iter(shared_authorities))
                if shared_authority not in expected_peer_ids:
                    findings.append("shared authority peer id is not a participating required peer")
    if authority_configured_count not in {0, len(required_ids)}:
        findings.append("authority peer evidence is only partially configured across required roles")
    if authority_configured_count == len(required_ids) and len(set(authority_peer_ids.values())) != 1:
        findings.append("required roles did not report one shared authority peer id")

    proven = not findings and len(role_evidence) == len(required_ids)
    return {
        "schemaVersion": 1,
        "configured": True,
        "proven": proven,
        "requiredRoleCount": len(required_ids),
        "authorityObserved": authority_configured_count == len(required_ids) and proven,
        "dynamicCaptureRoleCount": dynamic_capture_role_count,
        "roles": role_evidence,
        "findings": sorted(set(findings)),
        "truthBoundary": (
            "A proven result means the required role journeys all passed game-owned metadata "
            "evidence for one shared session, unique local peer ids, and reciprocal peer "
            "observation. metadata_capture values come from the running game rather than the "
            "profile. Legacy metadata_equals assertions remain supported for fixed-value "
            "contracts. Neither form by itself proves transport causality, hostile-network "
            "resilience, complete authority enforcement, game feel, or release readiness."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m godot_game_test_lab.multiplayer_peer_exchange",
        description="Verify optional cross-role multiplayer peer-exchange evidence.",
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        result = verify_peer_exchange(summary_path=args.summary, artifact_root=args.artifacts)
    except (
        AttendedMultiplayerError,
        PeerExchangeEvidenceError,
        FileNotFoundError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        return 2

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if not result["configured"]:
        print("EVAVO_MULTIPLAYER_PEER_EXCHANGE=NOT_CONFIGURED")
        return 0
    if result["proven"]:
        print(
            "EVAVO_MULTIPLAYER_PEER_EXCHANGE=PASS "
            f"required_roles={result['requiredRoleCount']}"
        )
        return 0
    print(
        "EVAVO_MULTIPLAYER_PEER_EXCHANGE=FAIL "
        f"required_roles={result['requiredRoleCount']}"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

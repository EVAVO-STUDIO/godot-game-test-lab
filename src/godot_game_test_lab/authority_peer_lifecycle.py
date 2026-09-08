from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .peer_exchange_semantics import PeerObservationEvidenceError, verify_peer_observations

_MAX_EVIDENCE_BYTES = 256 * 1024
_MAX_TEXT_BYTES = 256
_ROLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_EXPECTED_PHASES = ("single", "reciprocal", "departure", "reconnect")


class AuthorityPeerLifecycleError(ValueError):
    """Raised when authority-owned peer lifecycle evidence is inadmissible."""


def _fail(message: str) -> None:
    raise AuthorityPeerLifecycleError(message)


def _bounded_text(value: object, label: str, max_bytes: int = _MAX_TEXT_BYTES) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > max_bytes
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        _fail(f"{label} must be bounded non-empty single-line text")
    return value


def _role_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _ROLE_ID.fullmatch(value) is None:
        _fail(f"{label} is invalid")
    return value


def _role(raw: object, label: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        _fail(f"{label} must be an object")
    unexpected = set(raw) - {"id", "sessionId", "localPeerId", "observedPeerIds"}
    if unexpected:
        _fail(f"{label} has unexpected fields: {', '.join(sorted(unexpected))}")

    role_id = _role_id(raw.get("id"), f"{label} id")
    session_id = _bounded_text(raw.get("sessionId"), f"{label} sessionId")
    local_peer_id = raw.get("localPeerId")
    if (
        not isinstance(local_peer_id, int)
        or isinstance(local_peer_id, bool)
        or local_peer_id < 1
        or local_peer_id > 2**31 - 1
    ):
        _fail(f"{label} localPeerId must be a positive peer id")

    observed_raw = raw.get("observedPeerIds")
    if not isinstance(observed_raw, list) or len(observed_raw) > 32:
        _fail(f"{label} observedPeerIds must be a bounded array")
    observed: list[int] = []
    for index, value in enumerate(observed_raw):
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 1
            or value > 2**31 - 1
        ):
            _fail(f"{label} observedPeerIds[{index}] must be a positive peer id")
        observed.append(value)
    if len(set(observed)) != len(observed):
        _fail(f"{label} observedPeerIds contain duplicates")
    if local_peer_id in observed:
        _fail(f"{label} observedPeerIds include its local peer id")

    return {
        "id": role_id,
        "sessionId": session_id,
        "localPeerId": local_peer_id,
        "observedPeerIds": observed,
    }


def _phase(raw: object, expected_id: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        _fail(f"phase {expected_id} must be an object")
    unexpected = set(raw) - {"id", "roles"}
    if unexpected:
        _fail(f"phase {expected_id} has unexpected fields: {', '.join(sorted(unexpected))}")
    if raw.get("id") != expected_id:
        _fail(f"authority lifecycle phase order must be {' -> '.join(_EXPECTED_PHASES)}")
    roles_raw = raw.get("roles")
    if not isinstance(roles_raw, list) or not 1 <= len(roles_raw) <= 8:
        _fail(f"phase {expected_id} roles must contain between one and eight roles")
    roles = [_role(value, f"phase {expected_id} role {index}") for index, value in enumerate(roles_raw)]
    ids = [role["id"] for role in roles]
    if len(set(ids)) != len(ids):
        _fail(f"phase {expected_id} role ids are duplicated")
    return {"id": expected_id, "roles": roles}


def _semantic_phase(phase: Mapping[str, Any], authority: str) -> dict[str, Any]:
    payload = {
        "schemaVersion": "1.0",
        "evidenceClass": "authority-peer-lifecycle-phase",
        "source": authority,
        "roles": [
            {
                "id": role["id"],
                "required": True,
                "sessionId": role["sessionId"],
                "localPeerId": role["localPeerId"],
                "observedPeerIds": list(role["observedPeerIds"]),
            }
            for role in phase["roles"]
        ],
    }
    try:
        return verify_peer_observations(payload)
    except PeerObservationEvidenceError as error:
        raise AuthorityPeerLifecycleError(str(error)) from error


def verify_authority_peer_lifecycle(payload: Mapping[str, object]) -> dict[str, Any]:
    expected_fields = {
        "schemaVersion",
        "kind",
        "gameId",
        "authority",
        "protocol",
        "sessionId",
        "departedRoleId",
        "phases",
        "privacy",
        "truthBoundary",
    }
    unexpected = set(payload) - expected_fields
    missing = expected_fields - set(payload)
    if unexpected or missing:
        details = []
        if missing:
            details.append(f"missing: {', '.join(sorted(missing))}")
        if unexpected:
            details.append(f"unexpected: {', '.join(sorted(unexpected))}")
        _fail("authority peer lifecycle fields are invalid (" + "; ".join(details) + ")")
    if payload.get("schemaVersion") != "1.0":
        _fail("authority peer lifecycle schemaVersion must be 1.0")
    if payload.get("kind") != "evavo-authority-peer-exchange-lifecycle":
        _fail("authority peer lifecycle kind is invalid")

    game_id = _bounded_text(payload.get("gameId"), "gameId")
    authority = _bounded_text(payload.get("authority"), "authority")
    protocol = _bounded_text(payload.get("protocol"), "protocol")
    session_id = _bounded_text(payload.get("sessionId"), "sessionId")
    departed_role_id = _role_id(payload.get("departedRoleId"), "departedRoleId")
    truth_boundary = _bounded_text(payload.get("truthBoundary"), "truthBoundary", 1024)

    phases_raw = payload.get("phases")
    if not isinstance(phases_raw, list) or len(phases_raw) != len(_EXPECTED_PHASES):
        _fail("authority peer lifecycle must contain exactly four lifecycle phases")
    phases = [_phase(raw, expected) for raw, expected in zip(phases_raw, _EXPECTED_PHASES, strict=True)]

    privacy = payload.get("privacy")
    if not isinstance(privacy, Mapping):
        _fail("authority peer lifecycle privacy must be an object")
    expected_privacy = {
        "rawPlayerIdsTransmitted": False,
        "runtimeSessionIdsTransmitted": False,
        "credentialsTransmitted": False,
    }
    if set(privacy) != set(expected_privacy):
        _fail("authority peer lifecycle privacy fields are invalid")
    if any(privacy.get(key) is not value for key, value in expected_privacy.items()):
        _fail("authority peer lifecycle must explicitly deny identity and credential transmission")

    findings: list[str] = []
    for phase in phases:
        for role in phase["roles"]:
            if role["sessionId"] != session_id:
                findings.append(f"phase {phase['id']} role {role['id']} reported a different session")

    single, reciprocal, departure, reconnect = phases
    if len(single["roles"]) != 1 or single["roles"][0]["observedPeerIds"]:
        findings.append("single phase must contain one role observing no peers")
    if departed_role_id not in {role["id"] for role in reciprocal["roles"]}:
        findings.append("departed role is absent from reciprocal phase")
    if departed_role_id in {role["id"] for role in departure["roles"]}:
        findings.append("departed role remained present after departure")
    if len(departure["roles"]) != 1 or departure["roles"][0]["observedPeerIds"]:
        findings.append("departure phase must leave one role observing no peers")
    if departed_role_id not in {role["id"] for role in reconnect["roles"]}:
        findings.append("departed role did not return in reconnect phase")

    reciprocal_semantics = _semantic_phase(reciprocal, authority)
    reconnect_semantics = _semantic_phase(reconnect, authority)
    if reciprocal_semantics["proven"] is not True:
        findings.extend(f"reciprocal: {finding}" for finding in reciprocal_semantics["findings"])
    if reconnect_semantics["proven"] is not True:
        findings.extend(f"reconnect: {finding}" for finding in reconnect_semantics["findings"])

    proven = not findings
    return {
        "schemaVersion": 1,
        "kind": "evavo-authority-peer-exchange-lifecycle-verification",
        "gameId": game_id,
        "authority": authority,
        "protocol": protocol,
        "sessionId": session_id,
        "departedRoleId": departed_role_id,
        "proven": proven,
        "authorityLifecycleProven": proven,
        "transportProven": False,
        "browserTransportProven": False,
        "reciprocalPeerSemanticsProven": reciprocal_semantics["proven"] is True,
        "reconnectPeerSemanticsProven": reconnect_semantics["proven"] is True,
        "findings": sorted(set(findings)),
        "truthBoundary": truth_boundary,
    }


def load_and_verify(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        _fail("authority peer lifecycle evidence path must not be a symlink")
    raw = path.read_bytes()
    if len(raw) > _MAX_EVIDENCE_BYTES:
        _fail("authority peer lifecycle evidence exceeds 256 KiB")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuthorityPeerLifecycleError("authority peer lifecycle evidence is not valid JSON") from error
    if not isinstance(payload, dict):
        _fail("authority peer lifecycle evidence root must be an object")
    return verify_authority_peer_lifecycle(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m godot_game_test_lab.authority_peer_lifecycle",
        description="Verify privacy-safe server-authority peer lifecycle evidence.",
    )
    parser.add_argument("--evidence", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = load_and_verify(args.evidence)
    except (OSError, AuthorityPeerLifecycleError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["proven"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

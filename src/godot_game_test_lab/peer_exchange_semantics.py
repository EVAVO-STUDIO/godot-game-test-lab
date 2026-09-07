from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_MAX_ROLES = 8
_MAX_OBSERVED_PEERS = 32
_MAX_SESSION_BYTES = 256
_MAX_SOURCE_BYTES = 256
_ROLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PeerObservationEvidenceError(ValueError):
    """Raised when portable peer-observation evidence is structurally inadmissible."""


def _fail(message: str) -> None:
    raise PeerObservationEvidenceError(message)


def _positive_peer_id(value: object, label: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > 2**31 - 1
    ):
        _fail(f"{label} must be a positive peer id")
    return value


def _bounded_text(value: object, label: str, max_bytes: int) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value.encode("utf-8")) > max_bytes
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        _fail(f"{label} must be bounded non-empty single-line text")
    return value


def _role_id(value: object) -> str:
    if not isinstance(value, str) or _ROLE_ID.fullmatch(value) is None:
        _fail("peer evidence role id is invalid")
    return value


def verify_peer_observations(payload: Mapping[str, object]) -> dict[str, Any]:
    """Validate portable, privacy-safe cross-role peer observation evidence.

    This deliberately proves only the semantic peer-observation contract. It does not
    claim transport causality or production network execution.
    """

    if payload.get("schemaVersion") != "1.0":
        _fail("peer observation evidence schemaVersion must be 1.0")

    evidence_class = _bounded_text(
        payload.get("evidenceClass"),
        "evidenceClass",
        _MAX_SOURCE_BYTES,
    )
    source_name = _bounded_text(payload.get("source"), "source", _MAX_SOURCE_BYTES)

    raw_roles = payload.get("roles")
    if not isinstance(raw_roles, list) or not 2 <= len(raw_roles) <= _MAX_ROLES:
        _fail("peer observation evidence must contain between two and eight roles")

    roles: list[dict[str, Any]] = []
    seen_role_ids: set[str] = set()
    for index, raw in enumerate(raw_roles):
        if not isinstance(raw, Mapping):
            _fail(f"peer observation role {index} must be an object")
        unexpected = set(raw) - {
            "id",
            "required",
            "sessionId",
            "localPeerId",
            "observedPeerIds",
            "authorityPeerId",
        }
        if unexpected:
            _fail(
                f"peer observation role {index} has unexpected fields: "
                + ", ".join(sorted(unexpected))
            )
        role_id = _role_id(raw.get("id"))
        if role_id in seen_role_ids:
            _fail("peer observation role id is duplicated")
        seen_role_ids.add(role_id)
        required = raw.get("required", True)
        if not isinstance(required, bool):
            _fail(f"role {role_id} required must be boolean")
        session_id = _bounded_text(
            raw.get("sessionId"),
            f"role {role_id} sessionId",
            _MAX_SESSION_BYTES,
        )
        local_peer_id = _positive_peer_id(
            raw.get("localPeerId"), f"role {role_id} localPeerId"
        )
        observed_raw = raw.get("observedPeerIds")
        if not isinstance(observed_raw, list) or len(observed_raw) > _MAX_OBSERVED_PEERS:
            _fail(f"role {role_id} observedPeerIds must be a bounded array")
        observed = [
            _positive_peer_id(value, f"role {role_id} observed peer id")
            for value in observed_raw
        ]
        if len(set(observed)) != len(observed):
            _fail(f"role {role_id} observedPeerIds contain duplicates")
        if local_peer_id in observed:
            _fail(f"role {role_id} observedPeerIds include its local peer id")

        authority_peer_id: int | None = None
        if "authorityPeerId" in raw and raw.get("authorityPeerId") is not None:
            authority_peer_id = _positive_peer_id(
                raw.get("authorityPeerId"),
                f"role {role_id} authorityPeerId",
            )

        roles.append(
            {
                "id": role_id,
                "required": required,
                "sessionId": session_id,
                "localPeerId": local_peer_id,
                "observedPeerIds": observed,
                "authorityPeerId": authority_peer_id,
            }
        )

    required_roles = sorted(
        (role for role in roles if role["required"] is True),
        key=lambda role: str(role["id"]),
    )
    findings: list[str] = []
    if len(required_roles) < 2:
        findings.append("fewer than two required roles are available for peer-exchange proof")

    sessions = {str(role["sessionId"]) for role in required_roles}
    if len(required_roles) >= 2 and len(sessions) != 1:
        findings.append("required roles did not report one shared multiplayer session id")

    peer_ids = [int(role["localPeerId"]) for role in required_roles]
    if len(set(peer_ids)) != len(peer_ids):
        findings.append("required roles did not report unique local peer ids")
    expected_peer_ids = set(peer_ids)
    for role in required_roles:
        local_peer_id = int(role["localPeerId"])
        expected_remote_ids = expected_peer_ids - {local_peer_id}
        observed = {int(value) for value in role["observedPeerIds"]}
        if not expected_remote_ids.issubset(observed):
            findings.append(
                f"role {role['id']} did not report every other required peer as observed"
            )

    configured_authorities = [
        int(role["authorityPeerId"])
        for role in required_roles
        if role["authorityPeerId"] is not None
    ]
    if configured_authorities and len(configured_authorities) != len(required_roles):
        findings.append(
            "authority peer evidence is only partially configured across required roles"
        )
    if len(configured_authorities) == len(required_roles):
        shared_authorities = set(configured_authorities)
        if len(shared_authorities) != 1:
            findings.append("required roles did not report one shared authority peer id")
        elif next(iter(shared_authorities)) not in expected_peer_ids:
            findings.append("shared authority peer id is not a participating required peer")

    proven = not findings and len(required_roles) >= 2
    normalized_roles = [
        {
            "id": str(role["id"]),
            "sessionId": str(role["sessionId"]),
            "localPeerId": int(role["localPeerId"]),
            "observedPeerIds": [int(value) for value in role["observedPeerIds"]],
            "authorityPeerId": role["authorityPeerId"],
        }
        for role in required_roles
    ]
    return {
        "schemaVersion": 1,
        "evidenceClass": evidence_class,
        "source": source_name,
        "configured": True,
        "proven": proven,
        "transportProven": False,
        "requiredRoleCount": len(required_roles),
        "authorityObserved": (
            len(configured_authorities) == len(required_roles)
            and len(set(configured_authorities)) == 1
            and proven
        ),
        "roles": normalized_roles,
        "findings": sorted(set(findings)),
        "truthBoundary": (
            "A proven result means the supplied required roles report one shared session, "
            "unique local peer ids, and reciprocal observation of every other required peer. "
            "This portable semantic verifier does not prove that bytes crossed a real network, "
            "that a browser or deployed transport was exercised, that admission was authentic, "
            "or that authority enforcement and reconnect behavior are production-ready."
        ),
    }


def load_and_verify(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        _fail("peer observation evidence path must not be a symlink")
    raw = path.read_bytes()
    if len(raw) > 256 * 1024:
        _fail("peer observation evidence exceeds 256 KiB")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PeerObservationEvidenceError("peer observation evidence is not valid JSON") from error
    if not isinstance(payload, dict):
        _fail("peer observation evidence root must be an object")
    return verify_peer_observations(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m godot_game_test_lab.peer_exchange_semantics",
        description="Verify portable privacy-safe multiplayer peer-observation evidence.",
    )
    parser.add_argument("--evidence", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = load_and_verify(args.evidence)
    except (OSError, PeerObservationEvidenceError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["proven"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

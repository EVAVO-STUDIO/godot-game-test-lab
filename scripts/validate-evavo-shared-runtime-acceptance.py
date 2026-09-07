#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VALID_STATUSES = {"passed", "failed", "source_only"}
VALID_COMMAND_STATUSES = {"passed", "failed", "skipped"}
EXPECTED_COMMANDS = {
    "engine-networking-contracts",
    "game-runtime-contracts",
    "web-runtime-check",
}


def fail(message: str) -> None:
    raise ValueError(message)


def require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{name} must be an object")
    return value


def validate_repository(value: Any, name: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    repo = require_mapping(value, name)
    if set(repo) != {"path", "sha", "branch", "dirty"}:
        fail(f"{name} must contain exactly path, sha, branch, dirty")
    if not isinstance(repo["path"], str) or not repo["path"].strip():
        fail(f"{name}.path must be non-empty")
    if not isinstance(repo["sha"], str) or SHA_RE.fullmatch(repo["sha"]) is None:
        fail(f"{name}.sha must be a lowercase 40-character SHA")
    if not isinstance(repo["branch"], str) or not repo["branch"].strip():
        fail(f"{name}.branch must be non-empty")
    if not isinstance(repo["dirty"], bool):
        fail(f"{name}.dirty must be boolean")


def validate_receipt(payload: Any) -> None:
    root = require_mapping(payload, "receipt")
    expected_root = {
        "version",
        "generated_utc",
        "status",
        "test_lab",
        "repositories",
        "godot",
        "commands",
        "issues",
        "claims",
    }
    if set(root) != expected_root:
        fail("receipt root contains missing or unexpected fields")
    if root["version"] != 1:
        fail("receipt.version must equal 1")
    if not isinstance(root["generated_utc"], str) or not root["generated_utc"].strip():
        fail("generated_utc must be non-empty")
    status = root["status"]
    if status not in VALID_STATUSES:
        fail("invalid receipt status")

    validate_repository(root["test_lab"], "test_lab")
    repositories = require_mapping(root["repositories"], "repositories")
    if set(repositories) != {"game_runtime", "engine_systems", "web_runtime"}:
        fail("repositories must contain exactly game_runtime, engine_systems, web_runtime")
    validate_repository(repositories["game_runtime"], "repositories.game_runtime")
    validate_repository(repositories["engine_systems"], "repositories.engine_systems")
    validate_repository(repositories["web_runtime"], "repositories.web_runtime", nullable=True)

    godot = root["godot"]
    if godot is not None:
        godot_obj = require_mapping(godot, "godot")
        if set(godot_obj) != {"path", "version"}:
            fail("godot must contain exactly path and version")
        if not all(isinstance(godot_obj[key], str) and godot_obj[key].strip() for key in godot_obj):
            fail("godot path/version must be non-empty strings")

    commands = root["commands"]
    if not isinstance(commands, list) or not commands:
        fail("commands must be a non-empty array")
    names: set[str] = set()
    failures = 0
    for index, raw in enumerate(commands):
        command = require_mapping(raw, f"commands[{index}]")
        required = {"name", "repository", "status", "exit_code", "duration_ms", "log_path"}
        if not required.issubset(command):
            fail(f"commands[{index}] is missing required fields")
        name = command["name"]
        if not isinstance(name, str) or not name:
            fail(f"commands[{index}].name must be non-empty")
        if name in names:
            fail(f"duplicate command name: {name}")
        names.add(name)
        if command["status"] not in VALID_COMMAND_STATUSES:
            fail(f"commands[{index}] has invalid status")
        if not isinstance(command["exit_code"], int):
            fail(f"commands[{index}].exit_code must be integer")
        if not isinstance(command["duration_ms"], int) or command["duration_ms"] < 0:
            fail(f"commands[{index}].duration_ms must be non-negative integer")
        if not isinstance(command["log_path"], str) or not command["log_path"].strip():
            fail(f"commands[{index}].log_path must be non-empty")
        if command["status"] == "failed":
            failures += 1
        if command["status"] == "passed" and command["exit_code"] != 0:
            fail(f"passed command {name} has nonzero exit code")
        if command["status"] == "failed" and command["exit_code"] == 0:
            fail(f"failed command {name} has zero exit code")
    if names != EXPECTED_COMMANDS:
        fail("receipt must contain exactly the three shared runtime acceptance commands")

    issues = root["issues"]
    if not isinstance(issues, list) or not all(isinstance(item, str) and item for item in issues):
        fail("issues must be an array of non-empty strings")
    if status == "failed" and failures == 0:
        fail("failed receipt must contain at least one failed command")
    if status != "failed" and failures != 0:
        fail("non-failed receipt cannot contain failed commands")

    claims = require_mapping(root["claims"], "claims")
    required_claims = {
        "source_only_is_executable_pass",
        "dirty_checkout_is_release_evidence",
        "networking_contracts_executed",
        "game_runtime_contracts_executed",
        "web_runtime_contracts_executed",
    }
    if not required_claims.issubset(claims):
        fail("claims missing required fields")
    if claims["source_only_is_executable_pass"] is not False:
        fail("source-only validation must never claim executable pass")
    if claims["dirty_checkout_is_release_evidence"] is not False:
        fail("dirty checkouts must never be release evidence")
    for name in required_claims - {"source_only_is_executable_pass", "dirty_checkout_is_release_evidence"}:
        if not isinstance(claims[name], bool):
            fail(f"claims.{name} must be boolean")

    by_name = {command["name"]: command for command in commands}
    expected_networking = by_name["engine-networking-contracts"]["status"] == "passed"
    expected_game = by_name["game-runtime-contracts"]["status"] == "passed"
    expected_web = by_name["web-runtime-check"]["status"] == "passed"
    if claims["networking_contracts_executed"] != expected_networking:
        fail("networking_contracts_executed disagrees with command evidence")
    if claims["game_runtime_contracts_executed"] != expected_game:
        fail("game_runtime_contracts_executed disagrees with command evidence")
    if claims["web_runtime_contracts_executed"] != expected_web:
        fail("web_runtime_contracts_executed disagrees with command evidence")

    if status == "passed":
        if godot is None:
            fail("passed receipt requires Godot evidence")
        if not expected_networking or not expected_game or not expected_web:
            fail("passed receipt requires all three runtime command lanes to pass")
        repos = [root["test_lab"], repositories["game_runtime"], repositories["engine_systems"], repositories["web_runtime"]]
        if any(repo is None or repo["dirty"] for repo in repos):
            fail("passed receipt requires clean evidence for all four repositories")
    elif status == "source_only":
        if expected_networking:
            fail("source_only receipt cannot claim executable engine networking contracts")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate EVAVO shared runtime acceptance receipt")
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.receipt.read_text(encoding="utf-8-sig"))
    validate_receipt(payload)
    print("EVAVO_SHARED_RUNTIME_ACCEPTANCE_RECEIPT=VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fail closed before the canonical Test Lab toolchain checker can run."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path.cwd().resolve(strict=True)
CORE = ROOT / "scripts" / "check_repository_toolchain_core.py"
EXPECTED_WORKFLOWS = {
    ".github/workflows/ci.yml",
    ".github/workflows/evavo-mainline-confirmation.yml",
    ".github/workflows/evavo-native-godot-validation.yml",
    ".github/workflows/reusable-godot-linux-sandbox.yml",
    ".github/workflows/evavo-linux-godot-sandbox.yml",
    ".github/workflows/linux-sandbox-smoke.yml",
}
FORBIDDEN_WORKFLOW_TOKENS = (
    "permissions: write-all",
    "contents: write",
    "actions: write",
    "checks: write",
    "deployments: write",
    "packages: write",
    "pull-requests: write",
    "statuses: write",
    "persist-credentials: true",
    "github.token",
    "GH_TOKEN",
    "git push",
    "gh workflow run",
)
FORBIDDEN_RESIDUE = (
    ".evavo/bootstrap",
    ".evavo/agent-audio-upgrade-diagnostic.txt",
    "scripts/apply_agent_audio_upgrade.py",
)


def _active_yaml(source: str) -> str:
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )


def _preflight_errors() -> list[str]:
    errors: list[str] = []
    workflow_root = ROOT / ".github" / "workflows"
    observed = {
        path.relative_to(ROOT).as_posix()
        for path in workflow_root.iterdir()
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    }
    if observed != EXPECTED_WORKFLOWS:
        missing = sorted(EXPECTED_WORKFLOWS - observed)
        unexpected = sorted(observed - EXPECTED_WORKFLOWS)
        errors.append(
            "workflow inventory drifted: "
            f"missing={missing or 'none'} unexpected={unexpected or 'none'}"
        )

    for relative in sorted(observed & EXPECTED_WORKFLOWS):
        source = _active_yaml((ROOT / relative).read_text(encoding="utf-8"))
        for token in FORBIDDEN_WORKFLOW_TOKENS:
            if token in source:
                errors.append(f"{relative} contains forbidden workflow authority: {token}")

    for relative in FORBIDDEN_RESIDUE:
        if (ROOT / relative).exists():
            errors.append(f"one-time upgrade residue remains: {relative}")
    payloads = sorted((ROOT / ".evavo").glob("bootstrap/agent-audio-upgrade-*.b64"))
    if payloads:
        errors.append(
            "encoded one-time upgrade payloads remain: "
            + ", ".join(path.relative_to(ROOT).as_posix() for path in payloads)
        )
    if not CORE.is_file() or CORE.is_symlink():
        errors.append("canonical toolchain core is missing or not a regular file")
    return errors


def main() -> int:
    errors = _preflight_errors()
    if errors:
        print("Godot lab workflow and residue preflight failed:\n", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    runpy.run_path(str(CORE), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

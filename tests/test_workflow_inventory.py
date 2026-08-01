from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_ROOT = ROOT / ".github" / "workflows"
EXPECTED_WORKFLOWS = {
    "ci.yml",
    "evavo-mainline-confirmation.yml",
    "evavo-native-godot-validation.yml",
    "reusable-godot-linux-sandbox.yml",
    "evavo-linux-godot-sandbox.yml",
    "linux-sandbox-smoke.yml",
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
FORBIDDEN_STAGING_PATHS = (
    ".evavo/bootstrap",
    ".evavo/agent-audio-upgrade-diagnostic.txt",
    "scripts/apply_agent_audio_upgrade.py",
)


def _active_yaml(source: str) -> str:
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )


def test_workflow_inventory_is_exact_and_read_only() -> None:
    observed = {
        path.name
        for path in WORKFLOW_ROOT.iterdir()
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    }
    assert observed == EXPECTED_WORKFLOWS

    for name in sorted(observed):
        source = _active_yaml((WORKFLOW_ROOT / name).read_text(encoding="utf-8"))
        for token in FORBIDDEN_WORKFLOW_TOKENS:
            assert token not in source, f"{name} contains forbidden workflow authority: {token}"


def test_one_time_upgrade_payload_residue_is_absent() -> None:
    for relative in FORBIDDEN_STAGING_PATHS:
        assert not (ROOT / relative).exists(), f"one-time upgrade residue remains: {relative}"

    payloads = sorted((ROOT / ".evavo").glob("bootstrap/agent-audio-upgrade-*.b64"))
    assert payloads == []

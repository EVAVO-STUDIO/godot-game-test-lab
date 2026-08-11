from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_ROOT = ROOT / ".github" / "workflows"
CHECKER_PATH = ROOT / "scripts" / "check_repository_toolchain.py"
EXPECTED_WORKFLOWS = {
    "ci.yml",
    "evavo-mainline-confirmation.yml",
    "evavo-native-godot-validation.yml",
    "game-asset-delivery-admission.yml",
    "reusable-godot-linux-sandbox.yml",
    "evavo-linux-godot-sandbox.yml",
    "linux-sandbox-smoke.yml",
    "visual-animation-admission.yml",
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
    return "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("workflow_guarded_toolchain_checker", CHECKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load workflow-guarded toolchain checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_workflow_inventory_is_exact_and_read_only() -> None:
    observed = {
        path.name for path in WORKFLOW_ROOT.iterdir() if path.is_file() and path.suffix in {".yml", ".yaml"}
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


def test_checker_main_returns_core_result_without_nested_system_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _load_checker()
    monkeypatch.setattr(checker, "_preflight_errors", lambda: [])
    monkeypatch.setattr(checker.runpy, "run_path", lambda *_args, **_kwargs: {"main": lambda: 7})
    assert checker.main() == 7


def test_checker_rejects_core_without_callable_main(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _load_checker()
    monkeypatch.setattr(checker, "_preflight_errors", lambda: [])
    monkeypatch.setattr(checker.runpy, "run_path", lambda *_args, **_kwargs: {})
    with pytest.raises(RuntimeError, match="does not expose callable main"):
        checker.main()

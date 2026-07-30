from __future__ import annotations

import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "evavo-native-godot-validation.yml"
RUNNER = ROOT / "scripts" / "Invoke-GodotLabNativeValidation.ps1"
PYPROJECT = ROOT / "pyproject.toml"


def test_native_workflow_is_exact_sha_manual_and_immutable() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    for token in (
        "name: EVAVO native Godot validation",
        "workflow_dispatch:",
        "expected_sha:",
        "target_repository_path:",
        "minimum_godot_version:",
        "request_source:",
        "permissions:\n  contents: read",
        "runs-on: [self-hosted, Windows, X64, evavo-godot-lab]",
        "ref: ${{ inputs.expected_sha }}",
        "fetch-depth: 0",
        "persist-credentials: false",
        "git merge-base --is-ancestor $env:EXPECTED_SHA origin/main",
        "py -3.11 -m venv",
        "& $python -m pip --version",
        "pip install --disable-pip-version-check -e '.[dev]'",
        "./scripts/Invoke-GodotLabNativeValidation.ps1",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "retention-days: 14",
    ):
        assert token in source, token

    for event in (
        "push",
        "pull_request",
        "pull_request_target",
        "schedule",
        "workflow_run",
        "repository_dispatch",
    ):
        assert re.search(rf"^  {re.escape(event)}:", source, re.MULTILINE) is None

    actions = re.findall(r"^\s*uses:\s*([^\s#]+)", source, re.MULTILINE)
    assert actions
    assert all(re.search(r"@[0-9a-f]{40}$", action) for action in actions)

    for forbidden in (
        "contents: write",
        "packages: write",
        "pull-requests: write",
        "id-token: write",
        "git push",
        "git commit",
        "wrangler deploy",
        "vercel deploy",
        "secrets.",
        "--upgrade pip",
    ):
        assert forbidden not in source


def test_native_wrapper_is_bounded_and_detects_tracked_mutation() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    for token in (
        '[string]$MinimumGodotVersion = "4.6.2"',
        '$allowedRepositoryRoot = (Resolve-Path "C:\\GitRepos").Path',
        'Test-Path (Join-Path $target "project.godot")',
        'git -C $labRoot rev-parse HEAD',
        'git -C $target rev-parse --show-toplevel',
        'status --porcelain=v1 --untracked-files=no',
        '"-m", "compileall", "src", "tests"',
        '"-m", "ruff", "check", "src", "tests"',
        '"-m", "pytest"',
        '"-m", "godot_game_test_lab.cli", "doctor"',
        '"-m", "godot_game_test_lab.cli", "validate", $target',
        '"--minimum-godot-version", $MinimumGodotVersion',
        '$receipt.trackedMutationDetected = $trackedAfter -ne $trackedBefore',
        'Native validation changed tracked files in the target repository.',
        'if ($validationError)',
    ):
        assert token in source, token

    for forbidden in (
        "git commit",
        "git push",
        "git reset --hard",
        "git checkout --",
        "wrangler deploy",
        "vercel deploy",
        "gh pr",
    ):
        assert forbidden not in source


def test_validation_toolchain_dependencies_are_exact() -> None:
    document = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert document["build-system"]["requires"] == ["hatchling==1.25.0"]
    assert document["project"]["optional-dependencies"]["dev"] == [
        "pytest==8.3.0",
        "ruff==0.9.0",
    ]

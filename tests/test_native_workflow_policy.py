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
        "project_subpath:",
        "expected_target_sha:",
        "minimum_godot_version:",
        "request_source:",
        "group: native-godot-${{ inputs.expected_sha }}-${{ inputs.expected_target_sha }}",
        "permissions:\n  contents: read",
        "runs-on: [self-hosted, Windows, X64, evavo-godot-lab]",
        "ref: ${{ inputs.expected_sha }}",
        "fetch-depth: 0",
        "persist-credentials: false",
        "git merge-base --is-ancestor $env:EXPECTED_SHA origin/main",
        "py -3.11 -m venv",
        "& $python -m pip --version",
        "pip install --disable-pip-version-check -e '.[dev,agent]'",
        "validation_root=$validationRoot",
        "validation_artifacts=$(Join-Path $validationRoot 'evidence')",
        "-TargetRepositoryPath $env:TARGET_ROOT",
        "-ProjectSubpath $env:PROJECT_SUBPATH",
        "-AllowedTargetRoots @('C:\\GitRepos')",
        "-ExpectedTargetSha $env:EXPECTED_TARGET_SHA",
        "-AllowedArtifactRoot $env:VALIDATION_ROOT",
        "path: ${{ steps.paths.outputs.validation_artifacts }}",
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
        "path: artifacts/native-validation",
    ):
        assert forbidden not in source


def test_native_wrapper_is_exact_sha_external_and_mutation_safe() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    for token in (
        "[string]$ExpectedTargetSha",
        "[string]$AllowedArtifactRoot",
        '[string]$ProjectSubpath = "."',
        '[string[]]$AllowedTargetRoots = @("C:\\GitRepos")',
        '[string]$MinimumGodotVersion = "4.6.2"',
        "Assert-NoReparsePoint",
        "TargetRepositoryPath must identify the target Git root",
        "use ProjectSubpath for monorepos",
        "TargetRepositoryPath is outside AllowedTargetRoots",
        "ProjectSubpath escapes the target Git repository",
        'Test-Path -LiteralPath (Join-Path $projectPath "project.godot")',
        '"status", "--porcelain=v1", "--untracked-files=all"',
        "The target repository must be completely clean",
        "ArtifactPath must remain beneath AllowedArtifactRoot",
        "AllowedArtifactRoot must remain disjoint from Lab and target repositories",
        "ArtifactPath already exists; use a unique run directory",
        '"scripts/check_repository_toolchain.py", "--native-family", "--installed"',
        '"-m", "compileall", "-q", "src", "scripts", "tests"',
        '"-m", "ruff", "check", "src", "scripts", "tests"',
        '"-m", "pytest"',
        '"-m", "godot_game_test_lab.cli", "doctor"',
        '"-m", "godot_game_test_lab.cli", "validate", $projectPath',
        '"--artifacts", (Join-Path $artifacts "validation")',
        "schemaVersion = \"2.0\"",
        "Write-AtomicJson -Path $receiptPath",
        "$receipt.targetUnchanged",
        "Native validation changed or obscured the target repository.",
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
        "--untracked-files=no) -join",
        "ArtifactPath must remain beneath the lab checkout or target project",
    ):
        assert forbidden not in source


def test_validation_toolchain_dependencies_are_exact() -> None:
    document = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert document["build-system"]["requires"] == ["hatchling==1.25.0"]
    assert document["project"]["optional-dependencies"]["dev"] == [
        "pytest==8.3.0",
        "ruff==0.9.0",
    ]

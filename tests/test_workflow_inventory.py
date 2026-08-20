from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
EXPECTED_WORKFLOWS = {
    "capability-manifest.yml",
    "ci.yml",
    "evavo-linux-godot-sandbox.yml",
    "evavo-mainline-confirmation.yml",
    "evavo-native-godot-validation.yml",
    "game-asset-delivery-admission.yml",
    "linux-sandbox-smoke.yml",
    "reusable-godot-linux-sandbox.yml",
    "verified-toolchain-transport.yml",
    "visual-animation-admission.yml",
}
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
EXTERNAL_USES = re.compile(r"^\s*uses:\s*([^\s#]+)", flags=re.MULTILINE)


def _workflows() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"), key=lambda path: path.name)


def test_workflow_inventory_is_explicit_and_complete() -> None:
    assert {path.name for path in _workflows()} == EXPECTED_WORKFLOWS


def test_workflows_use_immutable_external_actions() -> None:
    for workflow in _workflows():
        text = workflow.read_text(encoding="utf-8")
        assert "persist-credentials: true" not in text
        assert "permissions: write-all" not in text
        assert "contents: write" not in text
        assert "pull-requests: write" not in text
        for reference in EXTERNAL_USES.findall(text):
            if reference.startswith("./"):
                continue
            assert "@" in reference, f"{workflow.name} action lacks a ref: {reference}"
            action, ref = reference.rsplit("@", 1)
            assert action and FULL_SHA.fullmatch(ref), (
                f"{workflow.name} action is not pinned to a full SHA: {reference}"
            )


def test_native_validation_workflow_retains_fail_closed_policy() -> None:
    text = (
        WORKFLOWS / "evavo-native-godot-validation.yml"
    ).read_text(encoding="utf-8")
    assert "Validate dispatch inputs" in text
    assert "expected_sha:" in text
    assert "expected_target_sha:" in text
    assert "request_source:" in text
    assert "runs-on: [self-hosted, Windows, X64, evavo-godot-lab]" in text
    assert "cancel-in-progress: false" in text
    assert "Check out exact test-lab mainline commit" in text
    assert "git merge-base --is-ancestor $env:EXPECTED_SHA origin/main" in text
    assert "py -3.11 scripts/check_repository_toolchain.py --native-family" in text
    assert "Invoke-GodotLabNativeValidation.ps1" in text
    assert (
        "native-godot-validation-${{ inputs.expected_sha }}-"
        "${{ inputs.expected_target_sha }}"
    ) in text
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text
    assert "git push" not in text


def test_rally_preview_workflows_were_not_retained() -> None:
    assert not any("rally" in path.name.casefold() for path in _workflows())
    assert not any("preview" in path.name.casefold() for path in _workflows())
    all_workflow_text = "\n".join(
        path.read_text(encoding="utf-8") for path in _workflows()
    )
    assert "rally-falcon-preview.v1.json" not in all_workflow_text
    assert "rally-falcon-preview.v2.json" not in all_workflow_text
    assert "rally-falcon-preview.json" not in all_workflow_text


def test_mainline_confirmation_is_source_only_and_exact_sha_bound() -> None:
    text = (
        WORKFLOWS / "evavo-mainline-confirmation.yml"
    ).read_text(encoding="utf-8")
    assert "Validate dispatch input" in text
    assert "Check out exact mainline commit" in text
    assert "Verify checked-out commit" in text
    assert 'ACTUAL_SHA="$(git rev-parse HEAD)"' in text
    assert 'git merge-base --is-ancestor "$EXPECTED_SHA" origin/main' in text
    assert "Run adversarial toolchain fixtures" in text
    assert "python scripts/test_repository_toolchain.py" in text
    assert "Record source-only truth boundary" in text
    assert "Target project import, boot, export or movie: not performed" in text
    assert "Windows runner probe: not performed" in text
    assert "permissions:\n  contents: read" in text
    assert "native-validation" not in text
    assert "docker build" not in text
    assert "dotnet build" not in text
    assert "git push" not in text
    assert "gh pr create" not in text

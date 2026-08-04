from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_IMAGE = (
    "ubuntu:noble-20260610@sha256:"
    "4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90"
)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_linux_container_is_pinned_and_fail_closed() -> None:
    dockerfile = _read("containers/linux-sandbox/Dockerfile")
    dockerignore = _read(".dockerignore")
    reliability = _read("evavo.reliability.json")
    assert f"FROM {BASE_IMAGE}" in dockerfile
    assert BASE_IMAGE in reliability
    assert "ARG GODOT_VERSION=4.6.3" in dockerfile
    engine_lock = json.loads(
        _read("src/godot_game_test_lab/godot-engine-lock.json")
    )
    assert engine_lock["minimumVersion"] == "4.6.2"
    assert engine_lock["defaultVersion"] == "4.6.3"
    assert "SHA512-SUMS.txt" in dockerfile
    assert "digest = hashlib.sha512()" in dockerfile
    assert "SHA-512 mismatch" in dockerfile
    assert "dotnet-sdk-8.0" in dockerfile
    assert "xvfb" in dockerfile
    assert "mesa-vulkan-drivers" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "target-source" in dockerignore
    assert ".git" in dockerignore
    assert "artifacts" in dockerignore


def test_linux_workflow_enforces_exact_sha_and_sandbox_boundaries() -> None:
    workflow = _read(".github/workflows/evavo-linux-godot-sandbox.yml")
    for marker in [
        "workflow_call:",
        "expected_sha:",
        "expected_target_sha:",
        "Verify target current default-branch head",
        "repository: EVAVO-STUDIO/godot-game-test-lab",
        "request_source:",
        "EVAVO_GODOT_LAB_READ_TOKEN",
        "^EVAVO-STUDIO/",
        "api.github.com/repos/{repository}",
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "target=/workspace/source,readonly",
        "Verify target checkout remained unchanged",
        "retention-days: 14",
    ]:
        assert marker in workflow
    assert "persist-credentials: false" in workflow
    assert "git reset" not in workflow
    assert "git push" not in workflow


def test_reusable_workflow_preserves_host_file_ownership() -> None:
    workflow = _read(".github/workflows/reusable-godot-linux-sandbox.yml")
    for marker in [
        'host_uid="$(id -u)"',
        'host_gid="$(id -g)"',
        "Linux sandbox requires a non-root hosted runner identity",
        '--user "${host_uid}:${host_gid}"',
        'uid=${host_uid},gid=${host_gid}',
        "--env HOME=/home/godotlab",
        '[[ ! -e "${work}" ]]',
        "Linux sandbox ephemeral worktree cleanup failed",
    ]:
        assert marker in workflow
    assert "uid=10001,gid=10001" not in workflow
    assert "--user root" not in workflow
    assert "sudo chown" not in workflow
    assert "sudo chmod" not in workflow


def test_entrypoint_requires_read_only_source_and_uses_ephemeral_copy() -> None:
    entrypoint = _read("scripts/linux-sandbox-entrypoint.sh")
    assert "source mount must be read-only" in entrypoint
    assert "EVAVO_WORKING_ROOT" in entrypoint
    assert "run_agent_godot_qa_with_process_exit.py" in entrypoint
    assert "--working-root" in entrypoint
    assert "export_preset" in entrypoint


def test_linux_runner_records_visual_and_structured_evidence() -> None:
    runner = _read("src/godot_game_test_lab/linux_sandbox.py")
    for marker in [
        "prepare_ephemeral_copy",
        "GALLIUM_DRIVER=llvmpipe",
        "--write-movie",
        "contact-sheet.png",
        "sandbox-report.json",
        "source symlink escapes repository",
        "_enforce_godot_identity",
    ]:
        assert marker in runner

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_fixture_and_profile_are_mounted_at_the_same_project_root() -> None:
    fixture = ROOT / "fixtures/linux-smoke"
    profile = json.loads(
        (fixture / ".evavo/godot-lab-linux.json").read_text(encoding="utf-8")
    )

    assert (fixture / "project.godot").is_file()
    assert (fixture / "main.tscn").is_file()
    assert (fixture / "smoke.gd").is_file()
    assert profile["projectSubpath"] == "fixtures/linux-smoke"
    assert profile["minimumGodotVersion"] == "4.6.2"
    assert profile["engineFlavor"] == "standard"
    assert profile["visual"]["required"] is True
    assert profile["visual"]["scene"] == "res://main.tscn"
    assert profile["visual"]["frames"] == 180


def test_smoke_workflow_invokes_the_local_reusable_worker_at_the_same_sha() -> None:
    workflow = (ROOT / ".github/workflows/linux-sandbox-smoke.yml").read_text(
        encoding="utf-8"
    )

    assert "uses: ./.github/workflows/reusable-godot-linux-sandbox.yml" in workflow
    assert "lab_sha: ${{ github.sha }}" in workflow
    assert "target_sha: ${{ github.sha }}" in workflow
    assert "fixtures/linux-smoke/.evavo/godot-lab-linux.json" in workflow
    assert "workflow_dispatch:" in workflow
    assert "contents: read" in workflow

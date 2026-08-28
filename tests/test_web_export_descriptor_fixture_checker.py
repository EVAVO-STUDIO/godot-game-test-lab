from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_web_export_descriptor_fixture.py"
SOURCE_FIXTURE = ROOT / "tests" / "fixtures" / "generated-descriptor.v2.json"
RUNTIME_FIXTURE = Path("packages/godot-loader/fixtures/generated-descriptor.v2.json")


def _runtime_root(tmp_path: Path) -> Path:
    runtime = tmp_path / "godot-web-runtime"
    fixture = runtime / RUNTIME_FIXTURE
    fixture.parent.mkdir(parents=True)
    shutil.copyfile(SOURCE_FIXTURE, fixture)
    return runtime


def _run(runtime: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--runtime-root",
            str(runtime),
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_fixture_checker_returns_exact_non_mutating_receipt(tmp_path: Path) -> None:
    runtime = _runtime_root(tmp_path)

    result = _run(runtime)

    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout)
    assert report["status"] == "passed"
    assert report["contract"] == "evavo.godot-web-export-descriptor.v2"
    assert report["bytes"] == SOURCE_FIXTURE.stat().st_size
    assert len(report["sha256"]) == 64
    assert report["mutationAuthority"] is False
    assert report["publicationAuthority"] is False


def test_fixture_checker_fails_closed_on_byte_drift(tmp_path: Path) -> None:
    runtime = _runtime_root(tmp_path)
    fixture = runtime / RUNTIME_FIXTURE
    value = json.loads(fixture.read_text(encoding="utf-8"))
    value["bridgeTimeoutMs"] = 20_000
    fixture.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    result = _run(runtime)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["status"] == "failed"
    assert "bridgeTimeoutMs" in report["error"] or "differ" in report["error"]
    assert report["mutationAuthority"] is False
    assert report["publicationAuthority"] is False


def test_fixture_checker_rejects_linked_runtime_root(tmp_path: Path) -> None:
    runtime = _runtime_root(tmp_path)
    linked = tmp_path / "linked-runtime"
    linked.symlink_to(runtime, target_is_directory=True)

    result = _run(linked)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["status"] == "failed"
    assert "non-linked directory" in report["error"]

from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mcp") is None,
    reason="the optional MCP agent extra is not installed",
)


def _available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_listener(process: subprocess.Popen[str], port: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise AssertionError(f"MCP server exited before startup with code {return_code}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("MCP server did not open its loopback port within the timeout")


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def test_loopback_server_proves_protocol_identity_and_roots(tmp_path: Path) -> None:
    port = _available_loopback_port()
    evidence = tmp_path / "evidence"
    engines = tmp_path / "engines"
    probe = tmp_path / "mcp-worker-acceptance.json"
    server_stdout = tmp_path / "mcp-server.stdout.log"
    server_stderr = tmp_path / "mcp-server.stderr.log"

    command = [
        sys.executable,
        "-m",
        "godot_game_test_lab.mcp_server",
        "--transport",
        "streamable-http",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--lab-root",
        str(ROOT),
        "--allowed-root",
        str(ROOT),
        "--evidence-root",
        str(evidence),
        "--engine-root",
        str(engines),
        "--allow-noninteractive",
    ]

    with (
        server_stdout.open("w", encoding="utf-8") as stdout_handle,
        server_stderr.open("w", encoding="utf-8") as stderr_handle,
    ):
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            text=True,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
        try:
            _wait_for_listener(process, port, 20)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "godot_game_test_lab.mcp_probe",
                    "--endpoint",
                    f"http://127.0.0.1:{port}/mcp",
                    "--expected-lab-root",
                    str(ROOT),
                    "--expected-allowed-root",
                    str(ROOT),
                    "--expected-evidence-root",
                    str(evidence),
                    "--expected-engine-root",
                    str(engines),
                    "--expect-noninteractive",
                    "--timeout-seconds",
                    "15",
                    "--output",
                    str(probe),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            assert result.returncode == 0, (
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}\n"
                f"server stdout:\n{server_stdout.read_text(encoding='utf-8')}\n"
                f"server stderr:\n{server_stderr.read_text(encoding='utf-8')}"
            )
        finally:
            _stop_process(process)

    report = json.loads(probe.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["capabilities"]["bridge"] == "evavo-godot-lab-agent"
    assert report["capabilities"]["labRoot"] == str(ROOT)
    assert report["capabilities"]["allowedTargetRoots"] == [str(ROOT)]
    assert report["capabilities"]["evidenceRoot"] == str(evidence)
    assert report["capabilities"]["engineRoot"] == str(engines)
    assert report["capabilities"]["requireInteractiveDesktop"] is False
    assert "godot_view_image" in report["capabilities"]["tools"]
    assert "godot_hear_audio" in report["capabilities"]["tools"]

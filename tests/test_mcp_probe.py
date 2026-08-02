from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from godot_game_test_lab.mcp_probe import (
    McpProbeError,
    _REQUIRED_TOOLS,
    _structured_payload,
    _validate_capabilities,
    _validate_endpoint,
)


def _directories(tmp_path: Path) -> tuple[Path, Path, Path, tuple[Path, ...]]:
    lab = tmp_path / "lab"
    evidence = tmp_path / "evidence"
    engines = tmp_path / "engines"
    roots = (tmp_path / "games-a", tmp_path / "games-b")
    for path in (lab, evidence, engines, *roots):
        path.mkdir()
    return lab, evidence, engines, roots


def _capabilities(
    lab: Path,
    evidence: Path,
    engines: Path,
    roots: tuple[Path, ...],
) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "bridge": "evavo-godot-lab-agent",
        "labRoot": str(lab),
        "allowedTargetRoots": [str(path) for path in roots],
        "evidenceRoot": str(evidence),
        "engineRoot": str(engines),
        "requireInteractiveDesktop": True,
        "autoProvisionEngines": True,
    }


def test_loopback_endpoint_is_explicit_and_path_bound() -> None:
    assert _validate_endpoint("http://127.0.0.1:8765/mcp").endswith("/mcp")
    assert _validate_endpoint("http://[::1]:8765/mcp").endswith("/mcp")

    for value in (
        "http://localhost:8765/mcp",
        "http://0.0.0.0:8765/mcp",
        "https://127.0.0.1:8765/mcp",
        "http://127.0.0.1:8765/",
        "http://127.0.0.1/mcp",
        "http://user@127.0.0.1:8765/mcp",
    ):
        with pytest.raises(McpProbeError):
            _validate_endpoint(value)


def test_capabilities_require_exact_roots_and_tools(tmp_path: Path) -> None:
    lab, evidence, engines, roots = _directories(tmp_path)
    value = _capabilities(lab, evidence, engines, roots)

    accepted = _validate_capabilities(
        value,
        expected_lab_root=lab,
        expected_allowed_roots=tuple(reversed(roots)),
        expected_evidence_root=evidence,
        expected_engine_root=engines,
        expect_interactive=True,
        expect_auto_provision=True,
        tool_names=set(_REQUIRED_TOOLS),
    )

    assert accepted["bridge"] == "evavo-godot-lab-agent"
    assert accepted["allowedTargetRoots"] == [str(path) for path in roots]


def test_capability_drift_fails_closed(tmp_path: Path) -> None:
    lab, evidence, engines, roots = _directories(tmp_path)
    value = _capabilities(lab, evidence, engines, roots)
    value["autoProvisionEngines"] = False

    with pytest.raises(McpProbeError, match="provisioning policy"):
        _validate_capabilities(
            value,
            expected_lab_root=lab,
            expected_allowed_roots=roots,
            expected_evidence_root=evidence,
            expected_engine_root=engines,
            expect_interactive=True,
            expect_auto_provision=True,
            tool_names=set(_REQUIRED_TOOLS),
        )

    value["autoProvisionEngines"] = True
    with pytest.raises(McpProbeError, match="missing required tools"):
        _validate_capabilities(
            value,
            expected_lab_root=lab,
            expected_allowed_roots=roots,
            expected_evidence_root=evidence,
            expected_engine_root=engines,
            expect_interactive=True,
            expect_auto_provision=True,
            tool_names={"godot_capabilities"},
        )


def test_structured_payload_prefers_mcp_structured_content() -> None:
    value = {"bridge": "evavo-godot-lab-agent"}
    result = SimpleNamespace(structuredContent=value, content=[])
    assert _structured_payload(result) is value

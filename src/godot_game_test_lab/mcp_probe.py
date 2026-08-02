from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_REQUIRED_TOOLS = frozenset(
    {
        "godot_capabilities",
        "godot_doctor",
        "godot_ensure_engine",
        "godot_inspect",
        "godot_audit",
        "godot_validate",
        "godot_run_bot_qa",
        "godot_run_native_qa",
        "godot_run_linux_sandbox",
        "godot_analyze_run_media",
        "godot_view_image",
        "godot_hear_audio",
    }
)


class McpProbeError(RuntimeError):
    """Raised when the loopback MCP worker cannot prove its configured identity."""


def _canonical_path(value: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(os.fspath(value.expanduser())))
    for component in (absolute, *absolute.parents):
        try:
            if component.exists() and component.is_symlink():
                raise McpProbeError(f"{label} may not traverse a symbolic link: {component}")
        except OSError as error:
            raise McpProbeError(f"Could not inspect {label}: {component}") from error
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as error:
        raise McpProbeError(f"{label} does not exist: {absolute}") from error
    if not resolved.is_dir():
        raise McpProbeError(f"{label} must be a directory: {resolved}")
    return resolved


def _identity(path: Path) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(path)))


def _validate_endpoint(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != "/mcp"
    ):
        raise McpProbeError(
            "MCP endpoint must be an explicit loopback HTTP URL ending in /mcp"
        )
    try:
        port = parsed.port
    except ValueError as error:
        raise McpProbeError("MCP endpoint contains an invalid port") from error
    if port is None or not 1 <= port <= 65535:
        raise McpProbeError("MCP endpoint must include a port between 1 and 65535")
    return value


def _structured_payload(result: object) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    for item in getattr(result, "content", []):
        text = getattr(item, "text", None)
        if not isinstance(text, str):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise McpProbeError("godot_capabilities did not return a structured JSON object")


def _validate_capabilities(
    value: dict[str, Any],
    *,
    expected_lab_root: Path,
    expected_allowed_roots: tuple[Path, ...],
    expected_evidence_root: Path,
    expected_engine_root: Path,
    expect_interactive: bool,
    expect_auto_provision: bool,
    tool_names: set[str],
) -> dict[str, Any]:
    if value.get("schemaVersion") != "1.0":
        raise McpProbeError("MCP capability schema version changed")
    if value.get("bridge") != "evavo-godot-lab-agent":
        raise McpProbeError("Loopback endpoint is not the EVAVO Godot Lab agent bridge")

    comparisons = (
        ("Lab root", value.get("labRoot"), expected_lab_root),
        ("Evidence root", value.get("evidenceRoot"), expected_evidence_root),
        ("Engine root", value.get("engineRoot"), expected_engine_root),
    )
    for label, observed, expected in comparisons:
        if not isinstance(observed, str) or _identity(Path(observed)) != _identity(expected):
            raise McpProbeError(f"{label} does not match the accepted worker configuration")

    observed_roots = value.get("allowedTargetRoots")
    if not isinstance(observed_roots, list) or not all(
        isinstance(item, str) for item in observed_roots
    ):
        raise McpProbeError("MCP allowedTargetRoots is not a string array")
    expected_root_ids = sorted({_identity(path) for path in expected_allowed_roots})
    observed_root_ids = sorted({_identity(Path(item)) for item in observed_roots})
    if observed_root_ids != expected_root_ids:
        raise McpProbeError("MCP allowed target roots do not match the accepted configuration")

    if value.get("requireInteractiveDesktop") is not expect_interactive:
        raise McpProbeError(
            "MCP interactive-desktop policy does not match the accepted configuration"
        )
    if value.get("autoProvisionEngines") is not expect_auto_provision:
        raise McpProbeError("MCP managed-engine provisioning policy does not match")

    missing_tools = sorted(_REQUIRED_TOOLS - tool_names)
    if missing_tools:
        raise McpProbeError(f"MCP worker is missing required tools: {missing_tools}")
    if "godot_capabilities" not in tool_names:
        raise McpProbeError("MCP worker did not expose godot_capabilities")

    return {
        "bridge": value["bridge"],
        "labRoot": value["labRoot"],
        "allowedTargetRoots": value["allowedTargetRoots"],
        "evidenceRoot": value["evidenceRoot"],
        "engineRoot": value["engineRoot"],
        "requireInteractiveDesktop": value["requireInteractiveDesktop"],
        "autoProvisionEngines": value["autoProvisionEngines"],
        "tools": sorted(tool_names),
    }


async def _probe(endpoint: str) -> tuple[dict[str, Any], set[str], dict[str, Any]]:
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as error:
        raise McpProbeError(
            'MCP probing requires the optional agent extra: pip install -e ".[agent]"'
        ) from error

    async with streamable_http_client(endpoint) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            tool_names = {tool.name for tool in listed.tools}
            result = await session.call_tool("godot_capabilities", arguments={})
            if getattr(result, "isError", False):
                raise McpProbeError("godot_capabilities returned an MCP tool error")
            payload = _structured_payload(result)
            server_info = getattr(initialized, "serverInfo", None)
            server = {
                "name": getattr(server_info, "name", None),
                "version": getattr(server_info, "version", None),
            }
            return payload, tool_names, server


def _write_json(path: Path, value: dict[str, Any]) -> None:
    destination = Path(os.path.abspath(os.fspath(path.expanduser())))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.tmp-{os.getpid()}-{id(value)}"
    )
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m godot_game_test_lab.mcp_probe",
        description="Prove the exact identity and root policy of a loopback Godot Lab MCP worker.",
    )
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--expected-lab-root", type=Path, required=True)
    parser.add_argument(
        "--expected-allowed-root",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument("--expected-evidence-root", type=Path, required=True)
    parser.add_argument("--expected-engine-root", type=Path, required=True)
    parser.add_argument("--expect-noninteractive", action="store_true")
    parser.add_argument("--expect-no-auto-provision", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    report: dict[str, Any] = {
        "schemaVersion": "1.0",
        "status": "blocked",
        "endpoint": args.endpoint,
    }
    try:
        endpoint = _validate_endpoint(args.endpoint)
        if not 0.5 <= args.timeout_seconds <= 120:
            raise McpProbeError("--timeout-seconds must be between 0.5 and 120")
        if not args.expected_allowed_root:
            raise McpProbeError("At least one --expected-allowed-root is required")

        lab_root = _canonical_path(args.expected_lab_root, "Expected Lab root")
        evidence_root = _canonical_path(
            args.expected_evidence_root, "Expected evidence root"
        )
        engine_root = _canonical_path(args.expected_engine_root, "Expected engine root")
        allowed_roots = tuple(
            _canonical_path(path, "Expected allowed target root")
            for path in args.expected_allowed_root
        )
        if len({_identity(path) for path in allowed_roots}) != len(allowed_roots):
            raise McpProbeError("Expected allowed target roots contain duplicates")

        payload, tool_names, server = asyncio.run(
            asyncio.wait_for(_probe(endpoint), timeout=args.timeout_seconds)
        )
        accepted = _validate_capabilities(
            payload,
            expected_lab_root=lab_root,
            expected_allowed_roots=allowed_roots,
            expected_evidence_root=evidence_root,
            expected_engine_root=engine_root,
            expect_interactive=not args.expect_noninteractive,
            expect_auto_provision=not args.expect_no_auto_provision,
            tool_names=tool_names,
        )
        report.update(
            {
                "status": "passed",
                "server": server,
                "capabilities": accepted,
            }
        )
        code = 0
    except (McpProbeError, TimeoutError, OSError, RuntimeError, ValueError) as error:
        report["error"] = str(error)
        code = 2

    if args.output is not None:
        _write_json(args.output, report)
    stream = sys.stdout if code == 0 else sys.stderr
    print(json.dumps(report, sort_keys=True), file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

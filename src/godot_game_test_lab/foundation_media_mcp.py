from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import Context, FastMCP
except ImportError:  # Source-only validation does not require MCP.
    Context = Any
    FastMCP = None

from .asset_audit_io import (
    AssetAuditError,
    is_within,
    resolve_regular_file,
    write_evidence_json,
)
from .asset_audit_mcp_policy import (
    AssetAuditMcpConfig,
    AssetAuditTarget,
    resolve_audit_path,
    resolve_target,
)
from .foundation_media_plan import validate_foundation_media_plan

DEFAULT_CONTRACT = (
    "examples/playable_foundation_hub/data/"
    "foundation_kit_media_production_contract_v1.json"
)


def _evidence_path(
    value: str,
    *,
    label: str,
    target: AssetAuditTarget,
    config: AssetAuditMcpConfig,
    target_only: bool,
) -> Path:
    requested = Path(value).expanduser()
    if not requested.is_absolute():
        requested = Path(target.git_root) / requested
    resolved = resolve_regular_file(requested, label)
    if is_within(resolved, Path(target.git_root)):
        return resolved
    if not target_only and is_within(resolved, config.evidence_root):
        return resolved
    boundary = "target Git root" if target_only else "target or evidence root"
    raise AssetAuditError(f"{label} must remain inside the {boundary}")


def build_server(config: AssetAuditMcpConfig):
    if FastMCP is None:
        raise RuntimeError(
            'Foundation media MCP requires the agent extra: pip install -e ".[agent]"'
        )
    server = FastMCP(
        name="EVAVO Foundation Kit Media Plan Gate",
        instructions=(
            "Validate exact Foundation Kit media plans against the game-owned "
            "contract and Art Studio audit. The target repository is read-only. "
            "Optional reports are create-only beneath the configured evidence root. "
            "Long-running upstream audits, mastering and native captures should use "
            "cancellable MCP Tasks with progress evidence."
        ),
        json_response=True,
    )

    @server.tool(
        name="foundation_media_plan_capabilities",
        structured_output=True,
    )
    def capabilities() -> dict[str, Any]:
        return {
            "schemaVersion": "1.0",
            "bridge": "evavo-foundation-media-plan-gate",
            "labRoot": str(config.lab_root),
            "allowedTargetRoots": [
                str(path) for path in config.allowed_target_roots
            ],
            "evidenceRoot": str(config.evidence_root),
            "writesTargetRepository": False,
            "performsGitMutation": False,
            "supportsProgressNotifications": True,
            "taskPolicy": {
                "longRunningUpstreamOperationsUseTasks": True,
                "taskCancellationRequired": True,
                "taskResultsAreEvidenceResources": True,
            },
            "tools": [
                "foundation_media_plan_capabilities",
                "foundation_validate_media_plan",
            ],
            "checks": [
                "exact game-contract SHA-256 binding",
                "exact Art Studio audit SHA-256 binding",
                "stable current source identities",
                "role-owned runtime roots and import policy",
                "five authored native review surfaces",
                "audio analysis and listening routes",
                "strict no-blocker and no-review readiness",
            ],
            "truthBoundaries": [
                "A passing plan is not creative approval.",
                "The tool does not import Godot or listen to audio.",
                "The tool has no deletion or publication authority.",
            ],
        }

    @server.tool(
        name="foundation_validate_media_plan",
        structured_output=True,
    )
    async def validate_plan(
        target: str,
        audit: str,
        plan: str,
        ctx: Context,
        contract: str = DEFAULT_CONTRACT,
        project_subpath: str | None = None,
        expected_target_sha: str | None = None,
        strict: bool = False,
        output: str | None = None,
    ) -> dict[str, Any]:
        """Validate one exact Foundation Kit media production plan."""
        await ctx.report_progress(
            progress=0.05,
            total=1.0,
            message="Resolving exact Foundation Kit source authority",
        )
        record = await asyncio.to_thread(
            resolve_target,
            target,
            config=config,
            project_subpath=project_subpath,
            expected_target_sha=expected_target_sha,
        )
        contract_path = _evidence_path(
            contract,
            label="Foundation Kit media contract",
            target=record,
            config=config,
            target_only=True,
        )
        audit_path = resolve_audit_path(audit, target=record, config=config)
        plan_path = _evidence_path(
            plan,
            label="Foundation Kit media plan",
            target=record,
            config=config,
            target_only=False,
        )
        await ctx.report_progress(
            progress=0.3,
            total=1.0,
            message="Binding plan work items to exact contract and audit bytes",
        )
        report = await asyncio.to_thread(
            validate_foundation_media_plan,
            Path(record.project_root),
            contract_path,
            audit_path,
            plan_path,
            strict=strict,
        )
        report["target"] = {
            "gitRoot": record.git_root,
            "projectRoot": record.project_root,
            "projectSubpath": record.project_subpath,
            "targetSha": record.target_sha,
        }
        if output is not None:
            written = await asyncio.to_thread(
                write_evidence_json,
                report,
                output=Path(output),
                evidence_root=config.evidence_root,
                protected_roots=(config.lab_root, Path(record.git_root)),
                replace=False,
            )
            report["outputPath"] = str(written)
        await ctx.report_progress(
            progress=1.0,
            total=1.0,
            message="Foundation Kit media plan validation complete",
        )
        return report

    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m godot_game_test_lab.foundation_media_mcp"
    )
    parser.add_argument("--lab-root", type=Path)
    parser.add_argument("--allowed-root", type=Path, action="append", default=[])
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.transport == "streamable-http" and args.host not in {
        "127.0.0.1",
        "::1",
    }:
        raise SystemExit(
            "Streamable HTTP is restricted to an explicit loopback host"
        )
    if not 1 <= args.port <= 65_535:
        raise SystemExit("--port must be between 1 and 65535")
    try:
        config = AssetAuditMcpConfig.from_environment(
            lab_root=args.lab_root,
            allowed_target_roots=args.allowed_root or None,
            evidence_root=args.evidence_root,
        )
        server = build_server(config)
    except (RuntimeError, AssetAuditError, OSError, ValueError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}), file=sys.stderr)
        return 2
    if args.self_test:
        print(
            json.dumps(
                {
                    "schemaVersion": "1.0",
                    "status": "passed",
                    "server": server.name,
                    "transport": args.transport,
                    "writesTargetRepository": False,
                    "performsGitMutation": False,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.transport == "streamable-http":
        server.settings.host = args.host
        server.settings.port = args.port
        server.run(transport="streamable-http")
    else:
        server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

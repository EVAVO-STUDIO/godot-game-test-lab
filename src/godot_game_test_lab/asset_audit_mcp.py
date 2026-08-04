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
except ImportError:  # Core and source-only validation do not require MCP.
    Context = Any
    FastMCP = None

from .asset_audit import REPORT_SCHEMA_VERSION, validate_asset_audit
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
from .media_production_plan import validate_media_production_plan

DEFAULT_MEDIA_CONTRACT = (
    "data/identity/brass_brine_media_production_contract_2026_08_04.json"
)


def _resolve_media_evidence_path(
    value: str,
    *,
    label: str,
    target: AssetAuditTarget,
    config: AssetAuditMcpConfig,
    allow_evidence_root: bool,
) -> Path:
    requested = Path(value).expanduser()
    if not requested.is_absolute():
        requested = Path(target.git_root) / requested
    resolved = resolve_regular_file(requested, label)
    in_target = is_within(resolved, Path(target.git_root))
    in_evidence = allow_evidence_root and is_within(
        resolved,
        config.evidence_root,
    )
    if not (in_target or in_evidence):
        boundary = (
            "the target Git root or evidence root"
            if allow_evidence_root
            else "the target Git root"
        )
        raise AssetAuditError(f"{label} must remain inside {boundary}")
    return resolved


def build_server(config: AssetAuditMcpConfig):
    if FastMCP is None:
        raise RuntimeError(
            'The asset-audit MCP requires the optional agent extra: pip install -e ".[agent]"'
        )

    server = FastMCP(
        name="EVAVO Godot Asset Audit and Media Plan Gate",
        instructions=(
            "Compare exact EVAVO Art Studio audits and game-owned media plans with "
            "stable current bytes of an allowed Godot project. Validate the audit "
            "before compiling a plan, then bind that plan to the exact game contract "
            "and audit identities. Planning mode may retain explicit repair work; "
            "strict mode requires no blockers or unresolved review. This server is "
            "read-only for target source and writes optional reports only beneath "
            "the configured evidence root."
        ),
        json_response=True,
    )

    @server.tool(name="godot_asset_audit_capabilities", structured_output=True)
    def capabilities() -> dict[str, Any]:
        return {
            "schemaVersion": "1.2",
            "resultSchemaVersion": REPORT_SCHEMA_VERSION,
            "bridge": "evavo-godot-asset-and-media-plan-gate",
            "labRoot": str(config.lab_root),
            "allowedTargetRoots": [
                str(path) for path in config.allowed_target_roots
            ],
            "evidenceRoot": str(config.evidence_root),
            "writesTargetRepository": False,
            "performsGitMutation": False,
            "tools": [
                "godot_asset_audit_capabilities",
                "godot_validate_art_audit",
                "godot_validate_media_production_plan",
            ],
            "checks": [
                "strict duplicate-key-safe Art Studio schema and type authority",
                "stable current file descriptors, byte lengths and SHA-256",
                "portable path collision and link/reparse rejection",
                "complete current art and resource inventory",
                "independent image structure, dimensions and meaningful alpha",
                "duplicate, cleanup, missing-reference and animation continuity",
                "optional exact target SHA and clean checkout",
                "final byte, inventory and Git-state rechecks",
                "exact game media-contract SHA-256 binding",
                "exact Art Studio audit SHA-256 binding",
                "work-item source, role, stage and target-root coherence",
                "recomputed blocker, review and role summaries",
                "strict no-blocker and no-review readiness",
                "role-specific native capture and listening routes",
            ],
            "truthBoundaries": [
                "A passing audit is not artistic or historical approval.",
                "A valid planning report may deliberately retain repair blockers.",
                "Strict plan validation does not prove Godot import or native rendering.",
                "Static reference analysis is not deletion authority.",
                "Compressed alpha requires decoded or native runtime verification.",
                "Native playback, audio listening and human acceptance remain separate gates.",
            ],
        }

    @server.tool(name="godot_validate_art_audit", structured_output=True)
    async def validate_art_audit(
        target: str,
        audit: str,
        ctx: Context,
        project_subpath: str | None = None,
        expected_target_sha: str | None = None,
        require_clean_target: bool = True,
        require_audit_root_match: bool = False,
        output: str | None = None,
        replace_output: bool = False,
        allow_unrecorded_assets: bool = False,
        allow_missing_references: bool = False,
        allow_animation_gaps: bool = False,
        allow_unverified_alpha: bool = False,
    ) -> dict[str, Any]:
        """Validate one exact Art Studio audit against one allowed Godot project."""
        await ctx.report_progress(
            progress=0.05,
            total=1.0,
            message="Resolving exact target and audit authority",
        )
        record = await asyncio.to_thread(
            resolve_target,
            target,
            config=config,
            project_subpath=project_subpath,
            expected_target_sha=expected_target_sha,
        )
        audit_path = resolve_audit_path(audit, target=record, config=config)
        await ctx.report_progress(
            progress=0.2,
            total=1.0,
            message="Validating stable asset bytes, alpha and continuity",
        )
        report = await asyncio.to_thread(
            validate_asset_audit,
            Path(record.project_root),
            audit_path,
            allow_unrecorded_assets=allow_unrecorded_assets,
            allow_missing_references=allow_missing_references,
            allow_animation_gaps=allow_animation_gaps,
            allow_unverified_alpha=allow_unverified_alpha,
            expected_target_sha=record.target_sha,
            require_clean_target=require_clean_target,
            require_audit_root_match=require_audit_root_match,
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
                replace=replace_output,
            )
            report["outputPath"] = str(written)
        await ctx.report_progress(
            progress=1.0,
            total=1.0,
            message="Godot asset-audit validation complete",
        )
        return report

    @server.tool(
        name="godot_validate_media_production_plan",
        structured_output=True,
    )
    async def validate_production_plan(
        target: str,
        audit: str,
        plan: str,
        ctx: Context,
        contract: str = DEFAULT_MEDIA_CONTRACT,
        project_subpath: str | None = None,
        expected_target_sha: str | None = None,
        strict: bool = False,
        output: str | None = None,
    ) -> dict[str, Any]:
        """Bind one media plan to exact game-contract and Art Studio evidence."""
        await ctx.report_progress(
            progress=0.05,
            total=1.0,
            message="Resolving exact target and media-plan authority",
        )
        record = await asyncio.to_thread(
            resolve_target,
            target,
            config=config,
            project_subpath=project_subpath,
            expected_target_sha=expected_target_sha,
        )
        contract_path = _resolve_media_evidence_path(
            contract,
            label="Game media production contract",
            target=record,
            config=config,
            allow_evidence_root=False,
        )
        audit_path = resolve_audit_path(audit, target=record, config=config)
        plan_path = _resolve_media_evidence_path(
            plan,
            label="Media production plan",
            target=record,
            config=config,
            allow_evidence_root=True,
        )
        await ctx.report_progress(
            progress=0.3,
            total=1.0,
            message="Binding plan work items to stable contract and audit bytes",
        )
        report = await asyncio.to_thread(
            validate_media_production_plan,
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
            message="Godot media production-plan validation complete",
        )
        return report

    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-asset-audit-mcp",
        description=(
            "Expose root-restricted Godot Art Studio audit and media-plan "
            "gates to MCP clients."
        ),
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
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if (
        args.transport == "streamable-http"
        and args.host not in {"127.0.0.1", "::1"}
    ):
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
        print(
            json.dumps({"status": "blocked", "error": str(error)}),
            file=sys.stderr,
        )
        return 2
    if args.self_test:
        print(
            json.dumps(
                {
                    "schemaVersion": "1.2",
                    "status": "passed",
                    "server": server.name,
                    "transport": args.transport,
                    "allowedTargetRoots": [
                        str(path) for path in config.allowed_target_roots
                    ],
                    "evidenceRoot": str(config.evidence_root),
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

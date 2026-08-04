from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .agent_bridge import (
    BridgeConfig,
    GodotAgentBridge,
    _is_within,
    _reject_symlink_components,
)
from .asset_audit import validate_asset_audit
from .native_qa_common import NativeQaError


def _audit_path(
    value: str,
    *,
    git_root: Path,
    evidence_root: Path,
) -> Path:
    requested = Path(value).expanduser()
    if not requested.is_absolute():
        requested = git_root / requested
    checked = _reject_symlink_components(requested, "Art Studio audit")
    resolved = checked.resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink():
        raise NativeQaError("Art Studio audit must be a regular JSON file")
    if not (_is_within(resolved, git_root) or _is_within(resolved, evidence_root)):
        raise NativeQaError(
            "Art Studio audit must remain inside the selected target Git root or evidence root"
        )
    return resolved


def build_server(config: BridgeConfig):
    try:
        from mcp.server.fastmcp import Context, FastMCP
    except ImportError as error:
        raise RuntimeError(
            'The asset-audit MCP requires the optional agent extra: pip install -e ".[agent]"'
        ) from error

    bridge = GodotAgentBridge(config)
    mcp = FastMCP(
        name="EVAVO Godot Asset Audit Gate",
        instructions=(
            "Use this root-restricted server to compare an EVAVO Art Studio bulk asset audit "
            "with the exact current bytes of an allowed Godot project. It validates identity, "
            "meaningful PNG alpha, current inventory, missing references and animation-family "
            "continuity. It never edits, deletes, commits, pushes or publishes the target."
        ),
        json_response=True,
    )

    @mcp.tool(name="godot_asset_audit_capabilities", structured_output=True)
    def capabilities() -> dict[str, Any]:
        return {
            "schemaVersion": "1.0",
            "tool": "godot_validate_art_audit",
            "allowedTargetRoots": [str(path) for path in config.allowed_target_roots],
            "evidenceRoot": str(config.evidence_root),
            "writesTargetRepository": False,
            "performsGitMutation": False,
            "checks": [
                "audit schema and bounded JSON",
                "portable target-contained paths",
                "current file bytes and SHA-256",
                "complete current art/resource inventory",
                "missing source and resource references",
                "numbered animation frame gaps and canvas consistency",
                "independent supported PNG meaningful-alpha evidence",
                "Art Studio blocking findings",
            ],
            "truthBoundaries": [
                "A passing audit is not artistic approval.",
                "Static path analysis is not deletion authority.",
                "Compressed alpha requires decoded or native runtime verification.",
                "Godot import, visual playback and human acceptance remain separate gates.",
            ],
        }

    @mcp.tool(name="godot_validate_art_audit", structured_output=True)
    async def validate_art_audit(
        target: str,
        audit: str,
        ctx: Context,
        project_subpath: str | None = None,
        allow_unrecorded_assets: bool = False,
        allow_missing_references: bool = False,
        allow_animation_gaps: bool = False,
        allow_unverified_alpha: bool = False,
    ) -> dict[str, Any]:
        """Validate one Art Studio bulk-media audit against an allowed Godot project."""
        await ctx.report_progress(
            progress=0.1,
            total=1.0,
            message="Resolving the allowed Godot project and Art Studio audit",
        )
        record = await asyncio.to_thread(
            bridge.target_record,
            target,
            project_subpath=project_subpath,
        )
        audit_path = _audit_path(
            audit,
            git_root=Path(record.git_root),
            evidence_root=config.evidence_root,
        )
        await ctx.report_progress(
            progress=0.3,
            total=1.0,
            message="Validating exact media identity, alpha and continuity",
        )
        result = await asyncio.to_thread(
            validate_asset_audit,
            Path(record.project_root),
            audit_path,
            allow_unrecorded_assets=allow_unrecorded_assets,
            allow_missing_references=allow_missing_references,
            allow_animation_gaps=allow_animation_gaps,
            allow_unverified_alpha=allow_unverified_alpha,
        )
        result["target"] = {
            "gitRoot": record.git_root,
            "projectRoot": record.project_root,
            "projectSubpath": record.project_subpath,
            "targetSha": record.target_sha,
        }
        await ctx.report_progress(
            progress=1.0,
            total=1.0,
            message="Godot asset-audit validation complete",
        )
        return result

    return mcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-asset-audit-mcp",
        description="Expose the root-restricted Godot Art Studio audit gate to MCP clients.",
    )
    parser.add_argument("--lab-root", type=Path)
    parser.add_argument("--allowed-root", type=Path, action="append", default=[])
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--engine-root", type=Path)
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
    if args.transport == "streamable-http" and args.host not in {"127.0.0.1", "::1"}:
        raise SystemExit("Streamable HTTP is restricted to an explicit loopback host")
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    try:
        config = BridgeConfig.from_environment(
            lab_root=args.lab_root,
            allowed_target_roots=args.allowed_root or None,
            evidence_root=args.evidence_root,
            engine_root=args.engine_root,
            require_interactive_desktop=False,
            auto_provision_engines=False,
        )
        server = build_server(config)
    except (RuntimeError, ValueError, FileNotFoundError, OSError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}), file=sys.stderr)
        return 2
    if args.self_test:
        print(
            json.dumps(
                {
                    "status": "passed",
                    "server": server.name,
                    "transport": args.transport,
                    "allowedTargetRoots": [str(path) for path in config.allowed_target_roots],
                    "evidenceRoot": str(config.evidence_root),
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

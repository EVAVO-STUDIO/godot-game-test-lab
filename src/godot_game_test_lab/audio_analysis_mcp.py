from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import Context, FastMCP
except ImportError:  # Core validation does not require MCP dependencies.
    Context = Any
    FastMCP = None

from .audio_analysis import (
    ANALYSIS_ID,
    INVENTORY_ID,
    REPORT_ID,
    SELECTION_ID,
    AudioAnalysisVerificationError,
    validate_audio_analysis,
    write_report,
)


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def _canonical_directory(value: Path, label: str) -> Path:
    requested = Path(os.path.abspath(os.fspath(value.expanduser())))
    try:
        if requested.is_symlink():
            raise AudioAnalysisVerificationError(f"{label} may not be a symbolic link")
        resolved = requested.resolve(strict=True)
    except OSError as error:
        raise AudioAnalysisVerificationError(
            f"{label} does not exist: {requested}"
        ) from error
    if not resolved.is_dir() or not _same_path(requested, resolved):
        raise AudioAnalysisVerificationError(
            f"{label} must be a canonical directory"
        )
    for component in (resolved, *resolved.parents):
        if component.is_symlink():
            raise AudioAnalysisVerificationError(
                f"{label} may not traverse a symbolic link"
            )
    return resolved


def _canonical_file(value: Path, label: str) -> Path:
    requested = Path(os.path.abspath(os.fspath(value.expanduser())))
    try:
        if requested.is_symlink():
            raise AudioAnalysisVerificationError(f"{label} may not be a symbolic link")
        resolved = requested.resolve(strict=True)
    except OSError as error:
        raise AudioAnalysisVerificationError(
            f"{label} does not exist: {requested}"
        ) from error
    if not resolved.is_file() or not _same_path(requested, resolved):
        raise AudioAnalysisVerificationError(
            f"{label} must be a canonical regular file"
        )
    for component in (resolved, *resolved.parents):
        if component.is_symlink():
            raise AudioAnalysisVerificationError(
                f"{label} may not traverse a symbolic link"
            )
    return resolved


def _roots_from_environment(name: str, fallback: Path) -> list[Path]:
    configured = os.environ.get(name, "").strip()
    if configured:
        return [
            Path(value)
            for value in configured.split(os.pathsep)
            if value.strip()
        ]
    return [fallback]


@dataclass(frozen=True)
class AudioAnalysisMcpConfig:
    lab_root: Path
    allowed_target_roots: tuple[Path, ...]
    allowed_contract_roots: tuple[Path, ...]
    evidence_root: Path

    @classmethod
    def from_environment(
        cls,
        *,
        lab_root: Path | None = None,
        allowed_target_roots: list[Path] | None = None,
        allowed_contract_roots: list[Path] | None = None,
        evidence_root: Path | None = None,
    ) -> AudioAnalysisMcpConfig:
        requested_lab = lab_root or Path(__file__).resolve().parents[2]
        resolved_lab = _canonical_directory(requested_lab, "Test Lab root")
        target_values = allowed_target_roots or _roots_from_environment(
            "EVAVO_GODOT_LAB_ALLOWED_ROOTS",
            Path.cwd(),
        )
        contract_values = allowed_contract_roots or _roots_from_environment(
            "EVAVO_GODOT_AUDIO_CONTRACT_ROOTS",
            Path.cwd(),
        )
        targets = tuple(
            dict.fromkeys(
                _canonical_directory(value, "Allowed game root")
                for value in target_values
            )
        )
        contracts = tuple(
            dict.fromkeys(
                _canonical_directory(value, "Allowed audio-contract root")
                for value in contract_values
            )
        )
        if not targets or not contracts:
            raise AudioAnalysisVerificationError(
                "At least one game root and audio-contract root are required"
            )
        requested_evidence = evidence_root or Path(
            os.environ.get(
                "EVAVO_GODOT_LAB_EVIDENCE_ROOT",
                str(Path.home() / ".local" / "share" / "EVAVO" / "GodotLabEvidence"),
            )
        )
        if not requested_evidence.is_absolute():
            raise AudioAnalysisVerificationError(
                "Audio evidence root must be absolute"
            )
        requested_evidence.mkdir(parents=True, exist_ok=True)
        resolved_evidence = _canonical_directory(
            requested_evidence,
            "Audio evidence root",
        )
        protected = (resolved_lab, *targets, *contracts)
        if any(
            _is_within(resolved_evidence, root)
            or _is_within(root, resolved_evidence)
            for root in protected
        ):
            raise AudioAnalysisVerificationError(
                "Audio evidence root must remain disjoint from source roots"
            )
        return cls(
            lab_root=resolved_lab,
            allowed_target_roots=targets,
            allowed_contract_roots=contracts,
            evidence_root=resolved_evidence,
        )


def _resolve_target(value: str, config: AudioAnalysisMcpConfig) -> Path:
    target = _canonical_directory(Path(value), "Brass & Brine target")
    if not any(_is_within(target, root) for root in config.allowed_target_roots):
        raise AudioAnalysisVerificationError(
            "Brass & Brine target is outside configured game roots"
        )
    if _is_within(target, config.lab_root) or _is_within(config.lab_root, target):
        raise AudioAnalysisVerificationError(
            "Brass & Brine target must remain disjoint from Test Lab"
        )
    return target


def _resolve_contract(value: str, config: AudioAnalysisMcpConfig) -> Path:
    contract = _canonical_file(Path(value), "Brass audio contract")
    if not any(_is_within(contract, root) for root in config.allowed_contract_roots):
        raise AudioAnalysisVerificationError(
            "Brass audio contract is outside configured contract roots"
        )
    return contract


def _resolve_evidence(value: str, label: str, config: AudioAnalysisMcpConfig) -> Path:
    requested = Path(value).expanduser()
    if not requested.is_absolute():
        requested = config.evidence_root / requested
    evidence = _canonical_file(requested, label)
    if not _is_within(evidence, config.evidence_root):
        raise AudioAnalysisVerificationError(
            f"{label} must remain below the configured evidence root"
        )
    return evidence


def capability_document(config: AudioAnalysisMcpConfig) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "bridge": "evavo-godot-brass-audio-analysis-gate",
        "report": REPORT_ID,
        "selection": SELECTION_ID,
        "inventory": INVENTORY_ID,
        "analysis": ANALYSIS_ID,
        "labRoot": str(config.lab_root),
        "allowedTargetRoots": [str(value) for value in config.allowed_target_roots],
        "allowedContractRoots": [
            str(value) for value in config.allowed_contract_roots
        ],
        "evidenceRoot": str(config.evidence_root),
        "tools": [
            "godot_audio_analysis_capabilities",
            "godot_validate_audio_analysis",
        ],
        "fixedExternalTools": ["git", "ffprobe"],
        "writesTargetRepository": False,
        "performsGitMutation": False,
        "arbitraryShellAllowed": False,
        "arbitraryGitArgumentsAllowed": False,
        "arbitraryExecutablePathsAllowed": False,
        "publicationAuthority": False,
        "humanListeningApproval": False,
        "godotGameplayMixApproval": False,
        "checks": [
            "exact current Brass main head and unchanged Git status",
            "duplicate-key-safe contract, selection, inventory and analysis JSON",
            "exact contract, selection, inventory and analysis SHA-256 binding",
            "complete selected-path equality across all retained evidence",
            "current runtime audio and Godot import sidecar identity",
            "independent WAV metadata and fixed-FFprobe compressed metadata",
            "role, bus, codec, channel, duration, loudness, peak and loop policy",
            "create-only report output and final identity recheck",
        ],
        "truthBoundaries": [
            "Independent technical validation is not human listening approval.",
            "A passing report is not native Godot gameplay-mix approval.",
            "A passing report is not provenance or release approval.",
            "Only Development Studio may execute governed publication.",
        ],
    }


def build_server(config: AudioAnalysisMcpConfig):
    if FastMCP is None:
        raise RuntimeError(
            'The audio-analysis MCP requires the agent extra: pip install -e ".[agent]"'
        )
    server = FastMCP(
        name="EVAVO Godot Brass Audio Analysis Gate",
        instructions=(
            "Independently verify exact Brass & Brine Audio Studio selection, "
            "inventory and analysis evidence against stable current game bytes. "
            "The target and contract roots are allowlisted. Evidence reads and "
            "create-only reports remain below the configured evidence root. "
            "This server performs no target mutation, Git publication, listening "
            "approval or native gameplay-mix approval."
        ),
        json_response=True,
    )

    @server.tool(name="godot_audio_analysis_capabilities", structured_output=True)
    def capabilities() -> dict[str, Any]:
        return capability_document(config)

    @server.tool(name="godot_validate_audio_analysis", structured_output=True)
    async def validate(
        target: str,
        contract: str,
        selection: str,
        inventory: str,
        analysis: str,
        ctx: Context,
        strict: bool = True,
        output: str | None = None,
    ) -> dict[str, Any]:
        await ctx.report_progress(
            progress=0.05,
            total=1.0,
            message="Resolving root-restricted Brass audio evidence",
        )
        target_path = _resolve_target(target, config)
        contract_path = _resolve_contract(contract, config)
        selection_path = _resolve_evidence(
            selection,
            "Audio publication selection",
            config,
        )
        inventory_path = _resolve_evidence(inventory, "Audio inventory", config)
        analysis_path = _resolve_evidence(
            analysis,
            "Audio Studio analysis report",
            config,
        )
        await ctx.report_progress(
            progress=0.25,
            total=1.0,
            message="Re-reading current runtime audio and upstream identities",
        )
        report = await asyncio.to_thread(
            validate_audio_analysis,
            target_path,
            contract_path,
            selection_path,
            inventory_path,
            analysis_path,
            strict=strict,
        )
        if output is not None:
            written = await asyncio.to_thread(
                write_report,
                report,
                output=Path(output),
                evidence_root=config.evidence_root,
                protected_roots=(
                    config.lab_root,
                    target_path,
                    *config.allowed_contract_roots,
                ),
            )
            report["outputPath"] = str(written)
        await ctx.report_progress(
            progress=1.0,
            total=1.0,
            message="Independent Brass audio validation complete",
        )
        return report

    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-audio-analysis-mcp",
        description="Expose root-restricted Brass audio verification to MCP clients.",
    )
    parser.add_argument("--lab-root", type=Path)
    parser.add_argument("--allowed-root", type=Path, action="append", default=[])
    parser.add_argument(
        "--contract-root",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.transport == "streamable-http" and args.host not in {"127.0.0.1", "::1"}:
        raise SystemExit("Streamable HTTP is restricted to an explicit loopback host")
    if not 1 <= args.port <= 65_535:
        raise SystemExit("--port must be between 1 and 65535")
    try:
        config = AudioAnalysisMcpConfig.from_environment(
            lab_root=args.lab_root,
            allowed_target_roots=args.allowed_root or None,
            allowed_contract_roots=args.contract_root or None,
            evidence_root=args.evidence_root,
        )
        if args.self_test:
            print(json.dumps(capability_document(config), indent=2, sort_keys=True))
            return 0
        server = build_server(config)
    except (AudioAnalysisVerificationError, RuntimeError, OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.settings.host = args.host
        server.settings.port = args.port
        server.run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

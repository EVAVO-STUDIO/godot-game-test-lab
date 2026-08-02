import argparse
import asyncio
import base64
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .agent_bridge import BridgeConfig, GodotAgentBridge


def build_server(config: BridgeConfig):
    try:
        from mcp.server.fastmcp import Context, FastMCP, Image
        from mcp.types import AudioContent
    except ImportError as error:
        raise RuntimeError(
            'The MCP bridge requires the optional agent extra: pip install -e ".[agent]"'
        ) from error

    bridge = GodotAgentBridge(config)
    mcp = FastMCP(
        name="EVAVO Godot Game Test Lab",
        instructions=(
            "Use this server for root-restricted cross-repository Godot inspection, managed "
            "official engine provisioning, exact-SHA validation, deterministic bot "
            "playtesting, native authored journeys, screenshots "
            "and synchronized audio evidence. Run inspect/audit before execution. Use retained "
            "screenshots and audio previews to review what the game looked and sounded like. "
            "The server never edits or publishes a target game."
        ),
        json_response=True,
    )

    async def _progress(ctx: Context, value: float, message: str) -> None:
        await ctx.info(message)
        await ctx.report_progress(progress=value, total=1.0, message=message)

    @mcp.tool(name="godot_capabilities", structured_output=True)
    def godot_capabilities() -> dict[str, Any]:
        """Describe allowed roots, evidence boundaries and available Godot QA operations."""
        return bridge.capabilities()

    @mcp.tool(name="godot_doctor", structured_output=True)
    async def godot_doctor(
        ctx: Context,
        godot: str | None = None,
        dotnet: str | None = None,
    ) -> dict[str, Any]:
        """Probe installed standard/.NET Godot, .NET, FFmpeg and hardware tooling."""
        await _progress(ctx, 0.1, "Probing the local Godot QA toolchain")
        result = await asyncio.to_thread(bridge.doctor, godot, dotnet)
        await _progress(ctx, 1.0, "Godot QA toolchain probe complete")
        return result

    @mcp.tool(name="godot_ensure_engine", structured_output=True)
    async def godot_ensure_engine(
        target: str,
        ctx: Context,
        project_subpath: str | None = None,
        version: str | None = None,
        flavor: str = "auto",
        install_templates: bool = True,
        offline: bool = False,
    ) -> dict[str, Any]:
        """Ensure the official checksum-verified editor required by an allowed project."""
        await _progress(ctx, 0.05, "Selecting and provisioning the governed Godot editor")
        result = await asyncio.to_thread(
            bridge.ensure_engine,
            target,
            project_subpath=project_subpath,
            version=version,
            flavor=flavor,
            install_templates=install_templates,
            offline=offline,
        )
        await _progress(ctx, 1.0, "Managed Godot editor is ready")
        return result

    @mcp.tool(name="godot_inspect", structured_output=True)
    async def godot_inspect(
        target: str,
        ctx: Context,
        project_subpath: str | None = None,
    ) -> dict[str, Any]:
        """Inspect one allowed external Godot project without executing it."""
        await _progress(ctx, 0.1, "Inspecting the target Godot project")
        result = await asyncio.to_thread(
            bridge.inspect,
            target,
            project_subpath,
        )
        await _progress(ctx, 1.0, "Godot project inspection complete")
        return result

    @mcp.tool(name="godot_audit", structured_output=True)
    async def godot_audit(
        target: str,
        ctx: Context,
        project_subpath: str | None = None,
    ) -> dict[str, Any]:
        """Audit corrupt scenes/resources, paths, Git materialization and common assets."""
        await _progress(ctx, 0.1, "Running the bounded Godot source integrity audit")
        result = await asyncio.to_thread(
            bridge.audit,
            target,
            project_subpath,
        )
        await _progress(ctx, 1.0, "Godot integrity audit complete")
        return result

    @mcp.tool(name="godot_validate", structured_output=True)
    async def godot_validate(
        target: str,
        ctx: Context,
        project_subpath: str | None = None,
        godot: str | None = None,
        dotnet: str | None = None,
        minimum_godot_version: str = "4.6.2",
        timeout_seconds: int = 300,
        boot_frames: int = 30,
    ) -> dict[str, Any]:
        """Run exact clean source audit, C# build, Godot import/recovery and bounded boot."""
        await _progress(ctx, 0.05, "Starting exact-SHA Godot validation")
        result = await asyncio.to_thread(
            bridge.validate,
            target,
            project_subpath=project_subpath,
            godot=godot,
            dotnet=dotnet,
            minimum_godot_version=minimum_godot_version,
            timeout_seconds=timeout_seconds,
            boot_frames=boot_frames,
        )
        await _progress(ctx, 1.0, "Exact-SHA Godot validation complete")
        return result

    @mcp.tool(name="godot_propose_bot_profile", structured_output=True)
    async def godot_propose_bot_profile(
        target: str,
        ctx: Context,
        project_subpath: str | None = None,
    ) -> dict[str, Any]:
        """Generate a reviewable bot-QA profile proposal outside the target repository."""
        await _progress(ctx, 0.1, "Discovering the target InputMap and rendering defaults")
        result = await asyncio.to_thread(
            bridge.propose_bot_profile,
            target,
            project_subpath=project_subpath,
        )
        await _progress(ctx, 1.0, "Bot-QA profile proposal retained")
        return result

    @mcp.tool(name="godot_run_bot_qa", structured_output=True)
    async def godot_run_bot_qa(
        target: str,
        profile: str,
        ctx: Context,
        project_subpath: str | None = None,
        godot: str | None = None,
        dotnet: str | None = None,
        minimum_godot_version: str = "4.6.2",
        timeout_seconds: int = 900,
        boot_frames: int = 30,
        maximum_total_seconds: int = 3600,
        maximum_artifact_gib: int = 20,
        window_position: str = "32,32",
        media_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run deterministic mouse/keyboard/action/gamepad bot playtesting and media review."""
        if not 1 <= maximum_artifact_gib <= 200:
            raise ValueError("maximum_artifact_gib must be between 1 and 200")
        await _progress(ctx, 0.02, "Starting deterministic Godot bot playtesting")
        result = await asyncio.to_thread(
            bridge.run_bot_qa,
            target,
            profile,
            project_subpath=project_subpath,
            godot=godot,
            dotnet=dotnet,
            minimum_godot_version=minimum_godot_version,
            timeout_seconds=timeout_seconds,
            boot_frames=boot_frames,
            maximum_total_seconds=maximum_total_seconds,
            maximum_artifact_bytes=maximum_artifact_gib * 1024**3,
            window_position=window_position,
            media_policy=media_policy,
        )
        await _progress(ctx, 1.0, "Deterministic Godot bot playtesting complete")
        return result

    @mcp.tool(name="godot_run_native_qa", structured_output=True)
    async def godot_run_native_qa(
        target: str,
        profile: str,
        ctx: Context,
        project_subpath: str | None = None,
        godot: str | None = None,
        dotnet: str | None = None,
        minimum_godot_version: str = "4.6.2",
        timeout_seconds: int = 900,
        boot_frames: int = 30,
        maximum_total_seconds: int = 3600,
        maximum_artifact_gib: int = 20,
        window_position: str = "32,32",
        media_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run target-authored native journeys and analyze visual plus audio evidence."""
        if not 1 <= maximum_artifact_gib <= 200:
            raise ValueError("maximum_artifact_gib must be between 1 and 200")
        await _progress(ctx, 0.02, "Starting authored native Godot journeys")
        result = await asyncio.to_thread(
            bridge.run_native_qa,
            target,
            profile,
            project_subpath=project_subpath,
            godot=godot,
            dotnet=dotnet,
            minimum_godot_version=minimum_godot_version,
            timeout_seconds=timeout_seconds,
            boot_frames=boot_frames,
            maximum_total_seconds=maximum_total_seconds,
            maximum_artifact_bytes=maximum_artifact_gib * 1024**3,
            window_position=window_position,
            media_policy=media_policy,
        )
        await _progress(ctx, 1.0, "Authored native Godot journeys complete")
        return result

    @mcp.tool(name="godot_run_linux_sandbox", structured_output=True)
    async def godot_run_linux_sandbox(
        target: str,
        profile: str,
        ctx: Context,
        project_subpath: str | None = None,
        timeout_seconds: int = 2700,
        cpus: float = 4.0,
        memory: str = "10g",
        memory_swap: str = "10g",
        pids_limit: int = 1024,
        nofile_limit: int = 4096,
        shm_size: str = "1g",
        rebuild_image: bool = False,
        remove_image: bool = False,
    ) -> dict[str, Any]:
        """Run exact-SHA no-network Linux software-rendered Godot QA in Docker."""
        await _progress(ctx, 0.02, "Starting isolated Linux Godot sandbox")
        result = await asyncio.to_thread(
            bridge.run_linux_sandbox,
            target,
            profile,
            project_subpath=project_subpath,
            timeout_seconds=timeout_seconds,
            cpus=cpus,
            memory=memory,
            memory_swap=memory_swap,
            pids_limit=pids_limit,
            nofile_limit=nofile_limit,
            shm_size=shm_size,
            rebuild_image=rebuild_image,
            remove_image=remove_image,
        )
        await _progress(ctx, 1.0, "Isolated Linux Godot sandbox complete")
        return result

    @mcp.tool(name="godot_analyze_run_media", structured_output=True)
    async def godot_analyze_run_media(
        run_id: str,
        ctx: Context,
        policy: dict[str, Any] | None = None,
        timeout_seconds: int = 300,
    ) -> dict[str, Any]:
        """Analyze every retained movie for audio, silence, clipping, A/V drift and previews."""
        await _progress(ctx, 0.1, "Analyzing retained Godot visual and audio recordings")
        result = await asyncio.to_thread(
            bridge.analyze_run_media,
            run_id,
            policy,
            timeout_seconds,
        )
        await _progress(ctx, 1.0, "Godot media analysis complete")
        return result

    @mcp.tool(name="godot_list_runs", structured_output=True)
    def godot_list_runs() -> list[dict[str, Any]]:
        """List bounded retained Godot QA runs available to this MCP server."""
        return bridge.list_runs()

    @mcp.tool(name="godot_review_run", structured_output=True)
    def godot_review_run(run_id: str) -> dict[str, Any]:
        """Return compact run summaries and all reviewable artifact paths."""
        return bridge.review_run(run_id)

    @mcp.tool(name="godot_list_artifacts", structured_output=True)
    def godot_list_artifacts(run_id: str) -> list[dict[str, Any]]:
        """List bounded files in one retained run with MIME types and byte counts."""
        return bridge.list_artifacts(run_id)

    @mcp.tool(name="godot_read_json", structured_output=True)
    def godot_read_json(run_id: str, path: str) -> dict[str, Any]:
        """Read one bounded JSON evidence artifact from a retained run."""
        return bridge.read_json_artifact(run_id, path)

    @mcp.tool(name="godot_view_image", structured_output=False)
    def godot_view_image(run_id: str, path: str) -> Image:
        """Return a retained screenshot, checkpoint, waveform or spectrogram to the model."""
        data, image_format = bridge.image_artifact(run_id, path)
        return Image(data=data, format=image_format)

    @mcp.tool(name="godot_hear_audio", structured_output=False)
    def godot_hear_audio(run_id: str, path: str) -> AudioContent:
        """Return a bounded retained WAV/FLAC/OGG/MP3 artifact for model audition."""
        data, mime_type = bridge.audio_artifact(run_id, path)
        return AudioContent(
            type="audio",
            data=base64.b64encode(data).decode("ascii"),
            mimeType=mime_type,
        )

    return mcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-mcp",
        description="Expose the EVAVO Godot Game Test Lab to MCP-capable Chat and Claude clients.",
    )
    parser.add_argument("--lab-root", type=Path)
    parser.add_argument("--allowed-root", type=Path, action="append", default=[])
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--engine-root", type=Path)
    parser.add_argument(
        "--no-auto-provision",
        action="store_true",
        help="Require explicit Godot paths instead of provisioning managed editors.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allow-noninteractive", action="store_true")
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
            require_interactive_desktop=not args.allow_noninteractive,
            auto_provision_engines=not args.no_auto_provision,
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
                    "capabilities": GodotAgentBridge(config).capabilities(),
                },
                sort_keys=True,
            )
        )
        return 0
    if args.transport == "streamable-http":
        server.settings.host = args.host
        server.settings.port = args.port
    server.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

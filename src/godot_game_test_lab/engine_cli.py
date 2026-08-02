from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .core import find_project_root
from .engine_manager import (
    EngineProvisionError,
    bootstrap_host,
    default_engine_root,
    ensure_project_engine,
    install_engine,
    list_installations,
    load_engine_lock,
    mirror_release_assets,
    prepare_estate,
)


def add_engine_parser(subparsers: argparse._SubParsersAction) -> None:
    engine = subparsers.add_parser(
        "engine",
        help="Provision and verify checksum-bound portable Godot editors.",
    )
    commands = engine.add_subparsers(dest="engine_command", required=True)

    status = commands.add_parser("status", help="List managed Godot installations.")
    status.add_argument("--root", type=Path)
    status.add_argument("--output", type=Path)

    install = commands.add_parser(
        "install",
        help="Install one official stable Godot editor for the current host.",
    )
    install.add_argument("--version")
    install.add_argument("--flavor", choices=("standard", "mono"), required=True)
    _add_install_options(install)

    ensure = commands.add_parser(
        "ensure",
        help="Detect a project's required branch/flavor and ensure its editor is installed.",
    )
    ensure.add_argument("project", type=Path)
    ensure.add_argument("--version")
    ensure.add_argument("--flavor", choices=("auto", "standard", "mono"), default="auto")
    _add_install_options(ensure)

    bootstrap = commands.add_parser(
        "bootstrap",
        help="Preinstall governed standard and .NET editors plus matching export templates.",
    )
    bootstrap.add_argument("--version")
    bootstrap.add_argument(
        "--flavors",
        default="standard,mono",
        help="Comma-separated subset of standard,mono.",
    )
    _add_install_options(bootstrap)

    prepare = commands.add_parser(
        "prepare",
        help="Scan a repository estate and install every required Godot branch/flavor.",
    )
    prepare.add_argument("target_root", type=Path)
    prepare.add_argument("--max-projects", type=int, default=256)
    _add_install_options(prepare)

    mirror = commands.add_parser(
        "mirror",
        help="Create a checksum-verified offline Windows/Linux Godot asset mirror.",
    )
    mirror.add_argument("destination", type=Path)
    mirror.add_argument(
        "--versions",
        help="Comma-separated stable versions; defaults to every governed channel.",
    )
    mirror.add_argument(
        "--platforms",
        default="windows-x86_64,linux-x86_64",
        help="Comma-separated Windows/Linux x86_64 or arm64 platforms.",
    )
    mirror.add_argument("--flavors", default="standard,mono")
    mirror.add_argument("--no-templates", action="store_true")
    mirror.add_argument("--lock", type=Path)
    mirror.add_argument("--output", type=Path)

    env = commands.add_parser(
        "env",
        help="Render environment variables for installed managed editors.",
    )
    env.add_argument("--root", type=Path)
    env.add_argument("--format", choices=("json", "powershell", "bash"), default="json")
    env.add_argument("--output", type=Path)


def _add_install_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-templates", action="store_true")
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--output", type=Path)


def _write(payload: Any, output: Path | None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if output is not None:
        target = output.expanduser().resolve(strict=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    print(text, end="")


def _comma_values(value: str, label: str) -> tuple[str, ...]:
    values = tuple(part.strip() for part in value.split(",") if part.strip())
    if not values or len(values) != len(set(values)):
        raise EngineProvisionError(f"{label} must be a non-empty unique comma-separated list")
    return values


def _flavors(value: str) -> tuple[str, ...]:
    values = tuple(part.strip() for part in value.split(",") if part.strip())
    if not values or any(item not in {"standard", "mono"} for item in values):
        raise EngineProvisionError("--flavors must contain standard and/or mono")
    if len(values) != len(set(values)):
        raise EngineProvisionError("--flavors may not contain duplicates")
    return values


def _environment(root: Path | None) -> dict[str, str | None]:
    installations = [
        item for item in list_installations(root) if item.get("status") == "ready"
    ]
    standard = [item for item in installations if item.get("flavor") == "standard"]
    mono = [item for item in installations if item.get("flavor") == "mono"]

    def version_key(item: dict[str, Any]) -> tuple[int, int, int]:
        return tuple(int(part) for part in str(item["version"]).split("."))

    standard.sort(key=version_key, reverse=True)
    mono.sort(key=version_key, reverse=True)
    return {
        "EVAVO_GODOT_HOME": str((root or default_engine_root()).resolve(strict=False)),
        "GODOT_BIN": str(standard[0]["executable"]) if standard else None,
        "GODOT_MONO_BIN": str(mono[0]["executable"]) if mono else None,
    }


def _render_environment(values: dict[str, str | None], format_name: str) -> str:
    if format_name == "json":
        return json.dumps(values, indent=2, ensure_ascii=False) + "\n"
    lines: list[str] = []
    for key, value in values.items():
        if value is None:
            continue
        if format_name == "powershell":
            escaped = value.replace("'", "''")
            lines.append(f"$env:{key} = '{escaped}'")
        else:
            escaped = value.replace("'", "'\\''")
            lines.append(f"export {key}='{escaped}'")
    return "\n".join(lines) + "\n"


def run_engine_command(args: argparse.Namespace) -> int:
    try:
        command = args.engine_command
        if command == "status":
            payload = {
                "schemaVersion": "1.0",
                "engineRoot": str((args.root or default_engine_root()).resolve(strict=False)),
                "installations": list_installations(args.root),
            }
            _write(payload, args.output)
            ready = bool(payload["installations"]) and all(
                item.get("status") == "ready"
                for item in payload["installations"]
            )
            return 0 if ready else 2
        if command == "install":
            governed = load_engine_lock(args.lock)
            installation = install_engine(
                version=args.version or governed.default_version,
                flavor=args.flavor,
                root=args.root,
                install_templates=not args.no_templates,
                source_dir=args.source_dir,
                offline=args.offline,
                force=args.force,
                lock=governed,
            )
            _write({"status": "ready", "installation": installation.to_dict()}, args.output)
            return 0
        if command == "ensure":
            project_root = find_project_root(args.project)
            selection, installation = ensure_project_engine(
                project_root,
                version=args.version,
                flavor=args.flavor,
                root=args.root,
                install_templates=not args.no_templates,
                source_dir=args.source_dir,
                offline=args.offline,
                force=args.force,
                lock_path=args.lock,
            )
            _write(
                {
                    "status": "ready",
                    "projectRoot": str(project_root),
                    "selection": {
                        "version": selection.version,
                        "flavor": selection.flavor,
                        "projectBranch": selection.project_branch,
                        "csharp": selection.csharp,
                        "reason": selection.reason,
                    },
                    "installation": installation.to_dict(),
                },
                args.output,
            )
            return 0
        if command == "bootstrap":
            payload = bootstrap_host(
                version=args.version,
                root=args.root,
                flavors=_flavors(args.flavors),
                install_templates=not args.no_templates,
                source_dir=args.source_dir,
                offline=args.offline,
                force=args.force,
                lock_path=args.lock,
            )
            _write(payload, args.output)
            return 0
        if command == "prepare":
            if not 1 <= args.max_projects <= 4096:
                raise EngineProvisionError("--max-projects must be between 1 and 4096")
            payload = prepare_estate(
                args.target_root,
                root=args.root,
                install_templates=not args.no_templates,
                source_dir=args.source_dir,
                offline=args.offline,
                force=args.force,
                lock_path=args.lock,
                maximum_projects=args.max_projects,
            )
            _write(payload, args.output)
            return 0 if payload["status"] == "passed" else 2
        if command == "mirror":
            versions = (
                _comma_values(args.versions, "--versions")
                if args.versions
                else None
            )
            payload = mirror_release_assets(
                args.destination,
                versions=versions,
                platforms=_comma_values(args.platforms, "--platforms"),
                flavors=_flavors(args.flavors),
                include_templates=not args.no_templates,
                lock_path=args.lock,
            )
            _write(payload, args.output)
            return 0
        if command == "env":
            values = _environment(args.root)
            text = _render_environment(values, args.format)
            if args.output is not None:
                destination = args.output.expanduser().resolve(strict=False)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(text, encoding="utf-8")
            print(text, end="")
            return 0 if values["GODOT_BIN"] or values["GODOT_MONO_BIN"] else 2
        raise EngineProvisionError(f"Unsupported engine command: {command}")
    except (EngineProvisionError, FileNotFoundError, OSError, ValueError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="godot-lab-engine")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_engine_parser(subparsers)
    arguments = ["engine", *(list(argv) if argv is not None else os.sys.argv[1:])]
    args = parser.parse_args(arguments)
    return run_engine_command(args)


if __name__ == "__main__":
    raise SystemExit(main())

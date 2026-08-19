from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import find_project_root
from .engine_manager import ensure_project_engine
from .localization_plural import (
    load_plural_testlab_request,
    run_plural_localization_validation,
)


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.strip().split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError("Godot version must use major.minor.patch")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def _resolve_engine(args: argparse.Namespace, project_root: Path) -> Path | None:
    if args.godot:
        return Path(args.godot).expanduser()
    if args.no_auto_provision_engine:
        return None
    selection, installation = ensure_project_engine(
        project_root,
        root=args.engine_root,
        source_dir=args.engine_source_dir,
        offline=args.offline_engine,
        install_templates=True,
    )
    if _version_tuple(installation.version) < _version_tuple(args.minimum_godot_version):
        selection, installation = ensure_project_engine(
            project_root,
            version=args.minimum_godot_version,
            root=args.engine_root,
            source_dir=args.engine_source_dir,
            offline=args.offline_engine,
            install_templates=True,
        )
    _ = selection
    return Path(installation.executable)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-localization-plural",
        description=(
            "Validate one exact Localization Manager Godot plural artifact against an "
            "exact external repository head using Godot Game Test Lab."
        ),
    )
    parser.add_argument("project", help="Target Godot project or a path inside it.")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--godot")
    parser.add_argument("--dotnet")
    parser.add_argument("--minimum-godot-version", default="4.6.2")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--boot-frames", type=int, default=5)
    parser.add_argument("--warnings-as-errors", action="store_true")
    parser.add_argument("--no-recovery-diagnostic", action="store_true")
    parser.add_argument("--allow-major-upgrade", action="store_true")
    parser.add_argument("--engine-root", type=Path)
    parser.add_argument("--engine-source-dir", type=Path)
    parser.add_argument("--offline-engine", action="store_true")
    parser.add_argument("--no-auto-provision-engine", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        request = load_plural_testlab_request(args.request)
        project_root = find_project_root(Path(args.project))
        godot = _resolve_engine(args, project_root)
        report = run_plural_localization_validation(
            project_root,
            request,
            artifacts_root=args.artifacts,
            godot_executable=godot,
            dotnet_executable=Path(args.dotnet).expanduser() if args.dotnet else None,
            minimum_godot_version=args.minimum_godot_version,
            timeout_seconds=max(1, args.timeout),
            boot_frames=max(0, args.boot_frames),
            warnings_as_errors=args.warnings_as_errors,
            recovery_diagnostic=not args.no_recovery_diagnostic,
            allow_major_upgrade=args.allow_major_upgrade,
        )
        text = report.to_json() + "\n"
        if args.output:
            destination = args.output.expanduser().resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
        print(text, end="")
        return 0 if report.status == "passed" else 2
    except (OSError, ValueError, json.JSONDecodeError) as error:
        payload = {
            "version": "evavo_godot_plural_localization_test_lab_error_v1",
            "status": "blocked",
            "error": str(error),
            "authority": {
                "nativeGodotImportVerified": False,
                "runtimePluralLookupVerified": False,
                "targetRepositoryMutationAuthority": False,
                "repairAuthority": False,
                "publicationAuthority": False,
            },
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

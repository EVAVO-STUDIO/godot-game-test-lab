#!/usr/bin/env python3
"""Read and validate a repository-owned Godot Linux sandbox profile."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

VERSION_RE = re.compile(r"^4\.[0-9]+\.[0-9]+$")
ALLOWED_ENGINE_FLAVORS = {"auto", "standard", "mono"}
ALLOWED_RENDERING_METHODS = {"gl_compatibility", "mobile", "forward_plus"}
MAX_ARGUMENTS = 32
MAX_ARGUMENT_BYTES = 256


class ProfileError(ValueError):
    pass


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProfileError(f"Duplicate JSON key is not allowed: {key!r}")
        value[key] = item
    return value


def _reject_non_finite(value: str) -> None:
    raise ProfileError(f"Non-finite JSON number is not allowed: {value}")


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except ProfileError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileError(f"Could not read Linux sandbox profile {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProfileError("Linux sandbox profile root must be an object.")
    return value


def _canonical_relative_path(value: Any, label: str, *, allow_dot: bool = False) -> str:
    text = str(value if value is not None else "").strip()
    if allow_dot and text in ("", "."):
        return "."
    if not text or "\\" in text or "\x00" in text or "\n" in text or "\r" in text:
        raise ProfileError(f"{label} must be a canonical relative path.")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ProfileError(f"{label} must be a canonical relative path.")
    return path.as_posix()


def _scene_path(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    if not text.startswith("res://") or "\\" in text or "\n" in text or "\r" in text:
        raise ProfileError("visual.scene must be an empty value or a canonical res:// path.")
    tail = text[6:]
    parts = tail.split("/")
    if not tail or any(part in ("", ".", "..") for part in parts):
        raise ProfileError("visual.scene must be an empty value or a canonical res:// path.")
    return "res://" + "/".join(parts)


def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfileError(f"{label} must be an integer.")
    if value < minimum or value > maximum:
        raise ProfileError(f"{label} must be between {minimum} and {maximum}.")
    return value


def _arguments(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProfileError("visual.userArguments must be an array.")
    if len(value) > MAX_ARGUMENTS:
        raise ProfileError(f"visual.userArguments may contain at most {MAX_ARGUMENTS} values.")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ProfileError(f"visual.userArguments[{index}] must be a string.")
        if (
            not item.startswith("--")
            or "\x00" in item
            or "\n" in item
            or "\r" in item
            or len(item.encode("utf-8")) > MAX_ARGUMENT_BYTES
        ):
            raise ProfileError(
                f"visual.userArguments[{index}] must be a bounded --prefixed argument."
            )
        result.append(item)
    return result


def read_profile(path: Path) -> dict[str, Any]:
    data = _load_object(path)
    if str(data.get("schemaVersion", "")) != "1.0":
        raise ProfileError("Linux sandbox profile schemaVersion must be 1.0.")

    project_subpath = _canonical_relative_path(
        data.get("projectSubpath", "."), "projectSubpath", allow_dot=True
    )
    minimum_version = str(data.get("minimumGodotVersion", "4.6.2")).strip()
    if not VERSION_RE.fullmatch(minimum_version):
        raise ProfileError("minimumGodotVersion must be an explicit Godot 4.x.y version.")

    engine_flavor = str(data.get("engineFlavor", "auto")).strip().lower()
    if engine_flavor not in ALLOWED_ENGINE_FLAVORS:
        raise ProfileError("engineFlavor must be auto, standard, or mono.")

    visual_value = data.get("visual", {})
    if not isinstance(visual_value, dict):
        raise ProfileError("visual must be an object.")
    visual_required = visual_value.get("required", True)
    if not isinstance(visual_required, bool):
        raise ProfileError("visual.required must be a boolean.")
    visual_scene = _scene_path(visual_value.get("scene", ""))
    visual_frames = _bounded_int(
        visual_value.get("frames", 180 if visual_required else 0),
        "visual.frames",
        1 if visual_required else 0,
        1800,
    )
    visual_fps = _bounded_int(visual_value.get("fps", 30), "visual.fps", 1, 120)
    visual_width = _bounded_int(visual_value.get("width", 1280), "visual.width", 320, 3840)
    visual_height = _bounded_int(
        visual_value.get("height", 720), "visual.height", 180, 2160
    )
    rendering_method = str(
        visual_value.get("renderingMethod", "gl_compatibility")
    ).strip()
    if rendering_method not in ALLOWED_RENDERING_METHODS:
        raise ProfileError(
            "visual.renderingMethod must be gl_compatibility, mobile, or forward_plus."
        )
    user_arguments = _arguments(visual_value.get("userArguments", []))

    export_value = data.get("export", {})
    if not isinstance(export_value, dict):
        raise ProfileError("export must be an object.")
    export_required = export_value.get("required", False)
    if not isinstance(export_required, bool):
        raise ProfileError("export.required must be a boolean.")
    export_preset = str(export_value.get("preset", "")).strip()
    if export_required and not export_preset:
        raise ProfileError("export.preset is required when export.required is true.")
    if len(export_preset.encode("utf-8")) > 128 or "\n" in export_preset or "\r" in export_preset:
        raise ProfileError("export.preset is invalid.")

    return {
        "schemaVersion": "1.0",
        "projectSubpath": project_subpath,
        "minimumGodotVersion": minimum_version,
        "engineFlavor": engine_flavor,
        "visual": {
            "required": visual_required,
            "scene": visual_scene,
            "frames": visual_frames,
            "fps": visual_fps,
            "width": visual_width,
            "height": visual_height,
            "renderingMethod": rendering_method,
            "userArguments": user_arguments,
        },
        "export": {
            "required": export_required,
            "preset": export_preset,
        },
    }


def _write_github_outputs(path: Path, profile: dict[str, Any]) -> None:
    visual = dict(profile["visual"])
    export = dict(profile["export"])
    values = {
        "project_subpath": profile["projectSubpath"],
        "minimum_godot_version": profile["minimumGodotVersion"],
        "engine_flavor": profile["engineFlavor"],
        "visual_required": str(bool(visual["required"])).lower(),
        "visual_scene": visual["scene"],
        "visual_frames": str(visual["frames"]),
        "visual_fps": str(visual["fps"]),
        "visual_width": str(visual["width"]),
        "visual_height": str(visual["height"]),
        "rendering_method": visual["renderingMethod"],
        "visual_arguments_json": json.dumps(
            visual["userArguments"], ensure_ascii=False, separators=(",", ":")
        ),
        "export_required": str(bool(export["required"])).lower(),
        "export_preset": export["preset"],
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        profile = read_profile(args.profile)
    except ProfileError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, indent=2))
        return 2

    rendered = json.dumps(profile, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.github_output:
        _write_github_outputs(args.github_output, profile)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

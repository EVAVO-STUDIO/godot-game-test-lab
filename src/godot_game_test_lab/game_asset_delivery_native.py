from __future__ import annotations

from pathlib import Path
from typing import Any

from .game_asset_delivery_common import (
    NATIVE_SCHEMA,
    _hash,
    _object,
    _positive_int,
    _read_json,
    _stable_file,
    _text,
    _verify_self_hash,
    _version_tuple,
    inspect_png,
    sha256_bytes,
)


def _verify_native(native_path: Path, game_head: str, contract: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    exact, file_bytes, value = _read_json(native_path, "native Godot evidence")
    if value.get("schema") != NATIVE_SCHEMA or value.get("status") != "passed":
        raise ValueError("native Godot evidence did not pass")
    native_sha = _verify_self_hash(value, "evidenceSha256", True)
    if value.get("gameHead") != game_head:
        raise ValueError("native evidence game head differs")
    minimum = (
        int(contract["minimumGodotVersion"]["major"]),
        int(contract["minimumGodotVersion"]["minor"]),
        int(contract["minimumGodotVersion"]["patch"]),
    )
    observed = _version_tuple(_text(value.get("godotVersion"), "native.godotVersion", 256))
    if observed[0] != minimum[0] or observed < minimum:
        raise ValueError("native evidence uses an unsupported Godot version")
    _text(value.get("renderer"), "native.renderer", 256)
    if value.get("importErrors") not in ([], None) or value.get("consoleErrors") not in ([], None):
        raise ValueError("native evidence contains import or console errors")
    rendered_roles = value.get("renderedRoles")
    if not isinstance(rendered_roles, list):
        raise ValueError("native.renderedRoles must be an array")
    required_roles = set(contract["requiredNativeRoles"])
    if not required_roles.issubset(set(rendered_roles)):
        raise ValueError("native evidence lacks required rendered roles")
    screenshots = value.get("screenshots")
    if not isinstance(screenshots, list) or not screenshots:
        raise ValueError("native evidence lacks screenshots")
    observed_roles: set[str] = set()
    verified_screenshots = []
    for index, raw in enumerate(screenshots):
        screenshot = _object(raw, f"native.screenshots[{index}]")
        role = _text(screenshot.get("role"), f"native.screenshots[{index}].role", 160)
        path_value = Path(_text(screenshot.get("path"), f"native.screenshots[{index}].path"))
        exact_image, image_bytes = _stable_file(path_value, f"native screenshot {role}", 128 * 1024 * 1024)
        if sha256_bytes(image_bytes) != _hash(screenshot.get("sha256"), f"native screenshot {role}.sha256"):
            raise ValueError(f"native screenshot hash differs for {role}")
        if len(image_bytes) != _positive_int(screenshot.get("bytes"), f"native screenshot {role}.bytes"):
            raise ValueError(f"native screenshot byte length differs for {role}")
        png = inspect_png(image_bytes, f"native screenshot {role}")
        if png["width"] < int(contract["minimumScreenshotWidth"]) or png["height"] < int(contract["minimumScreenshotHeight"]):
            raise ValueError(f"native screenshot resolution is too small for {role}")
        observed_roles.add(role)
        verified_screenshots.append({
            "role": role,
            "path": str(exact_image),
            "sha256": sha256_bytes(image_bytes),
            "bytes": len(image_bytes),
            **png,
        })
    if not required_roles.issubset(observed_roles):
        raise ValueError("native screenshots do not cover every required role")
    return (
        {"path": str(exact), "fileSha256": sha256_bytes(file_bytes), "evidenceSha256": native_sha},
        {
            "godotVersion": value["godotVersion"],
            "renderer": value["renderer"],
            "renderedRoles": sorted(set(rendered_roles)),
            "screenshots": sorted(verified_screenshots, key=lambda item: (item["role"], item["path"])),
        },
    )

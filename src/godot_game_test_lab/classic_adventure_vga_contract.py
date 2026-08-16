from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

REPORT_SCHEMA_VERSION = "1.0"
CONTRACT_SCHEMA_VERSION = "1.0"
MAX_CONTRACT_BYTES = 256 * 1024
MAX_ASSETS = 256
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_DECODED_BYTES = 256 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ClassicAdventureVgaError(ValueError):
    pass


def load_contract(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ClassicAdventureVgaError(f"Contract must be one regular file: {path}")
    if path.stat().st_size > MAX_CONTRACT_BYTES:
        raise ClassicAdventureVgaError("Contract exceeds the 256 KiB limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ClassicAdventureVgaError(f"Could not read contract: {error}") from error
    if not isinstance(value, dict):
        raise ClassicAdventureVgaError("Contract root must be an object")
    if value.get("schemaVersion") != CONTRACT_SCHEMA_VERSION:
        raise ClassicAdventureVgaError(
            f"schemaVersion must equal {CONTRACT_SCHEMA_VERSION}"
        )
    return value


def positive_int(value: Any, label: str, maximum: int = 16384) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ClassicAdventureVgaError(f"{label} must be an integer")
    if value < 1 or value > maximum:
        raise ClassicAdventureVgaError(f"{label} must be between 1 and {maximum}")
    return value


def bounded_float(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ClassicAdventureVgaError(f"{label} must be numeric")
    result = float(value)
    if result < minimum or result > maximum:
        raise ClassicAdventureVgaError(
            f"{label} must be between {minimum} and {maximum}"
        )
    return result


def safe_relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ClassicAdventureVgaError(f"{label} must be a non-empty string")
    if "\\" in value or "\x00" in value or "\n" in value or "\r" in value:
        raise ClassicAdventureVgaError(f"{label} must be a canonical relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ClassicAdventureVgaError(f"{label} must be a canonical relative path")
    return path.as_posix()


def safe_project_file(project_root: Path, relative_path: str) -> Path:
    target = project_root.joinpath(*PurePosixPath(relative_path).parts)
    try:
        target.relative_to(project_root)
    except ValueError as error:
        raise ClassicAdventureVgaError(
            f"Asset escapes the project root: {relative_path}"
        ) from error
    if not target.is_file() or target.is_symlink():
        raise ClassicAdventureVgaError(
            f"Asset must be one regular file inside the project: {relative_path}"
        )
    return target


def finding(
    code: str,
    message: str,
    *,
    path: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "severity": "error", "message": message}
    if path is not None:
        result["path"] = path
    if evidence:
        result["evidence"] = evidence
    return result

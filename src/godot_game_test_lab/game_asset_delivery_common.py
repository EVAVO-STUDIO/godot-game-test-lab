"""Independent installed-byte and native Godot admission for exact game-asset deliveries."""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

DELIVERY_SCHEMA = "evavo.game-asset-delivery-bundle.v2"
STORAGE_SCHEMA = "evavo.storage-game-asset-admission.v1"
NATIVE_SCHEMA = "evavo.godot-game-asset-native-evidence.v1"
CONTRACT_SCHEMA = "evavo.godot-game-asset-delivery-admission-contract.v1"
REPORT_SCHEMA = "evavo.godot-game-asset-delivery-admission.v1"
HASH64 = re.compile(r"^[0-9a-f]{64}$")
HEAD40 = re.compile(r"^[0-9a-f]{40}$")

AUTHORITY = {
    "automaticApproval": False,
    "candidatePromotion": False,
    "creativeApproval": False,
    "historicalApproval": False,
    "nativeCompositionApproval": False,
    "provenanceApproval": False,
    "gameRepositoryMutation": False,
    "gitCommit": False,
    "gitPush": False,
    "publication": False,
    "forcePush": False,
}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def hash_object(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _text(value: Any, label: str, maximum: int = 8192) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or len(value) > maximum or "\0" in value:
        raise ValueError(f"{label} is invalid")
    return value


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HASH64.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _positive_int(value: Any, label: str, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _stable_file(path_value: Path, label: str, maximum: int = 2 * 1024 * 1024 * 1024) -> tuple[Path, bytes]:
    lexical = Path(os.path.abspath(path_value))
    before = lexical.lstat()
    if lexical.is_symlink() or not lexical.is_file() or before.st_nlink != 1:
        raise ValueError(f"{label} must be a one-link regular non-symlink file")
    if before.st_size < 1 or before.st_size > maximum:
        raise ValueError(f"{label} has invalid byte length")
    exact = lexical.resolve(strict=True)
    data = exact.read_bytes()
    after = exact.stat()
    before_identity = (before.st_dev, before.st_ino, before.st_mode, before.st_nlink, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_mode, after.st_nlink, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if before_identity != after_identity or len(data) != before.st_size:
        raise ValueError(f"{label} changed while being read")
    return exact, data


def _read_json(path_value: Path, label: str) -> tuple[Path, bytes, dict[str, Any]]:
    exact, data = _stable_file(path_value, label, 256 * 1024 * 1024)
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid UTF-8 JSON: {exc}") from exc
    return exact, data, _object(value, label)


def _verify_self_hash(value: dict[str, Any], key: str, run_id: bool = True) -> str:
    stored = _hash(value.get(key), key)
    unsigned = dict(value)
    unsigned.pop(key, None)
    if run_id:
        unsigned.pop("runId", None)
    if hash_object(unsigned) != stored:
        raise ValueError(f"{key} does not match canonical content")
    if run_id and value.get("runId") != stored[:20]:
        raise ValueError(f"runId does not match {key}")
    return stored


def _all_false(value: Any, label: str) -> None:
    authority = _object(value, label)
    if not authority or any(entry is not False for entry in authority.values()):
        raise ValueError(f"{label} must remain all false")


def _target_path(value: Any, label: str) -> str:
    text = _text(value, label, 2048)
    if "\\" in text:
        raise ValueError(f"{label} must use forward slashes")
    parsed = PurePosixPath(text)
    if parsed.is_absolute() or parsed.as_posix() != text or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ValueError(f"{label} must be a canonical relative path")
    if any(part.casefold() in {".git", ".github", "secrets", "credentials"} for part in parsed.parts):
        raise ValueError(f"{label} contains a denied path component")
    return text


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _installed_file(game_root: Path, target: str, label: str) -> tuple[Path, bytes]:
    root = game_root.resolve(strict=True)
    lexical = root.joinpath(*PurePosixPath(target).parts)
    exact, data = _stable_file(lexical, label)
    if not _inside(root, exact):
        raise ValueError(f"{label} escaped game root")
    return exact, data


def _git_head(game_root: Path) -> str:
    result = subprocess.run(["git", "-C", str(game_root), "rev-parse", "HEAD"], check=False, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise ValueError(f"game root is not a readable Git checkout: {result.stderr.strip()}")
    head = result.stdout.strip()
    if not HEAD40.fullmatch(head):
        raise ValueError("game Git head is invalid")
    return head


def inspect_png(data: bytes, label: str) -> dict[str, Any]:
    if len(data) < 45 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{label} has invalid PNG signature")
    offset = 8
    width = height = bit_depth = color_type = None
    saw_end = False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError(f"{label} has truncated PNG chunk")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > len(data):
            raise ValueError(f"{label} has truncated PNG chunk data")
        chunk = data[start:end]
        expected_crc = struct.unpack(">I", data[end : end + 4])[0]
        actual_crc = binascii.crc32(chunk_type + chunk) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise ValueError(f"{label} PNG CRC differs")
        if chunk_type == b"IHDR":
            if length != 13:
                raise ValueError(f"{label} PNG IHDR length differs")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunk)
            if compression != 0 or filtering != 0 or interlace != 0:
                raise ValueError(f"{label} PNG uses unsupported compression/filter/interlace method")
        if chunk_type == b"IEND":
            saw_end = True
            offset = end + 4
            break
        offset = end + 4
    if not saw_end or offset != len(data) or not width or not height:
        raise ValueError(f"{label} PNG structure is incomplete or has trailing bytes")
    if bit_depth != 8 or color_type not in {2, 4, 6}:
        raise ValueError(f"{label} PNG must use 8-bit RGB, grayscale-alpha or RGBA")
    return {"width": width, "height": height, "bitDepth": bit_depth, "colorType": color_type}


def inspect_bmfont(data: bytes, label: str) -> dict[str, Any]:
    source = data.decode("utf-8-sig")
    if "\r" in source:
        raise ValueError(f"{label} must use LF line endings")
    lines = [line for line in source.split("\n") if line]
    info = next((line for line in lines if line.startswith("info ")), None)
    common = next((line for line in lines if line.startswith("common ")), None)
    page = next((line for line in lines if line.startswith("page ")), None)
    chars = [line for line in lines if line.startswith("char ")]
    if not info or not common or not page or not chars:
        raise ValueError(f"{label} BMFont structure is incomplete")
    if "smooth=0" not in info or "aa=1" not in info:
        raise ValueError(f"{label} must use smooth=0 and aa=1")
    if "pages=1" not in common or "packed=0" not in common:
        raise ValueError(f"{label} must use one unpacked page")
    page_match = re.search(r'file="([^"]+)"', page)
    if not page_match:
        raise ValueError(f"{label} lacks a page filename")
    ids: set[int] = set()
    for line in chars:
        match = re.search(r"\bid=(\d+)\b", line)
        if not match:
            raise ValueError(f"{label} has a char without id")
        codepoint = int(match.group(1))
        if codepoint in ids:
            raise ValueError(f"{label} duplicates codepoint {codepoint}")
        ids.add(codepoint)
    return {"pageFile": page_match.group(1), "glyphCount": len(ids)}


def inspect_godot_resource(data: bytes, label: str) -> dict[str, Any]:
    source = data.decode("utf-8-sig")
    if not (source.startswith("[gd_resource") or source.startswith("[gd_scene") or source.startswith("[resource")):
        raise ValueError(f"{label} must be a text Godot resource")
    references = sorted(set(re.findall(r'path\s*=\s*"(res://[^"\r\n]+)"', source)))
    if any(".." in value or "\\" in value for value in references):
        raise ValueError(f"{label} contains unsafe res:// reference")
    return {"references": references}


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.search(r"\b(\d+)\.(\d+)(?:\.(\d+))?\b", value)
    if not match:
        raise ValueError("native evidence lacks a parseable Godot version")
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)

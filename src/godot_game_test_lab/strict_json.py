from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any


class StrictJsonError(RuntimeError):
    """Raised when a retained JSON file is not safe to admit as evidence."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise StrictJsonError(f"duplicate JSON property: {key}")
        value[key] = item
    return value


def _parse_int(source: str) -> int:
    if source == "-0":
        raise StrictJsonError("negative zero is not accepted")
    return int(source)


def _parse_float(source: str) -> float:
    value = float(source)
    if not math.isfinite(value):
        raise StrictJsonError("non-finite JSON number is not accepted")
    if value == 0.0 and math.copysign(1.0, value) < 0:
        raise StrictJsonError("negative zero is not accepted")
    return value


def _reject_constant(source: str) -> None:
    raise StrictJsonError(f"non-standard JSON constant is not accepted: {source}")


def _validate_value(value: Any, *, depth: int = 0) -> None:
    if depth > 64:
        raise StrictJsonError("JSON nesting exceeds 64 levels")
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise StrictJsonError("JSON contains an invalid Unicode string") from error
        return
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise StrictJsonError("JSON contains a non-finite number")
        if value == 0.0 and math.copysign(1.0, value) < 0:
            raise StrictJsonError("JSON contains negative zero")
        return
    if isinstance(value, list):
        for item in value:
            _validate_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_value(key, depth=depth + 1)
            _validate_value(item, depth=depth + 1)
        return
    raise StrictJsonError(f"unsupported JSON value type: {type(value).__name__}")


def load_strict_json_object(
    path: Path,
    *,
    maximum_bytes: int,
) -> tuple[dict[str, Any], str]:
    source = Path(os.path.abspath(os.fspath(path.expanduser())))
    try:
        stats = source.lstat()
    except OSError as error:
        raise StrictJsonError(f"JSON file is unavailable: {source}") from error
    if source.is_symlink() or not source.is_file():
        raise StrictJsonError("JSON path must be a regular non-symbolic-link file")
    if stats.st_size < 1 or stats.st_size > maximum_bytes:
        raise StrictJsonError(
            f"JSON byte length must be between 1 and {maximum_bytes}"
        )
    try:
        payload = source.read_bytes()
    except OSError as error:
        raise StrictJsonError(f"JSON file could not be read: {source}") from error
    if payload.startswith(b"\xef\xbb\xbf"):
        raise StrictJsonError("UTF-8 BOM is not accepted")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise StrictJsonError("JSON file is not valid UTF-8") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_int=_parse_int,
            parse_float=_parse_float,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as error:
        raise StrictJsonError(
            f"JSON syntax is invalid at line {error.lineno}, column {error.colno}"
        ) from error
    if not isinstance(value, dict):
        raise StrictJsonError("JSON root must be an object")
    _validate_value(value)
    return value, hashlib.sha256(payload).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strict_json.py",
        description="Read one bounded UTF-8 JSON object without duplicate names.",
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--maximum-bytes", type=int, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not 1 <= args.maximum_bytes <= 64 * 1024 * 1024:
        raise SystemExit("--maximum-bytes must be between 1 and 67108864")
    try:
        value, sha256 = load_strict_json_object(
            args.input,
            maximum_bytes=args.maximum_bytes,
        )
    except (StrictJsonError, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schemaVersion": "1.0",
                    "status": "blocked",
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "status": "passed",
                "sha256": sha256,
                "value": value,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

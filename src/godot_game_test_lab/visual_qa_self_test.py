from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import uuid
import zlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_REQUIRED_LAYOUT_KEYS = {
    "overlappingInteractivePairs",
    "closeInteractivePairs",
    "ancestorClippedInteractive",
    "occludedInteractive",
}


class VisualQaSelfTestError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_digest(lab_root: Path) -> str:
    paths = [
        Path(__file__).resolve(),
        lab_root / "scripts" / "godot_input_journey.gd",
        lab_root / "schemas" / "native-agent-qa-profile.schema.json",
        lab_root / "src" / "godot_game_test_lab" / "native_qa_profile_visual.py",
        lab_root / "src" / "godot_game_test_lab" / "ui_layout_analysis.py",
        lab_root / "fixtures" / "visual-qa-overlap" / "project.godot",
        lab_root / "fixtures" / "visual-qa-overlap" / "main.tscn",
        lab_root
        / "fixtures"
        / "visual-qa-overlap"
        / "native-agent-qa.profile.json",
    ]
    digest = hashlib.sha256()
    for path in paths:
        if not path.is_file():
            raise VisualQaSelfTestError(f"Required self-test source is missing: {path}")
        digest.update(path.relative_to(lab_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_artifact_root(value: Path, lab_root: Path) -> Path:
    root = value.expanduser().resolve(strict=False)
    if root == lab_root or _is_within(root, lab_root):
        raise VisualQaSelfTestError(
            "Self-test artifacts must be outside the source repository"
        )
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve(strict=True)


def _resolve_godot(value: Path | None) -> Path | None:
    if value is not None:
        candidate = value.expanduser().resolve(strict=True)
        if not candidate.is_file():
            raise VisualQaSelfTestError(f"Godot executable is not a file: {candidate}")
        return candidate
    for name in ("godot", "godot4", "godot.exe", "Godot_v4.6.2-stable_win64.exe"):
        located = shutil.which(name)
        if located:
            return Path(located).resolve(strict=True)
    return None


def _safe_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VisualQaSelfTestError(f"{label} must be a JSON object")
    return value


def _safe_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise VisualQaSelfTestError(f"{label} must be a JSON array")
    return value


def _read_json_object(path: Path, label: str, maximum_bytes: int = 16 * 1024 * 1024) -> dict[str, Any]:
    info = path.stat()
    if not path.is_file() or info.st_size <= 0 or info.st_size > maximum_bytes:
        raise VisualQaSelfTestError(f"{label} size is outside policy: {path}")
    try:
        return _safe_mapping(json.loads(path.read_text(encoding="utf-8")), label)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisualQaSelfTestError(f"{label} is invalid JSON: {error}") from error


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    distances = (
        abs(estimate - left),
        abs(estimate - above),
        abs(estimate - upper_left),
    )
    minimum = min(distances)
    if distances[0] == minimum:
        return left
    if distances[1] == minimum:
        return above
    return upper_left


def _decode_png_rgba(path: Path, maximum_pixels: int = 4_000_000) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if not data.startswith(_PNG_SIGNATURE):
        raise VisualQaSelfTestError(f"Screenshot is not a PNG: {path}")
    offset = len(_PNG_SIGNATURE)
    width = height = 0
    bit_depth = color_type = -1
    compressed: list[bytes] = []
    seen_end = False
    while offset < len(data):
        if offset + 12 > len(data):
            raise VisualQaSelfTestError("PNG chunk header is truncated")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_end = offset + 12 + length
        if length > 128 * 1024 * 1024 or chunk_end > len(data):
            raise VisualQaSelfTestError("PNG chunk length is invalid")
        chunk_type = data[offset + 4 : offset + 8]
        chunk = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length : chunk_end])[0]
        if binascii.crc32(chunk_type + chunk) & 0xFFFFFFFF != expected_crc:
            raise VisualQaSelfTestError(
                f"PNG chunk {chunk_type!r} failed CRC validation"
            )
        if chunk_type == b"IHDR":
            if length != 13:
                raise VisualQaSelfTestError("PNG IHDR is malformed")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
            pixels = width * height
            if width <= 0 or height <= 0 or pixels > maximum_pixels:
                raise VisualQaSelfTestError("PNG dimensions are outside policy")
            if bit_depth != 8 or color_type not in {0, 2, 4, 6}:
                raise VisualQaSelfTestError(
                    f"Unsupported PNG bit depth or colour type: {bit_depth}/{color_type}"
                )
            if compression != 0 or filtering != 0 or interlace != 0:
                raise VisualQaSelfTestError(
                    "Unsupported PNG compression, filtering or interlace mode"
                )
        elif chunk_type == b"IDAT":
            compressed.append(chunk)
        elif chunk_type == b"IEND":
            seen_end = True
            break
        offset = chunk_end
    if width <= 0 or height <= 0 or not compressed or not seen_end:
        raise VisualQaSelfTestError("PNG is missing required chunks")
    source_channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    row_bytes = width * source_channels
    inflated = zlib.decompress(b"".join(compressed))
    expected = height * (row_bytes + 1)
    if len(inflated) != expected:
        raise VisualQaSelfTestError(
            f"PNG scanline length {len(inflated)} does not match {expected}"
        )
    scanlines = bytearray(height * row_bytes)
    input_offset = 0
    for y in range(height):
        filter_type = inflated[input_offset]
        input_offset += 1
        row_offset = y * row_bytes
        for x in range(row_bytes):
            raw = inflated[input_offset]
            input_offset += 1
            left = scanlines[row_offset + x - source_channels] if x >= source_channels else 0
            above = scanlines[row_offset - row_bytes + x] if y > 0 else 0
            upper_left = (
                scanlines[row_offset - row_bytes + x - source_channels]
                if y > 0 and x >= source_channels
                else 0
            )
            if filter_type == 0:
                value = raw
            elif filter_type == 1:
                value = raw + left
            elif filter_type == 2:
                value = raw + above
            elif filter_type == 3:
                value = raw + ((left + above) // 2)
            elif filter_type == 4:
                value = raw + _paeth(left, above, upper_left)
            else:
                raise VisualQaSelfTestError(
                    f"Unsupported PNG scanline filter: {filter_type}"
                )
            scanlines[row_offset + x] = value & 0xFF
    rgba = bytearray(width * height * 4)
    for pixel in range(width * height):
        source = pixel * source_channels
        target = pixel * 4
        if color_type == 0:
            gray = scanlines[source]
            rgba[target : target + 4] = bytes((gray, gray, gray, 255))
        elif color_type == 2:
            rgba[target : target + 4] = bytes(
                (
                    scanlines[source],
                    scanlines[source + 1],
                    scanlines[source + 2],
                    255,
                )
            )
        elif color_type == 4:
            gray = scanlines[source]
            rgba[target : target + 4] = bytes(
                (gray, gray, gray, scanlines[source + 1])
            )
        else:
            rgba[target : target + 4] = scanlines[source : source + 4]
    return width, height, bytes(rgba)


def _pixel_statistics(rgba: bytes, width: int, height: int) -> dict[str, Any]:
    pixels = width * height
    if len(rgba) != pixels * 4:
        raise VisualQaSelfTestError("Decoded RGBA payload has an invalid length")
    stride = max(1, pixels // 10_000)
    colours: set[bytes] = set()
    luminance_total = 0.0
    opaque_samples = 0
    for pixel in range(0, pixels, stride):
        offset = pixel * 4
        red, green, blue, alpha = rgba[offset : offset + 4]
        if alpha > 0:
            opaque_samples += 1
            luminance_total += 0.2126 * red + 0.7152 * green + 0.0722 * blue
        if len(colours) < 256:
            colours.add(rgba[offset : offset + 4])
    sampled = (pixels + stride - 1) // stride
    mean_luminance = luminance_total / opaque_samples if opaque_samples else 0.0
    return {
        "sampledPixels": sampled,
        "sampleStride": stride,
        "uniqueSampledColours": len(colours),
        "meanOpaqueLuminance": mean_luminance,
        "nonUniform": len(colours) >= 4,
        "notAllBlack": mean_luminance >= 1.0,
    }


def _run_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
    timeout: int,
) -> int:
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                timeout=timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            raise VisualQaSelfTestError(
                f"Godot visual QA fixture exceeded {timeout} seconds"
            ) from error
    return completed.returncode


def _godot_version(executable: Path, timeout: int) -> str:
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=min(timeout, 30),
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VisualQaSelfTestError(f"Godot version probe failed: {error}") from error
    text = completed.stdout.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0 or not text:
        raise VisualQaSelfTestError(
            f"Godot version probe exited {completed.returncode}: {text[:1000]}"
        )
    return text.splitlines()[0][:256]


def _write_atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(_canonical_json(value), encoding="utf-8")
    os.replace(temporary, path)


def run_visual_qa_self_test(args: argparse.Namespace) -> dict[str, Any]:
    lab_root = args.lab_root.expanduser().resolve(strict=True)
    fixture_root = lab_root / "fixtures" / "visual-qa-overlap"
    driver = lab_root / "scripts" / "godot_input_journey.gd"
    profile = fixture_root / "native-agent-qa.profile.json"
    for required in (fixture_root / "project.godot", fixture_root / "main.tscn", driver, profile):
        if not required.is_file():
            raise VisualQaSelfTestError(f"Required self-test file is missing: {required}")
    artifacts_root = _resolve_artifact_root(args.artifacts, lab_root)
    source_sha256 = _source_digest(lab_root)
    godot = _resolve_godot(args.godot)
    checked_at = datetime.now(UTC)
    latest_receipt = artifacts_root / "latest-receipt.json"
    if godot is None:
        receipt = {
            "schemaVersion": "1.0",
            "status": "source-present",
            "truth": "source-present",
            "ready": False,
            "checkedAt": checked_at.isoformat(),
            "sourceSha256": source_sha256,
            "reason": "Godot executable was not found",
            "requiredRuntime": "Godot 4.6.2 or a compatible Godot 4 runtime",
        }
        _write_atomic_json(latest_receipt, receipt)
        return receipt

    run_id = f"godot-visual-qa-{checked_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_root = artifacts_root / "runs" / run_id
    checkpoints = run_root / "checkpoints"
    run_root.mkdir(parents=True, exist_ok=False)
    checkpoints.mkdir(parents=True, exist_ok=False)
    report_path = run_root / "journey-report.json"
    stdout_path = run_root / "godot.stdout.log"
    stderr_path = run_root / "godot.stderr.log"

    environment = os.environ.copy()
    environment.update(
        {
            "EVAVO_JOURNEY_PATH": str(profile),
            "EVAVO_JOURNEY_REPORT": str(report_path),
            "EVAVO_JOURNEY_CHECKPOINT_ROOT": str(checkpoints),
            "EVAVO_JOURNEY_SCENE": "res://main.tscn",
            "EVAVO_JOURNEY_MAX_FRAMES": "180",
        }
    )
    command = [
        str(godot),
        "--path",
        str(fixture_root),
        "--rendering-method",
        "gl_compatibility",
        "--rendering-driver",
        "opengl3",
        "--resolution",
        "640x360",
    ]
    if args.headless:
        command.append("--headless")
    command.extend(["--script", str(driver)])
    exit_code = _run_process(
        command,
        cwd=fixture_root,
        environment=environment,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout=args.timeout,
    )
    report = _read_json_object(report_path, "Godot journey report")
    ui = _safe_mapping(report.get("ui"), "Godot journey report UI telemetry")
    detected: dict[str, int] = {}
    for key in sorted(_REQUIRED_LAYOUT_KEYS):
        count = len(_safe_list(ui.get(key), f"UI telemetry {key}"))
        detected[key] = count
        if count < 1:
            raise VisualQaSelfTestError(
                f"Deliberate fixture did not produce required finding: {key}"
            )
    if bool(ui.get("controlRecordsTruncated", False)) or bool(
        ui.get("interactiveRecordsTruncated", False)
    ) or bool(ui.get("pairAnalysisTruncated", False)):
        raise VisualQaSelfTestError("Godot layout telemetry was truncated")

    screenshot_path = checkpoints / "deliberate-defects.png"
    if not screenshot_path.is_file():
        screenshot_path = checkpoints / "final.png"
    if not screenshot_path.is_file():
        raise VisualQaSelfTestError("Godot did not retain a checkpoint PNG")
    width, height, rgba = _decode_png_rgba(screenshot_path)
    if (width, height) != (640, 360):
        raise VisualQaSelfTestError(
            f"Godot checkpoint dimensions are {width}x{height}, expected 640x360"
        )
    pixel_statistics = _pixel_statistics(rgba, width, height)
    if not pixel_statistics["nonUniform"] or not pixel_statistics["notAllBlack"]:
        raise VisualQaSelfTestError(
            "Godot checkpoint did not contain a non-uniform visible render"
        )
    checkpoint_ui = _safe_list(report.get("checkpointUi", []), "checkpointUi")
    if not checkpoint_ui:
        raise VisualQaSelfTestError("Godot did not retain checkpoint UI telemetry")

    evidence = []
    for path, kind in (
        (report_path, "semantic-report"),
        (screenshot_path, "rendered-pixels"),
        (stdout_path, "runtime-stdout"),
        (stderr_path, "runtime-stderr"),
    ):
        evidence.append(
            {
                "kind": kind,
                "path": path.relative_to(artifacts_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    receipt = {
        "schemaVersion": "1.0",
        "status": "locally-verified",
        "truth": "locally-verified",
        "ready": True,
        "runId": run_id,
        "checkedAt": checked_at.isoformat(),
        "expiresAt": (checked_at + timedelta(minutes=30)).isoformat(),
        "sourceSha256": source_sha256,
        "godotExecutable": str(godot),
        "godotVersion": _godot_version(godot, args.timeout),
        "displayMode": "headless-offscreen" if args.headless else "interactive-window",
        "processExitCode": exit_code,
        "expectedJourneyFailure": report.get("status") == "failed",
        "detected": detected,
        "pixelStatistics": pixel_statistics,
        "screenshot": {
            "path": screenshot_path.relative_to(artifacts_root).as_posix(),
            "width": width,
            "height": height,
            "bytes": screenshot_path.stat().st_size,
            "sha256": _sha256_file(screenshot_path),
        },
        "report": {
            "path": report_path.relative_to(artifacts_root).as_posix(),
            "bytes": report_path.stat().st_size,
            "sha256": _sha256_file(report_path),
        },
        "evidence": evidence,
        "truthBoundary": (
            "This receipt proves that the exact self-test sources launched Godot, "
            "retained non-uniform rendered pixels and detected deliberate semantic "
            "layout defects. It does not certify an unrelated game or application."
        ),
    }
    _write_atomic_json(run_root / "receipt.json", receipt)
    _write_atomic_json(latest_receipt, receipt)
    return receipt


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        prog="godot-lab-visual-qa-self-test",
        description=(
            "Render the deliberate Godot UI defect fixture and require screenshot plus "
            "semantic layout findings before issuing a local receipt."
        ),
    )
    parser.add_argument("--lab-root", type=Path, default=root)
    parser.add_argument("--godot", type=Path)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--headless", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not 10 <= args.timeout <= 900:
        raise SystemExit("--timeout must be between 10 and 900 seconds")
    try:
        receipt = run_visual_qa_self_test(args)
    except (
        VisualQaSelfTestError,
        FileNotFoundError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as error:
        result = {
            "schemaVersion": "1.0",
            "status": "failed",
            "truth": "source-present",
            "ready": False,
            "checkedAt": datetime.now(UTC).isoformat(),
            "errorType": type(error).__name__,
            "error": str(error),
        }
        print(json.dumps(result, sort_keys=True))
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt.get("ready") is True else 1


if __name__ == "__main__":
    sys.exit(main())

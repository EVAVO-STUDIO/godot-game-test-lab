"""Independent source and native admission for EVAVO/Godot pixel-font families."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import tempfile
import zlib
from pathlib import Path
from typing import Any

CONTRACT_ID = "evavo.godot-pixel-font-admission.v1"
RUNTIME_SCHEMA = "evavo.brass-brine.pixel-font-runtime.v1"
NATIVE_SCHEMA = "evavo.godot-pixel-font-native-evidence.v1"
REPORT_SCHEMA = "evavo.godot-pixel-font-admission-report.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEAD40 = re.compile(r"^[0-9a-f]{40}$")
PNG_SIG = b"\x89PNG\r\n\x1a\n"


def fail(message: str) -> None:
    raise ValueError(message)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def stable_bytes(path: Path, maximum: int = 64 * 1024 * 1024) -> bytes:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        fail(f"not a regular file: {path}")
    before = resolved.stat()
    if before.st_size < 1 or before.st_size > maximum:
        fail(f"invalid file size: {resolved}")
    data = resolved.read_bytes()
    after = resolved.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        fail(f"file changed while being read: {resolved}")
    return data


def read_object(path: Path) -> tuple[dict[str, Any], bytes]:
    data = stable_bytes(path)
    value = json.loads(data.decode("utf-8-sig"))
    if not isinstance(value, dict):
        fail(f"JSON root is not an object: {path}")
    return value, data


def verify_self_hash(value: dict[str, Any], key: str) -> None:
    stored = str(value.get(key) or "")
    if not HEX64.fullmatch(stored):
        fail(f"invalid {key}")
    body = dict(value)
    body.pop(key, None)
    body.pop("runId", None)
    actual = sha256_json(body)
    if stored != actual or value.get("runId") != actual[:20]:
        fail(f"{key} or runId mismatch")


def resolve_inside(root: Path, relative_value: str, label: str) -> Path:
    if not isinstance(relative_value, str) or not relative_value:
        fail(f"{label} path is missing")
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        fail(f"{label} escaped approved root")
    canonical_root = root.resolve(strict=True)
    candidate = (canonical_root / relative).resolve(strict=True)
    try:
        candidate.relative_to(canonical_root)
    except ValueError as error:
        raise ValueError(f"{label} escaped approved root") from error
    return candidate


def exact_file(root: Path, record: dict[str, Any], label: str) -> dict[str, Any]:
    path_value = str(record.get("path") or "")
    expected_sha = str(record.get("sha256") or "")
    expected_size = int(record.get("sizeBytes", -1))
    if not HEX64.fullmatch(expected_sha) or expected_size < 1:
        fail(f"{label} identity is invalid")
    path = resolve_inside(root, path_value, label)
    data = stable_bytes(path)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha or len(data) != expected_size:
        fail(f"{label} identity mismatch")
    return {"path": str(path), "sha256": actual, "sizeBytes": len(data)}


def parse_png(path: Path) -> dict[str, int]:
    data = stable_bytes(path)
    if not data.startswith(PNG_SIG):
        fail(f"PNG signature mismatch: {path}")
    offset = 8
    width = height = None
    saw_end = False
    while offset < len(data):
        if offset + 12 > len(data):
            fail(f"PNG chunk truncated: {path}")
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > len(data):
            fail(f"PNG data truncated: {path}")
        payload = data[start:end]
        expected_crc = struct.unpack(">I", data[end:end + 4])[0]
        if zlib.crc32(chunk_type + payload) & 0xFFFFFFFF != expected_crc:
            fail(f"PNG CRC mismatch: {path}")
        if chunk_type == b"IHDR":
            if length != 13:
                fail(f"PNG IHDR length mismatch: {path}")
            width, height = struct.unpack(">II", payload[:8])
            if payload[8] != 8 or payload[9] != 6 or payload[12] != 0:
                fail(f"PNG must be non-interlaced 8-bit RGBA: {path}")
        if chunk_type == b"IEND":
            saw_end = True
            offset = end + 4
            break
        offset = end + 4
    if not saw_end or offset != len(data) or not width or not height:
        fail(f"PNG structure incomplete: {path}")
    return {"width": width, "height": height}


def verify_runtime_manifest(game_root: Path, manifest_path: Path, game_head: str, contract: dict[str, Any]) -> dict[str, Any]:
    value, bytes_value = read_object(manifest_path)
    if value.get("schema") != RUNTIME_SCHEMA:
        fail("unexpected pixel-font runtime schema")
    verify_self_hash(value, "manifestSha256")
    if not HEAD40.fullmatch(game_head):
        fail("game head must be an exact lowercase 40-character SHA")
    godot = value.get("godot")
    if not isinstance(godot, dict):
        fail("runtime manifest lacks Godot policy")
    expected_godot = contract["godot"]
    for key, expected in expected_godot.items():
        if godot.get(key) != expected:
            fail(f"Godot pixel-font policy mismatch: {key}")
    authority = value.get("authority")
    if not isinstance(authority, dict) or any(item is not False for item in authority.values()):
        fail("runtime manifest authority is not all false")
    required_roles = set(contract["requiredRoles"])
    roles = value.get("roles")
    if not isinstance(roles, dict) or not required_roles.issubset(roles):
        fail("runtime manifest lacks required semantic roles")
    faces = value.get("family", {}).get("faces")
    if not isinstance(faces, list) or len(faces) < 5:
        fail("runtime manifest does not contain the complete font family")
    admitted_faces = []
    role_faces = set(roles.values())
    for face in faces:
        if not isinstance(face, dict):
            fail("font face record is invalid")
        face_id = str(face.get("faceId") or "")
        if not face_id or face_id not in role_faces:
            fail(f"font face is not reachable from a semantic role: {face_id}")
        atlas = exact_file(game_root, face.get("atlas") or {}, f"{face_id} atlas")
        png = parse_png(Path(atlas["path"]))
        if png["width"] != int(face.get("atlasWidth", -1)) or png["height"] != int(face.get("atlasHeight", -1)):
            fail(f"{face_id} atlas dimensions differ")
        bmfont = exact_file(game_root, face.get("bmfont") or {}, f"{face_id} BMFont")
        godot_resource = exact_file(game_root, face.get("godotResource") or {}, f"{face_id} Godot resource")
        text = Path(bmfont["path"]).read_text(encoding="utf-8-sig")
        if 'smooth=0' not in text or 'aa=0' not in text:
            fail(f"{face_id} BMFont re-enabled smoothing")
        admitted_faces.append({
            "faceId": face_id,
            "role": face.get("role"),
            "atlas": {**atlas, **png},
            "bmfont": bmfont,
            "godotResource": godot_resource,
            "glyphCount": int(face.get("glyphCount", 0)),
        })
    return {
        "manifest": {
            "path": str(manifest_path.resolve()),
            "sha256": hashlib.sha256(bytes_value).hexdigest(),
            "sizeBytes": len(bytes_value),
            "manifestSha256": value["manifestSha256"],
        },
        "faces": admitted_faces,
        "roles": sorted(required_roles),
        "godot": godot,
    }


def verify_native_evidence(value: dict[str, Any], game_root: Path, game_head: str, contract: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema") != NATIVE_SCHEMA or value.get("status") != "passed":
        fail("native pixel-font evidence did not pass")
    verify_self_hash(value, "evidenceSha256")
    if value.get("gameHead") != game_head:
        fail("native evidence game head differs")
    if value.get("importErrors") not in ([], None) or value.get("consoleErrors") not in ([], None):
        fail("native evidence contains import or console errors")
    version = str(value.get("godotVersion") or "")
    if not version.startswith(str(contract["godot"]["targetVersion"])):
        fail("native evidence Godot version differs")
    required_roles = set(contract["nativeRequiredRoles"])
    rendered_roles = set(value.get("renderedRoles") or [])
    if not required_roles.issubset(rendered_roles):
        fail("native evidence lacks required rendered roles")
    screenshots = value.get("screenshots")
    if not isinstance(screenshots, list) or not screenshots:
        fail("native evidence has no screenshots")
    admitted = []
    screenshot_roles = set()
    for record in screenshots:
        if not isinstance(record, dict):
            fail("native screenshot record is invalid")
        role = str(record.get("role") or "")
        screenshot_roles.add(role)
        identity = exact_file(game_root, record, f"native screenshot {role}")
        png = parse_png(Path(identity["path"]))
        if png["width"] != int(record.get("width", -1)) or png["height"] != int(record.get("height", -1)):
            fail("native screenshot dimensions differ")
        if int(record.get("visiblePixels", 0)) < int(contract["minimumVisiblePixels"]):
            fail("native screenshot does not contain enough visible pixels")
        if int(record.get("luminanceRange", 0)) < int(contract["minimumLuminanceRange"]):
            fail("native screenshot lacks visual contrast")
        admitted.append({**identity, **png, "role": role})
    if not required_roles.issubset(screenshot_roles):
        fail("native screenshots do not cover required roles")
    return {
        "evidenceSha256": value["evidenceSha256"],
        "godotVersion": version,
        "renderer": value.get("renderer"),
        "renderedRoles": sorted(rendered_roles),
        "screenshots": admitted,
    }


def admit(game_root: Path, runtime_manifest: Path, game_head: str, contract_path: Path, native_evidence: Path | None = None) -> dict[str, Any]:
    contract, contract_bytes = read_object(contract_path)
    if contract.get("contract") != CONTRACT_ID:
        fail("unexpected pixel-font admission contract")
    source = verify_runtime_manifest(game_root, runtime_manifest, game_head, contract)
    native = None
    input_bindings = [
        {"path": str(contract_path.resolve()), "sha256": hashlib.sha256(contract_bytes).hexdigest(), "sizeBytes": len(contract_bytes)},
        source["manifest"],
    ]
    status = "source-passed-native-pending"
    if native_evidence is not None:
        native_value, native_bytes = read_object(native_evidence)
        native = verify_native_evidence(native_value, game_root, game_head, contract)
        input_bindings.append({"path": str(native_evidence.resolve()), "sha256": hashlib.sha256(native_bytes).hexdigest(), "sizeBytes": len(native_bytes)})
        status = "passed"
    report = {
        "schema": REPORT_SCHEMA,
        "contract": CONTRACT_ID,
        "status": status,
        "gameRoot": str(game_root.resolve()),
        "gameHead": game_head,
        "sourceAdmission": source,
        "nativeAdmission": native,
        "inputBindings": sorted(input_bindings, key=lambda item: item["path"]),
        "creativeApproval": False,
        "historicalApproval": False,
        "nativeCompositionApproval": False,
        "provenanceApproval": False,
        "publicationAuthority": False,
        "authority": contract["authority"],
    }
    report["reportSha256"] = sha256_json(report)
    report["runId"] = report["reportSha256"][:20]
    return report


def atomic_write(path: Path, value: dict[str, Any], replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        fail(f"output already exists: {path}")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--runtime-manifest", type=Path, required=True)
    parser.add_argument("--game-head", required=True)
    parser.add_argument("--native-evidence", type=Path)
    parser.add_argument("--contract", type=Path, default=Path(__file__).resolve().parents[2] / "config" / "pixel-font-admission.v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    try:
        report = admit(
            args.game_root.resolve(),
            args.runtime_manifest.resolve(),
            args.game_head,
            args.contract.resolve(),
            args.native_evidence.resolve() if args.native_evidence else None,
        )
        atomic_write(args.output.resolve(), report, args.replace)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(f"pixel-font admission failed: {error}", file=os.sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "reportSha256": report["reportSha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

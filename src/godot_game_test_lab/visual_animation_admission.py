"""Independent Test Lab admission for Brass static art and SpriteFrames evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

CONTRACT_ID = "evavo.godot-visual-animation-admission.v1"
STATIC_SCHEMA = "evavo.brass-creative-candidate-evaluation.v1"
ANIMATION_SCHEMA = "evavo.brass-animation-sequence-evaluation.v1"
ENGINE_SCHEMA = "evavo.godot-visual-animation-import-evidence.v1"
REPORT_SCHEMA = "evavo.brass-visual-animation-test-lab-report.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEAD40 = re.compile(r"^[0-9a-f]{40}$")


def fail(message: str) -> None:
    raise ValueError(message)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def stable_bytes(path: Path, maximum: int = 512 * 1024 * 1024) -> bytes:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        fail(f"not a regular file: {path}")
    before = resolved.stat()
    if before.st_size > maximum:
        fail(f"file exceeds maximum bytes: {resolved}")
    data = resolved.read_bytes()
    after = resolved.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        fail(f"file changed while being read: {resolved}")
    return data


def read_object(path: Path) -> tuple[dict[str, Any], bytes]:
    data = stable_bytes(path)
    value = json.loads(data.decode("utf-8-sig"))
    if not isinstance(value, dict):
        fail(f"JSON root is not an object: {path}")
    return value, data


def exact_file(path: Path, expected_sha: str, expected_size: int | None = None) -> dict[str, Any]:
    data = stable_bytes(path, 2 * 1024 * 1024 * 1024)
    actual = hashlib.sha256(data).hexdigest()
    if not HEX64.fullmatch(str(expected_sha or "")) or actual != expected_sha:
        fail(f"file SHA-256 mismatch: {path}")
    if expected_size is not None and len(data) != int(expected_size):
        fail(f"file byte length mismatch: {path}")
    return {"path": str(path.resolve()), "sha256": actual, "sizeBytes": len(data)}


def resolve_inside(root: Path, value: str, label: str) -> Path:
    if not isinstance(value, str) or not value:
        fail(f"{label} path is missing")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        fail(f"{label} escaped approved root")
    root = root.resolve(strict=True)
    candidate = (root / relative).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} escaped approved root") from error
    return candidate


def verify_self_hash(value: dict[str, Any], key: str) -> None:
    stored = str(value.get(key) or "")
    if not HEX64.fullmatch(stored):
        fail(f"invalid {key}")
    unhashed = dict(value)
    unhashed.pop(key, None)
    unhashed.pop("runId", None)
    if sha256_json(unhashed) != stored or value.get("runId") != stored[:20]:
        fail(f"{key} or runId mismatch")


def verify_art_studio_authority(value: dict[str, Any], label: str) -> None:
    authority = value.get("authority")
    if not isinstance(authority, dict) or any(item is not False for item in authority.values()):
        fail(f"{label} authority is not all false")
    for key in ("creativeApproval", "historicalApproval", "runtimeApproval", "publicationAuthority"):
        if value.get(key) is not False:
            fail(f"{label} falsely claims {key}")


def verify_evidence_file(record: Any, label: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        fail(f"{label} evidence is missing")
    return exact_file(Path(str(record.get("path") or "")), str(record.get("sha256") or ""), int(record.get("sizeBytes", -1)))


def verify_static(value: dict[str, Any], candidate_root: Path) -> dict[str, Any]:
    if value.get("schema") != STATIC_SCHEMA or value.get("status") != "passed" or value.get("blockers") not in ([], None):
        fail("static Art Studio evaluation did not pass")
    verify_self_hash(value, "evaluationSha256")
    verify_art_studio_authority(value, "static evaluation")
    candidate = resolve_inside(candidate_root, str(value.get("candidatePath") or ""), "static candidate")
    candidate_identity = exact_file(candidate, str(value.get("candidateSha256") or ""), int(value.get("candidateSizeBytes", -1)))
    return {
        "evaluationSha256": value["evaluationSha256"],
        "candidate": candidate_identity,
        "runtimeScaleEvidence": verify_evidence_file(value.get("runtimeScaleEvidence"), "runtime-scale"),
        "matteEvidence": verify_evidence_file(value.get("matteEvidence"), "matte"),
    }


def verify_animation(value: dict[str, Any], frame_root: Path, game_root: Path) -> dict[str, Any]:
    if value.get("schema") != ANIMATION_SCHEMA or value.get("status") != "passed" or value.get("blockers") not in ([], None):
        fail("animation Art Studio evaluation did not pass")
    verify_self_hash(value, "evaluationSha256")
    verify_art_studio_authority(value, "animation evaluation")
    frames = value.get("frames")
    if not isinstance(frames, list) or not frames:
        fail("animation evaluation has no frames")
    identities = []
    for frame in frames:
        if not isinstance(frame, dict):
            fail("animation frame evidence is invalid")
        path = resolve_inside(frame_root, str(frame.get("path") or ""), "animation frame")
        identities.append(exact_file(path, str(frame.get("sha256") or ""), int(frame.get("sizeBytes", -1))))
    contact = verify_evidence_file(value.get("contactSheet"), "animation contact sheet")
    destination = str(value.get("spriteFramesDestination") or "")
    if not destination.startswith("res://"):
        fail("SpriteFrames destination is not a Godot res:// path")
    resource = resolve_inside(game_root, destination.removeprefix("res://"), "SpriteFrames resource")
    resource_bytes = stable_bytes(resource, 16 * 1024 * 1024)
    resource_text = resource_bytes.decode("utf-8-sig")
    clip_id = str(value.get("clipId") or "")
    if clip_id not in resource_text:
        fail("SpriteFrames resource lacks clip identity")
    for frame in frames:
        basename = Path(str(frame.get("path"))).name
        if basename not in resource_text:
            fail(f"SpriteFrames resource does not reference frame: {basename}")
    return {
        "evaluationSha256": value["evaluationSha256"],
        "frames": identities,
        "contactSheet": contact,
        "spriteFrames": {"path": str(resource), "sha256": hashlib.sha256(resource_bytes).hexdigest(), "sizeBytes": len(resource_bytes), "destination": destination},
    }


def verify_engine(value: dict[str, Any], game_head: str, candidate_hashes: set[str]) -> dict[str, Any]:
    if value.get("schema") != ENGINE_SCHEMA or value.get("status") != "passed":
        fail("Godot engine import evidence did not pass")
    verify_self_hash(value, "evidenceSha256")
    if value.get("gameHead") != game_head or not HEAD40.fullmatch(game_head):
        fail("engine evidence game head differs")
    if not isinstance(value.get("godotVersion"), str) or not value["godotVersion"]:
        fail("engine evidence lacks Godot version")
    if not isinstance(value.get("renderer"), str) or not value["renderer"]:
        fail("engine evidence lacks renderer")
    if value.get("importErrors") not in ([], None) or value.get("consoleErrors") not in ([], None):
        fail("engine evidence contains import or console errors")
    evidenced = set(value.get("candidateSha256s") or [])
    if not candidate_hashes.issubset(evidenced):
        fail("engine evidence does not cover every candidate or frame hash")
    if value.get("spriteFramesLoaded") is not True or value.get("firstFrameRendered") is not True or value.get("finalEvidenceFrameRendered") is not True:
        fail("engine evidence lacks SpriteFrames render proof")
    return {"evidenceSha256": value["evidenceSha256"], "godotVersion": value["godotVersion"], "renderer": value["renderer"], "candidateSha256s": sorted(evidenced)}


def admit(game_root: Path, candidate_root: Path, frame_root: Path, static_path: Path | None, animation_path: Path | None, engine_path: Path, game_head: str, contract_path: Path) -> dict[str, Any]:
    contract, contract_bytes = read_object(contract_path)
    if contract.get("contract") != CONTRACT_ID:
        fail("unexpected visual-animation admission contract")
    static_result = None
    animation_result = None
    candidate_hashes: set[str] = set()
    inputs = []
    if static_path:
        static_value, static_bytes = read_object(static_path)
        static_result = verify_static(static_value, candidate_root)
        candidate_hashes.add(static_result["candidate"]["sha256"])
        inputs.append({"path": str(static_path.resolve()), "sha256": hashlib.sha256(static_bytes).hexdigest(), "sizeBytes": len(static_bytes)})
    if animation_path:
        animation_value, animation_bytes = read_object(animation_path)
        animation_result = verify_animation(animation_value, frame_root, game_root)
        candidate_hashes.update(frame["sha256"] for frame in animation_result["frames"])
        inputs.append({"path": str(animation_path.resolve()), "sha256": hashlib.sha256(animation_bytes).hexdigest(), "sizeBytes": len(animation_bytes)})
    if not static_result and not animation_result:
        fail("at least one Art Studio evaluation is required")
    engine_value, engine_bytes = read_object(engine_path)
    engine_result = verify_engine(engine_value, game_head, candidate_hashes)
    inputs.extend([
        {"path": str(engine_path.resolve()), "sha256": hashlib.sha256(engine_bytes).hexdigest(), "sizeBytes": len(engine_bytes)},
        {"path": str(contract_path.resolve()), "sha256": hashlib.sha256(contract_bytes).hexdigest(), "sizeBytes": len(contract_bytes)},
    ])
    report = {
        "schema": REPORT_SCHEMA,
        "contract": CONTRACT_ID,
        "status": "passed",
        "gameRoot": str(game_root.resolve()),
        "gameHead": game_head,
        "staticAdmission": static_result,
        "animationAdmission": animation_result,
        "engineEvidence": engine_result,
        "inputBindings": sorted(inputs, key=lambda item: item["path"]),
        "creativeApproval": False,
        "historicalApproval": False,
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
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--frame-root", type=Path, required=True)
    parser.add_argument("--static-evaluation", type=Path)
    parser.add_argument("--animation-evaluation", type=Path)
    parser.add_argument("--engine-evidence", type=Path, required=True)
    parser.add_argument("--game-head", required=True)
    parser.add_argument("--contract", type=Path, default=Path(__file__).resolve().parents[2] / "config" / "visual-animation-admission.v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    try:
        report = admit(args.game_root, args.candidate_root, args.frame_root, args.static_evaluation, args.animation_evaluation, args.engine_evidence, args.game_head, args.contract.resolve())
        atomic_write(args.output.resolve(), report, args.replace)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(f"visual-animation admission failed: {error}", file=os.sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "reportSha256": report["reportSha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

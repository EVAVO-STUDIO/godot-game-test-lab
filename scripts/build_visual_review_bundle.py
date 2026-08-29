#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from godot_game_test_lab.native_qa_common import NativeQaError
from godot_game_test_lab.visual_review_bundle import build_visual_review_bundle


def _compact_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _source_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in (
        root / "src" / "godot_game_test_lab" / "visual_review_bundle.py",
        root / "scripts" / "build_visual_review_bundle.py",
    ):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _finalize_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise NativeQaError("Visual review manifest is not an object")
    manifest.pop("rootDigest", None)
    manifest["rootDigest"] = hashlib.sha256(_compact_json(manifest)).hexdigest()
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a digest-bound visual review bundle from Godot native QA checkpoints."
    )
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("visual-review/manifest.json"),
        help="Manifest path below the artifact root.",
    )
    parser.add_argument("--maximum-frames", type=int, default=16)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    artifact_root = args.artifact_root.expanduser().resolve(strict=True)
    result = build_visual_review_bundle(
        artifact_root,
        args.output,
        args.campaign_id,
        _source_sha256(repository_root),
        maximum_frames=args.maximum_frames,
    )
    manifest_path = artifact_root / result["manifestPath"]
    manifest = _finalize_manifest(manifest_path)
    payload = {
        "status": "created",
        "truth": "source-present",
        "campaignId": manifest["campaignId"],
        "manifestPath": str(manifest_path),
        "manifestSha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "rootDigest": manifest["rootDigest"],
        "retainedFrameCount": len(manifest["frames"]),
        "truthBoundary": (
            "The bundle is digest-bound source output. Visual completion additionally requires "
            "retrieval and inspection of the actual frame bytes."
        ),
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (NativeQaError, FileNotFoundError, OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "truth": "source-present", "error": str(error)}, sort_keys=True))
        raise SystemExit(2) from error

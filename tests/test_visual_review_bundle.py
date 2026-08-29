from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from godot_game_test_lab.native_qa_common import NativeQaError
from godot_game_test_lab.visual_review_bundle import build_visual_review_bundle

PNG = b"\x89PNG\r\n\x1a\n" + b"fixture-pixels"


def compact(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def create_fixture(root: Path) -> None:
    journey = root / "journeys" / "menu"
    checkpoints = journey / "checkpoints"
    checkpoints.mkdir(parents=True)
    (checkpoints / "menu.png").write_bytes(PNG)
    (journey / "ui-layout-analysis.json").write_text(
        json.dumps(
            {
                "snapshots": [
                    {
                        "id": "menu",
                        "analysis": {
                            "issues": [
                                {
                                    "id": "layout:overlap:save-cancel",
                                    "code": "interactive-overlap",
                                    "severity": "error",
                                    "description": "Save and Cancel overlap.",
                                    "paths": ["/root/Save", "/root/Cancel"],
                                }
                            ]
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "native-agent-summary.json").write_text(
        json.dumps(
            {
                "journeys": [
                    {
                        "id": "menu",
                        "harness": {
                            "steps": [
                                {"type": "action_tap", "accepted": True, "elapsedFrames": 4}
                            ]
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_builds_manifest_with_real_checkpoint_hashes_and_semantic_context(
    tmp_path: Path,
) -> None:
    create_fixture(tmp_path)
    result = build_visual_review_bundle(
        tmp_path,
        Path("visual-review/manifest.json"),
        "campaign-1",
        "a" * 64,
    )
    manifest_path = tmp_path / result["manifestPath"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "evavo.visual-review-bundle.v1"
    assert len(manifest["frames"]) == 1
    assert manifest["frames"][0]["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert manifest["frames"][0]["geometryDigest"] == hashlib.sha256(
        (tmp_path / "journeys" / "menu" / "ui-layout-analysis.json").read_bytes()
    ).hexdigest()
    assert manifest["findings"][0]["rule"] == "interactive-overlap"
    assert manifest["actions"][0]["kind"] == "action_tap"
    assert manifest["privacy"]["handling"] == "private-local"


def test_bundle_creation_is_create_only_and_confined(tmp_path: Path) -> None:
    create_fixture(tmp_path)
    build_visual_review_bundle(
        tmp_path,
        Path("visual-review/manifest.json"),
        "campaign-1",
        "a" * 64,
    )
    with pytest.raises(NativeQaError, match="already exists"):
        build_visual_review_bundle(
            tmp_path,
            Path("visual-review/manifest.json"),
            "campaign-1",
            "a" * 64,
        )
    with pytest.raises(NativeQaError, match="remain below"):
        build_visual_review_bundle(
            tmp_path,
            tmp_path.parent / "escape.json",
            "campaign-2",
            "a" * 64,
        )


def test_manifest_digest_can_be_finalized_against_serialized_property_order(
    tmp_path: Path,
) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    create_fixture(tmp_path)
    build_visual_review_bundle(
        tmp_path,
        Path("visual-review/manifest.json"),
        "campaign-1",
        "a" * 64,
    )
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_visual_review_bundle.py"
    spec = spec_from_file_location("build_visual_review_bundle_script", script)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest_path = tmp_path / "visual-review" / "manifest.json"
    finalized = module._finalize_manifest(manifest_path)
    parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
    root_digest = parsed.pop("rootDigest")
    assert root_digest == hashlib.sha256(compact(parsed)).hexdigest()
    assert finalized["rootDigest"] == root_digest


def test_rejects_non_png_checkpoint_bytes(tmp_path: Path) -> None:
    checkpoint = tmp_path / "journeys" / "menu" / "checkpoints"
    checkpoint.mkdir(parents=True)
    (checkpoint / "menu.png").write_bytes(b"not-a-png")
    with pytest.raises(NativeQaError, match="not a PNG"):
        build_visual_review_bundle(
            tmp_path,
            Path("visual-review/manifest.json"),
            "campaign-1",
            "a" * 64,
        )

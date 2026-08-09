from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest

from godot_game_test_lab.pixel_font_admission import admit, sha256_json


def png_bytes(width: int = 8, height: int = 8) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + (b"\xff\xff\xff\xff" * width) for _ in range(height))
    return signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def file_record(root: Path, rel: str, data: bytes) -> dict:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "sizeBytes": len(data)}


def build_fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    game = tmp_path / "game"
    game.mkdir()
    roles = {
        "title": "display",
        "body": "ui",
        "dialogue": "ui",
        "button": "ui",
        "ledger": "ledger",
        "numeric_hud": "ledger",
        "map_label": "micro",
        "symbols": "symbols",
    }
    faces = []
    for face_id, role in [("display", "display"), ("ui", "ui"), ("ledger", "ledger"), ("micro", "micro"), ("symbols", "symbols")]:
        atlas = file_record(game, f"fonts/{face_id}.png", png_bytes())
        fnt = file_record(game, f"fonts/{face_id}.fnt", f'info face="{face_id}" size=8 bold=0 italic=0 charset="" unicode=1 stretchH=100 smooth=0 aa=0\ncommon lineHeight=8 base=7 scaleW=8 scaleH=8 pages=1 packed=0\npage id=0 file="{face_id}.png"\nchars count=1\nchar id=32 x=0 y=0 width=1 height=1 xoffset=0 yoffset=0 xadvance=2 page=0 chnl=15\n'.encode())
        tres = file_record(game, f"fonts/{face_id}.tres", b'[gd_resource type="FontVariation" load_steps=2 format=3]\n')
        faces.append({"faceId": face_id, "role": role, "atlasWidth": 8, "atlasHeight": 8, "glyphCount": 1, "atlas": atlas, "bmfont": fnt, "godotResource": tres})
    manifest = {
        "schema": "evavo.brass-brine.pixel-font-runtime.v1",
        "family": {"faces": faces},
        "roles": roles,
        "godot": {"minimumVersion": "4.6.2", "targetVersion": "4.6.2", "textureFilter": "nearest", "mipmaps": False, "subpixelPositioning": False, "integerScaleOnly": True, "pixelSnap": True},
        "authority": {"publication": False, "forcePush": False},
    }
    manifest["manifestSha256"] = sha256_json(manifest)
    manifest["runId"] = manifest["manifestSha256"][:20]
    manifest_path = game / "config/runtime.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    contract = Path(__file__).resolve().parents[1] / "config" / "pixel-font-admission.v1.json"
    return game, manifest_path, contract, "a" * 40


def native_evidence(game: Path, head: str, path: Path) -> Path:
    screenshots = []
    for role in ["title", "body", "ledger", "map_label", "symbols"]:
        record = file_record(game, f"evidence/{role}.png", png_bytes(16, 16))
        screenshots.append({**record, "role": role, "width": 16, "height": 16, "visiblePixels": 256, "luminanceRange": 255})
    value = {
        "schema": "evavo.godot-pixel-font-native-evidence.v1",
        "status": "passed",
        "gameHead": head,
        "godotVersion": "4.6.2.stable",
        "renderer": "gl_compatibility",
        "renderedRoles": ["title", "body", "ledger", "map_label", "symbols"],
        "screenshots": screenshots,
        "importErrors": [],
        "consoleErrors": [],
    }
    value["evidenceSha256"] = sha256_json(value)
    value["runId"] = value["evidenceSha256"][:20]
    path.write_text(json.dumps(value, indent=2) + "\n")
    return path


def test_source_only_is_native_pending(tmp_path: Path) -> None:
    game, manifest, contract, head = build_fixture(tmp_path)
    report = admit(game, manifest, head, contract)
    assert report["status"] == "source-passed-native-pending"
    assert report["nativeAdmission"] is None
    assert report["publicationAuthority"] is False


def test_native_evidence_completes_admission(tmp_path: Path) -> None:
    game, manifest, contract, head = build_fixture(tmp_path)
    report = admit(game, manifest, head, contract, native_evidence(game, head, tmp_path / "native.json"))
    assert report["status"] == "passed"
    assert report["nativeAdmission"]["godotVersion"] == "4.6.2.stable"
    assert len(report["nativeAdmission"]["screenshots"]) == 5


def test_manifest_tampering_fails(tmp_path: Path) -> None:
    game, manifest, contract, head = build_fixture(tmp_path)
    value = json.loads(manifest.read_text())
    value["godot"]["textureFilter"] = "linear"
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="manifestSha256|runId"):
        admit(game, manifest, head, contract)


def test_path_escape_fails(tmp_path: Path) -> None:
    game, manifest, contract, head = build_fixture(tmp_path)
    value = json.loads(manifest.read_text())
    value["family"]["faces"][0]["atlas"]["path"] = "../escape.png"
    value.pop("manifestSha256")
    value.pop("runId")
    value["manifestSha256"] = sha256_json(value)
    value["runId"] = value["manifestSha256"][:20]
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="escaped approved root"):
        admit(game, manifest, head, contract)


def test_native_missing_role_fails(tmp_path: Path) -> None:
    game, manifest, contract, head = build_fixture(tmp_path)
    evidence_path = native_evidence(game, head, tmp_path / "native.json")
    value = json.loads(evidence_path.read_text())
    value["renderedRoles"].remove("symbols")
    value.pop("evidenceSha256")
    value.pop("runId")
    value["evidenceSha256"] = sha256_json(value)
    value["runId"] = value["evidenceSha256"][:20]
    evidence_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="required rendered roles"):
        admit(game, manifest, head, contract, evidence_path)


def test_native_console_error_fails(tmp_path: Path) -> None:
    game, manifest, contract, head = build_fixture(tmp_path)
    evidence_path = native_evidence(game, head, tmp_path / "native.json")
    value = json.loads(evidence_path.read_text())
    value["consoleErrors"] = ["font import warning promoted to error"]
    value.pop("evidenceSha256")
    value.pop("runId")
    value["evidenceSha256"] = sha256_json(value)
    value["runId"] = value["evidenceSha256"][:20]
    evidence_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="console errors"):
        admit(game, manifest, head, contract, evidence_path)

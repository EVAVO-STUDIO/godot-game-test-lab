from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

from godot_game_test_lab.classic_adventure_vga import validate_classic_adventure_vga


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _rgba_png(width: int, height: int, pixels: list[tuple[int, int, int, int]]) -> bytes:
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend(pixels[y * width + x])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(rows)))
        + _chunk(b"IEND", b"")
    )



def _indexed_png(
    width: int,
    height: int,
    palette: list[tuple[int, int, int]],
    indexes: list[int],
    transparency: list[int] | None = None,
) -> bytes:
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        rows.extend(indexes[y * width : (y + 1) * width])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)
    palette_bytes = b"".join(bytes(colour) for colour in palette)
    chunks = [_chunk(b"IHDR", ihdr), _chunk(b"PLTE", palette_bytes)]
    if transparency is not None:
        chunks.append(_chunk(b"tRNS", bytes(transparency)))
    chunks.extend([_chunk(b"IDAT", zlib.compress(bytes(rows))), _chunk(b"IEND", b"")])
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)

def _write_contract(root: Path, *, actor_alpha: str = "binary") -> Path:
    contract = {
        "schemaVersion": "1.0",
        "nativeCanvas": {"width": 320, "height": 200},
        "assets": [
            {
                "path": "assets/room.png",
                "role": "room-background",
                "width": 2,
                "height": 2,
                "maximumColours": 2,
                "alpha": "opaque",
                "maximumIsolatedVisiblePixelRatio": 1.0,
            },
            {
                "path": "assets/actor.png",
                "role": "actor-cel",
                "width": 2,
                "height": 2,
                "maximumColours": 3,
                "alpha": actor_alpha,
                "maximumIsolatedVisiblePixelRatio": 1.0,
            },
        ],
    }
    path = root / "classic.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    return path


def test_classic_adventure_vga_accepts_bounded_palette_and_binary_alpha(
    tmp_path: Path,
) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    room = [(10, 20, 30, 255), (40, 50, 60, 255)] * 2
    actor = [
        (0, 0, 0, 0),
        (200, 160, 80, 255),
        (200, 160, 80, 255),
        (0, 0, 0, 0),
    ]
    (assets / "room.png").write_bytes(_rgba_png(2, 2, room))
    (assets / "actor.png").write_bytes(_rgba_png(2, 2, actor))

    report = validate_classic_adventure_vga(tmp_path, _write_contract(tmp_path))

    assert report["status"] == "passed"
    assert report["assetCount"] == 2
    assert report["findings"] == []
    assert report["assets"][1]["pixels"]["alphaValues"] == [0, 255]


def test_classic_adventure_vga_rejects_partial_alpha(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    room = [(10, 20, 30, 255)] * 4
    actor = [
        (0, 0, 0, 0),
        (200, 160, 80, 128),
        (20, 160, 80, 255),
        (0, 0, 0, 0),
    ]
    (assets / "room.png").write_bytes(_rgba_png(2, 2, room))
    (assets / "actor.png").write_bytes(_rgba_png(2, 2, actor))

    report = validate_classic_adventure_vga(tmp_path, _write_contract(tmp_path))

    assert report["status"] == "failed"
    assert any(
        finding["code"] == "classic-vga-binary-alpha-violation"
        for finding in report["findings"]
    )


def test_classic_adventure_vga_rejects_palette_overflow(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    room = [
        (10, 20, 30, 255),
        (40, 50, 60, 255),
        (70, 80, 90, 255),
        (100, 110, 120, 255),
    ]
    actor = [
        (0, 0, 0, 0),
        (200, 160, 80, 255),
        (200, 160, 80, 255),
        (0, 0, 0, 0),
    ]
    (assets / "room.png").write_bytes(_rgba_png(2, 2, room))
    (assets / "actor.png").write_bytes(_rgba_png(2, 2, actor))

    report = validate_classic_adventure_vga(tmp_path, _write_contract(tmp_path))

    assert report["status"] == "failed"
    assert any(
        finding["code"] == "classic-vga-palette-budget-exceeded"
        for finding in report["findings"]
    )


def test_classic_adventure_vga_accepts_indexed_room_and_binary_actor(
    tmp_path: Path,
) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "room.png").write_bytes(
        _indexed_png(2, 2, [(10, 20, 30), (40, 50, 60)], [0, 1, 1, 0])
    )
    (assets / "actor.png").write_bytes(
        _indexed_png(
            2,
            2,
            [(0, 0, 0), (200, 160, 80)],
            [0, 1, 1, 0],
            [0, 255],
        )
    )

    report = validate_classic_adventure_vga(tmp_path, _write_contract(tmp_path))

    assert report["status"] == "passed"
    assert report["assets"][0]["pixels"]["uniqueRgbaColours"] == 2
    assert report["assets"][1]["pixels"]["alphaValues"] == [0, 255]

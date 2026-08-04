from __future__ import annotations

import struct
import zlib

import pytest

from godot_game_test_lab.asset_audit_png import probe_image_bytes


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    distances = (
        abs(estimate - left),
        abs(estimate - above),
        abs(estimate - upper_left),
    )
    if distances[0] <= distances[1] and distances[0] <= distances[2]:
        return left
    if distances[1] <= distances[2]:
        return above
    return upper_left


def _filtered(current: bytes, previous: bytes, filter_type: int, bpp: int) -> bytes:
    encoded = bytearray(len(current))
    for index, value in enumerate(current):
        left = current[index - bpp] if index >= bpp else 0
        above = previous[index]
        upper_left = previous[index - bpp] if index >= bpp else 0
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = above
        elif filter_type == 3:
            predictor = (left + above) // 2
        elif filter_type == 4:
            predictor = _paeth(left, above, upper_left)
        else:
            raise AssertionError(filter_type)
        encoded[index] = (value - predictor) & 0xFF
    return bytes(encoded)


def _png(
    *,
    width: int,
    height: int,
    bit_depth: int,
    colour_type: int,
    rows: list[bytes],
    filters: list[int],
    trns: bytes | None = None,
) -> bytes:
    channels = {3: 1, 4: 2, 6: 4}[colour_type]
    sample_bytes = 1 if bit_depth <= 8 else 2
    bpp = channels * sample_bytes
    previous = bytes(len(rows[0]))
    encoded = bytearray()
    for row, filter_type in zip(rows, filters, strict=True):
        encoded.append(filter_type)
        encoded.extend(_filtered(row, previous, filter_type, bpp))
        previous = row
    header = struct.pack(">IIBBBBB", width, height, bit_depth, colour_type, 0, 0, 0)
    parts = [b"\x89PNG\r\n\x1a\n", _chunk(b"IHDR", header)]
    if trns is not None:
        parts.append(_chunk(b"tRNS", trns))
    parts.extend((_chunk(b"IDAT", zlib.compress(bytes(encoded))), _chunk(b"IEND", b"")))
    return b"".join(parts)


@pytest.mark.parametrize("filter_type", range(5))
def test_all_png_scanline_filters_preserve_meaningful_alpha(filter_type: int) -> None:
    row_a = bytes((255, 0, 0, 255, 0, 255, 0, 0))
    row_b = bytes((0, 0, 255, 128, 255, 255, 255, 255))
    data = _png(
        width=2,
        height=2,
        bit_depth=8,
        colour_type=6,
        rows=[row_a, row_b],
        filters=[filter_type, filter_type],
    )
    probe = probe_image_bytes(data, ".png")
    assert probe.valid is True
    assert probe.probe_complete is True
    assert probe.alpha_usage == "meaningful"
    assert (probe.width, probe.height) == (2, 2)


def test_16_bit_png_alpha_is_decoded_exactly() -> None:
    row = b"".join(
        (
            struct.pack(">HHHH", 65535, 0, 0, 65535),
            struct.pack(">HHHH", 0, 65535, 0, 1),
        )
    )
    data = _png(
        width=2,
        height=1,
        bit_depth=16,
        colour_type=6,
        rows=[row],
        filters=[0],
    )
    probe = probe_image_bytes(data, ".png")
    assert probe.valid is True
    assert probe.bit_depth == 16
    assert probe.alpha_usage == "meaningful"


def test_indexed_trns_is_retained_as_unverified_not_false_proof() -> None:
    data = _png(
        width=1,
        height=1,
        bit_depth=8,
        colour_type=3,
        rows=[b"\x00"],
        filters=[0],
        trns=b"\x00",
    )
    probe = probe_image_bytes(data, ".png")
    assert probe.valid is True
    assert probe.has_alpha_channel is True
    assert probe.alpha_usage == "unknown"
    assert probe.probe_complete is False


def test_png_trailing_bytes_and_bad_crc_fail_closed() -> None:
    data = _png(
        width=1,
        height=1,
        bit_depth=8,
        colour_type=6,
        rows=[bytes((255, 255, 255, 0))],
        filters=[0],
    )
    trailing = probe_image_bytes(data + b"unexpected", ".png")
    assert trailing.valid is False
    corrupted = bytearray(data)
    corrupted[-5] ^= 0x40
    bad_crc = probe_image_bytes(bytes(corrupted), ".png")
    assert bad_crc.valid is False
    assert any("CRC" in warning for warning in bad_crc.warnings)

from __future__ import annotations

import struct
import zlib
from typing import Any

from .classic_adventure_vga_contract import (
    MAX_DECODED_BYTES,
    PNG_SIGNATURE,
    ClassicAdventureVgaError,
)


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def _png_chunks(
    data: bytes,
) -> tuple[int, int, int, bytes | None, bytes | None, list[bytes]]:
    if data[:8] != PNG_SIGNATURE:
        raise ClassicAdventureVgaError("PNG signature is invalid")
    offset = 8
    ihdr: tuple[int, int, int] | None = None
    palette: bytes | None = None
    transparency: bytes | None = None
    idat: list[bytes] = []
    saw_iend = False
    idat_closed = False
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        chunk_type = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        crc_end = end + 4
        if crc_end > len(data):
            raise ClassicAdventureVgaError("PNG chunk exceeds file bounds")
        payload = data[start:end]
        expected_crc = struct.unpack_from(">I", data, end)[0]
        actual_crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise ClassicAdventureVgaError("PNG chunk CRC is invalid")
        if ihdr is None and chunk_type != b"IHDR":
            raise ClassicAdventureVgaError("PNG IHDR must be the first chunk")
        if chunk_type == b"IHDR":
            if length != 13 or ihdr is not None:
                raise ClassicAdventureVgaError("PNG must contain one exact IHDR")
            width, height, bit_depth, colour_type, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", payload)
            )
            if not width or not height:
                raise ClassicAdventureVgaError("PNG dimensions must be positive")
            if bit_depth != 8 or colour_type not in {2, 3, 6}:
                raise ClassicAdventureVgaError(
                    "Classic VGA QA requires 8-bit indexed, RGB, or RGBA PNG bytes"
                )
            if compression != 0 or filtering != 0 or interlace != 0:
                raise ClassicAdventureVgaError(
                    "Classic VGA QA requires non-interlaced baseline PNG encoding"
                )
            ihdr = (width, height, colour_type)
        elif chunk_type == b"PLTE":
            if palette is not None or idat:
                raise ClassicAdventureVgaError("PNG PLTE must occur once before IDAT")
            if not payload or len(payload) % 3 != 0 or len(payload) > 768:
                raise ClassicAdventureVgaError(
                    "PNG palette is malformed or exceeds 256 entries"
                )
            palette = payload
        elif chunk_type == b"tRNS":
            if transparency is not None or idat:
                raise ClassicAdventureVgaError("PNG tRNS must occur once before IDAT")
            transparency = payload
        elif chunk_type == b"IDAT":
            if idat_closed:
                raise ClassicAdventureVgaError("PNG IDAT chunks must remain consecutive")
            idat.append(payload)
        elif chunk_type == b"IEND":
            if length != 0:
                raise ClassicAdventureVgaError("PNG IEND must be empty")
            saw_iend = True
            offset = crc_end
            break
        elif idat:
            idat_closed = True
        offset = crc_end
    if ihdr is None or not idat or not saw_iend or offset != len(data):
        raise ClassicAdventureVgaError(
            "PNG is incomplete, contains trailing bytes, or is missing image data"
        )
    width, height, colour_type = ihdr
    if colour_type == 3:
        if palette is None:
            raise ClassicAdventureVgaError("Indexed PNG is missing its PLTE palette")
        palette_entries = len(palette) // 3
        if transparency is not None and len(transparency) > palette_entries:
            raise ClassicAdventureVgaError("Indexed PNG tRNS exceeds its palette")
    elif transparency is not None:
        raise ClassicAdventureVgaError(
            "Classic VGA QA accepts tRNS only for indexed PNG assets"
        )
    return width, height, colour_type, palette, transparency, idat


def decode_png_rgba(data: bytes) -> tuple[int, int, bytes]:
    width, height, colour_type, palette, transparency, idat = _png_chunks(data)
    channels = {2: 3, 3: 1, 6: 4}[colour_type]
    row_bytes = width * channels
    expected = height * (row_bytes + 1)
    if expected > MAX_DECODED_BYTES:
        raise ClassicAdventureVgaError("Decoded image exceeds the 256 MiB limit")
    try:
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(b"".join(idat), expected + 1)
        if len(decoded) > expected or decompressor.unconsumed_tail:
            raise ClassicAdventureVgaError("Decoded PNG exceeds the declared canvas")
        decoded += decompressor.flush()
    except zlib.error as error:
        raise ClassicAdventureVgaError(f"PNG decompression failed: {error}") from error
    if not decompressor.eof or decompressor.unused_data or len(decoded) != expected:
        raise ClassicAdventureVgaError(
            "PNG scanline bytes do not match the declared canvas"
        )

    previous = bytearray(row_bytes)
    cursor = 0
    rgba = bytearray(width * height * 4)
    output = 0
    for _row in range(height):
        filter_type = decoded[cursor]
        cursor += 1
        current = bytearray(row_bytes)
        for index in range(row_bytes):
            encoded = decoded[cursor + index]
            left = current[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                value = encoded
            elif filter_type == 1:
                value = encoded + left
            elif filter_type == 2:
                value = encoded + above
            elif filter_type == 3:
                value = encoded + ((left + above) // 2)
            elif filter_type == 4:
                value = encoded + _paeth(left, above, upper_left)
            else:
                raise ClassicAdventureVgaError(
                    f"PNG uses unsupported scanline filter {filter_type}"
                )
            current[index] = value & 0xFF
        cursor += row_bytes
        for pixel in range(width):
            source = pixel * channels
            if colour_type == 3:
                assert palette is not None
                palette_index = current[source]
                palette_offset = palette_index * 3
                if palette_offset + 3 > len(palette):
                    raise ClassicAdventureVgaError(
                        "Indexed PNG references a palette entry that does not exist"
                    )
                rgba[output : output + 3] = palette[palette_offset : palette_offset + 3]
                rgba[output + 3] = (
                    transparency[palette_index]
                    if transparency is not None and palette_index < len(transparency)
                    else 255
                )
            else:
                rgba[output : output + 3] = current[source : source + 3]
                rgba[output + 3] = current[source + 3] if channels == 4 else 255
            output += 4
        previous = current
    return width, height, bytes(rgba)


def pixel_metrics(width: int, height: int, rgba: bytes) -> dict[str, Any]:
    colours: set[bytes] = set()
    alpha_values: set[int] = set()
    visible = bytearray(width * height)
    hidden_rgb = 0
    for index in range(width * height):
        offset = index * 4
        colour = rgba[offset : offset + 4]
        colours.add(colour)
        alpha = colour[3]
        alpha_values.add(alpha)
        if alpha > 0:
            visible[index] = 1
        elif colour[:3] != b"\x00\x00\x00":
            hidden_rgb += 1

    isolated = 0
    visible_count = sum(visible)
    for y in range(height):
        for x in range(width):
            index = y * width + x
            if not visible[index]:
                continue
            neighbours = 0
            if x > 0:
                neighbours += visible[index - 1]
            if x + 1 < width:
                neighbours += visible[index + 1]
            if y > 0:
                neighbours += visible[index - width]
            if y + 1 < height:
                neighbours += visible[index + width]
            if neighbours == 0:
                isolated += 1
    isolated_ratio = isolated / visible_count if visible_count else 0.0
    return {
        "uniqueRgbaColours": len(colours),
        "alphaValues": sorted(alpha_values),
        "visiblePixels": visible_count,
        "transparentPixels": width * height - visible_count,
        "hiddenTransparentRgbPixels": hidden_rgb,
        "isolatedVisiblePixels": isolated,
        "isolatedVisiblePixelRatio": round(isolated_ratio, 8),
    }

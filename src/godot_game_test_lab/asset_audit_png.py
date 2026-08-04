from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass

MAX_DECODED_ALPHA_BYTES = 256 * 1024 * 1024
MAX_PNG_CHUNKS = 100_000


@dataclass(frozen=True)
class ImageProbe:
    format: str
    width: int | float | None
    height: int | float | None
    bit_depth: int | None
    colour_model: str | None
    has_alpha_channel: bool
    alpha_usage: str
    probe_complete: bool
    valid: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "bitDepth": self.bit_depth,
            "colourModel": self.colour_model,
            "hasAlphaChannel": self.has_alpha_channel,
            "alphaUsage": self.alpha_usage,
            "probeComplete": self.probe_complete,
            "valid": self.valid,
            "warnings": list(self.warnings),
        }


def _invalid(format_name: str, message: str) -> ImageProbe:
    return ImageProbe(
        format=format_name,
        width=None,
        height=None,
        bit_depth=None,
        colour_model=None,
        has_alpha_channel=False,
        alpha_usage="unknown",
        probe_complete=False,
        valid=False,
        warnings=(message,),
    )


def _unknown(format_name: str, message: str) -> ImageProbe:
    return ImageProbe(
        format=format_name,
        width=None,
        height=None,
        bit_depth=None,
        colour_model=None,
        has_alpha_channel=False,
        alpha_usage="unknown",
        probe_complete=False,
        valid=True,
        warnings=(message,),
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


def _png_probe(data: bytes) -> ImageProbe:
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return _invalid("png", "PNG signature is invalid")

    offset = 8
    chunk_count = 0
    width = height = bit_depth = colour_type = None
    compression_method = filter_method = interlace = None
    idat: list[bytes] = []
    has_trns = False
    saw_ihdr = False
    saw_iend = False
    saw_idat = False
    idat_closed = False
    colour_models = {
        0: "greyscale",
        2: "truecolour",
        3: "indexed",
        4: "greyscale-alpha",
        6: "rgba",
    }
    valid_bit_depths = {
        0: {1, 2, 4, 8, 16},
        2: {8, 16},
        3: {1, 2, 4, 8},
        4: {8, 16},
        6: {8, 16},
    }

    while offset + 12 <= len(data):
        chunk_count += 1
        if chunk_count > MAX_PNG_CHUNKS:
            return _invalid("png", "PNG exceeds the bounded chunk-count limit")
        length = struct.unpack_from(">I", data, offset)[0]
        chunk_type = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        crc_end = end + 4
        if crc_end > len(data):
            return _invalid("png", "PNG chunk exceeds file bounds")
        payload = data[start:end]
        expected_crc = struct.unpack_from(">I", data, end)[0]
        actual_crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            return _invalid(
                "png",
                f"PNG chunk CRC mismatch for {chunk_type.decode('ascii', errors='replace')}",
            )
        if not saw_ihdr and chunk_type != b"IHDR":
            return _invalid("png", "PNG IHDR must be the first chunk")
        if chunk_type == b"IHDR":
            if saw_ihdr or length != 13:
                return _invalid("png", "PNG must contain one exact 13-byte IHDR")
            (
                width,
                height,
                bit_depth,
                colour_type,
                compression_method,
                filter_method,
                interlace,
            ) = struct.unpack(">IIBBBBB", payload)
            saw_ihdr = True
        elif chunk_type == b"IDAT":
            if idat_closed:
                return _invalid("png", "PNG IDAT chunks must remain consecutive")
            saw_idat = True
            idat.append(payload)
        elif chunk_type == b"tRNS":
            has_trns = True
        elif chunk_type == b"IEND":
            if length != 0:
                return _invalid("png", "PNG IEND must be empty")
            saw_iend = True
            offset = crc_end
            break
        elif saw_idat:
            idat_closed = True
        offset = crc_end

    if not saw_ihdr or not saw_idat or not saw_iend or offset != len(data):
        return _invalid("png", "PNG structure is incomplete or contains trailing bytes")
    if not width or not height or bit_depth is None or colour_type is None:
        return _invalid("png", "PNG IHDR is incomplete")
    if compression_method != 0 or filter_method != 0:
        return _invalid("png", "PNG uses an unsupported compression or filter method")
    if colour_type not in valid_bit_depths or bit_depth not in valid_bit_depths[colour_type]:
        return _invalid("png", "PNG colour type and bit depth are inconsistent")
    colour_model = colour_models[colour_type]
    has_alpha_channel = colour_type in {4, 6} or has_trns

    if colour_type not in {4, 6}:
        warnings = (
            ("PNG tRNS transparency requires decoded-image QA",)
            if has_trns
            else ()
        )
        return ImageProbe(
            format="png",
            width=width,
            height=height,
            bit_depth=bit_depth,
            colour_model=colour_model,
            has_alpha_channel=has_alpha_channel,
            alpha_usage="unknown" if has_trns else "none",
            probe_complete=not has_trns,
            valid=True,
            warnings=warnings,
        )
    if interlace != 0:
        return ImageProbe(
            format="png",
            width=width,
            height=height,
            bit_depth=bit_depth,
            colour_model=colour_model,
            has_alpha_channel=True,
            alpha_usage="unknown",
            probe_complete=False,
            valid=True,
            warnings=("Interlaced PNG alpha requires decoded-image QA",),
        )

    channels = 4 if colour_type == 6 else 2
    sample_bytes = bit_depth // 8
    bytes_per_pixel = channels * sample_bytes
    row_bytes = width * bytes_per_pixel
    expected = height * (row_bytes + 1)
    if expected > MAX_DECODED_ALPHA_BYTES:
        return ImageProbe(
            format="png",
            width=width,
            height=height,
            bit_depth=bit_depth,
            colour_model=colour_model,
            has_alpha_channel=True,
            alpha_usage="unknown",
            probe_complete=False,
            valid=True,
            warnings=("Decoded PNG alpha exceeds the bounded 256 MiB limit",),
        )

    try:
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(b"".join(idat), expected + 1)
        if len(decoded) > expected or decompressor.unconsumed_tail:
            return _invalid("png", "Decoded PNG alpha exceeds the declared canvas")
        decoded += decompressor.flush()
    except zlib.error as error:
        return _invalid("png", f"PNG alpha decompression failed: {error}")
    if (
        not decompressor.eof
        or decompressor.unused_data
        or len(decoded) != expected
    ):
        return _invalid("png", "PNG scanline data does not match the declared canvas")

    previous = bytearray(row_bytes)
    cursor = 0
    maximum = 65_535 if bit_depth == 16 else 255
    alpha_offset = (3 if colour_type == 6 else 1) * sample_bytes
    visible = False
    non_opaque = False
    opaque = False
    for _ in range(height):
        filter_type = decoded[cursor]
        cursor += 1
        current = bytearray(row_bytes)
        for index in range(row_bytes):
            encoded = decoded[cursor + index]
            left = current[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            above = previous[index]
            upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
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
                return _invalid("png", f"PNG scanline filter {filter_type} is invalid")
            current[index] = value & 0xFF
        cursor += row_bytes
        for pixel in range(width):
            alpha_index = pixel * bytes_per_pixel + alpha_offset
            if bit_depth == 16:
                alpha = (current[alpha_index] << 8) | current[alpha_index + 1]
            else:
                alpha = current[alpha_index]
            visible |= alpha > 0
            non_opaque |= alpha < maximum
            opaque |= alpha == maximum
        previous = current

    if not visible:
        alpha_usage = "fully-transparent"
    elif non_opaque:
        alpha_usage = "meaningful"
    elif opaque:
        alpha_usage = "opaque-channel"
    else:
        alpha_usage = "unknown"
    return ImageProbe(
        format="png",
        width=width,
        height=height,
        bit_depth=bit_depth,
        colour_model=colour_model,
        has_alpha_channel=True,
        alpha_usage=alpha_usage,
        probe_complete=True,
        valid=True,
        warnings=(),
    )


def _jpeg_probe(data: bytes) -> ImageProbe:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return _invalid("jpeg", "JPEG signature is invalid")
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            break
        length = struct.unpack_from(">H", data, offset)[0]
        if length < 2 or offset + length > len(data):
            return _invalid("jpeg", "JPEG segment exceeds file bounds")
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        } and length >= 8:
            bit_depth = data[offset + 2]
            height = struct.unpack_from(">H", data, offset + 3)[0]
            width = struct.unpack_from(">H", data, offset + 5)[0]
            return ImageProbe(
                format="jpeg",
                width=width,
                height=height,
                bit_depth=bit_depth,
                colour_model="jpeg",
                has_alpha_channel=False,
                alpha_usage="none",
                probe_complete=True,
                valid=True,
                warnings=(),
            )
        offset += length
    return _invalid("jpeg", "JPEG dimensions could not be located")


def _read_uint24_le(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8) | (data[offset + 2] << 16)


def _webp_probe(data: bytes) -> ImageProbe:
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return _invalid("webp", "WebP signature is invalid")
    declared_size = struct.unpack_from("<I", data, 4)[0] + 8
    if declared_size > len(data):
        return _invalid("webp", "WebP RIFF size exceeds file bounds")
    offset = 12
    width = height = None
    has_alpha = False
    while offset + 8 <= declared_size:
        kind = data[offset : offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        start = offset + 8
        end = start + size
        if end > declared_size:
            return _invalid("webp", "WebP chunk exceeds file bounds")
        if kind == b"VP8X" and size >= 10:
            flags = data[start]
            has_alpha |= bool(flags & 0x10)
            width = _read_uint24_le(data, start + 4) + 1
            height = _read_uint24_le(data, start + 7) + 1
        elif kind == b"ALPH":
            has_alpha = True
        elif kind == b"VP8L" and size >= 5 and data[start] == 0x2F:
            bits = struct.unpack_from("<I", data, start + 1)[0]
            width = width or (bits & 0x3FFF) + 1
            height = height or ((bits >> 14) & 0x3FFF) + 1
            has_alpha |= bool((bits >> 28) & 1)
        elif (
            kind == b"VP8 "
            and size >= 10
            and data[start + 3 : start + 6] == b"\x9d\x01\x2a"
        ):
            width = width or (struct.unpack_from("<H", data, start + 6)[0] & 0x3FFF)
            height = height or (struct.unpack_from("<H", data, start + 8)[0] & 0x3FFF)
        offset = end + (size % 2)
    if not width or not height:
        return _invalid("webp", "WebP dimensions could not be located")
    warnings = (
        ("WebP alpha is declared; decoded pixels are required for final alpha proof",)
        if has_alpha
        else ()
    )
    return ImageProbe(
        format="webp",
        width=width,
        height=height,
        bit_depth=None,
        colour_model="webp",
        has_alpha_channel=has_alpha,
        alpha_usage="unknown" if has_alpha else "none",
        probe_complete=not has_alpha,
        valid=True,
        warnings=warnings,
    )


def _gif_probe(data: bytes) -> ImageProbe:
    if len(data) < 13 or data[:6] not in {b"GIF87a", b"GIF89a"}:
        return _invalid("gif", "GIF signature is invalid")
    transparent = False
    for offset in range(13, max(13, len(data) - 6)):
        if (
            data[offset : offset + 3] == b"\x21\xf9\x04"
            and data[offset + 3] & 0x01
        ):
            transparent = True
            break
    return ImageProbe(
        format="gif",
        width=struct.unpack_from("<H", data, 6)[0],
        height=struct.unpack_from("<H", data, 8)[0],
        bit_depth=(data[10] & 0x07) + 1,
        colour_model="indexed",
        has_alpha_channel=transparent,
        alpha_usage="unknown" if transparent else "none",
        probe_complete=not transparent,
        valid=True,
        warnings=(
            ("GIF transparency is declared; decode all frames before promotion",)
            if transparent
            else ()
        ),
    )


def _bmp_probe(data: bytes) -> ImageProbe:
    if len(data) < 30 or data[:2] != b"BM":
        return _invalid("bmp", "BMP signature is invalid")
    width = abs(struct.unpack_from("<i", data, 18)[0])
    height = abs(struct.unpack_from("<i", data, 22)[0])
    bit_depth = struct.unpack_from("<H", data, 28)[0]
    has_alpha = bit_depth == 32
    return ImageProbe(
        format="bmp",
        width=width,
        height=height,
        bit_depth=bit_depth,
        colour_model="bmp",
        has_alpha_channel=has_alpha,
        alpha_usage="unknown" if has_alpha else "none",
        probe_complete=not has_alpha,
        valid=True,
        warnings=(
            ("32-bit BMP alpha requires decoded-pixel verification",)
            if has_alpha
            else ()
        ),
    )


def _tga_probe(data: bytes) -> ImageProbe:
    if len(data) < 18 or data[2] not in {1, 2, 3, 9, 10, 11}:
        return _invalid("tga", "TGA header is invalid")
    width = struct.unpack_from("<H", data, 12)[0]
    height = struct.unpack_from("<H", data, 14)[0]
    if not width or not height:
        return _invalid("tga", "TGA dimensions are invalid")
    bit_depth = data[16]
    alpha_bits = data[17] & 0x0F
    has_alpha = alpha_bits > 0 or bit_depth == 32
    return ImageProbe(
        format="tga",
        width=width,
        height=height,
        bit_depth=bit_depth,
        colour_model="tga",
        has_alpha_channel=has_alpha,
        alpha_usage="unknown" if has_alpha else "none",
        probe_complete=not has_alpha,
        valid=True,
        warnings=(
            ("TGA alpha requires decoded-pixel verification",)
            if has_alpha
            else ()
        ),
    )


def _svg_probe(data: bytes) -> ImageProbe:
    try:
        content = data[: 256 * 1024].decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return _invalid("svg", "SVG is not valid UTF-8")
    if not re.search(r"<svg\b", content, re.IGNORECASE):
        return _invalid("svg", "SVG root element is missing")

    def numeric(value: str | None) -> float | None:
        if not value:
            return None
        try:
            result = float(value)
        except ValueError:
            return None
        return result if result > 0 else None

    width = numeric(
        (re.search(r"<svg\b[^>]*\bwidth=[\"']\s*([0-9.]+)", content, re.I) or [None, None])[1]
    )
    height = numeric(
        (re.search(r"<svg\b[^>]*\bheight=[\"']\s*([0-9.]+)", content, re.I) or [None, None])[1]
    )
    view_box = re.search(
        r"<svg\b[^>]*\bviewBox=[\"']\s*[-.0-9]+[ ,]+[-.0-9]+[ ,]+([0-9.]+)[ ,]+([0-9.]+)",
        content,
        re.I,
    )
    if view_box:
        width = width or numeric(view_box.group(1))
        height = height or numeric(view_box.group(2))
    return ImageProbe(
        format="svg",
        width=width,
        height=height,
        bit_depth=None,
        colour_model="vector",
        has_alpha_channel=True,
        alpha_usage="unknown",
        probe_complete=False,
        valid=True,
        warnings=("SVG transparency and filters require rendered-pixel QA",),
    )


def probe_image_bytes(data: bytes, extension: str) -> ImageProbe:
    extension = extension.lower()
    if extension == ".png":
        return _png_probe(data)
    if extension in {".jpg", ".jpeg"}:
        return _jpeg_probe(data)
    if extension == ".webp":
        return _webp_probe(data)
    if extension == ".gif":
        return _gif_probe(data)
    if extension == ".bmp":
        return _bmp_probe(data)
    if extension == ".tga":
        return _tga_probe(data)
    if extension == ".svg":
        return _svg_probe(data)
    return _unknown(
        extension.removeprefix(".") or "unknown",
        f"{extension or 'unknown'} requires decoded runtime or media-toolchain verification",
    )

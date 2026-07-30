from __future__ import annotations

import math

from PIL import Image

from .models import SUPPORTED_RESOLUTIONS


_PROFILES = {
    (212, 104): (216, bytes([0x00, 0xD4, 0x68, 0x00, 0x00])),
    (250, 122): (256, bytes([0x00, 0xFA, 0x7A, 0x00, 0x00])),
    (296, 128): (296, bytes([0x00, 0x28, 0x80, 0x00, 0x00])),
    (400, 300): (400, b""),
}


def _bit_for_pixel(pixel: int, black_is_one: bool) -> int:
    is_black = pixel <= 0
    return int(is_black if black_is_one else not is_black)


def pack_monochrome(image: Image.Image, *, black_is_one: bool = True) -> bytes:
    source = image.convert("1")
    width, height = source.size
    output = bytearray(math.ceil(width * height / 8))
    bit_index = 0
    for y in range(height):
        for x in range(width):
            bit = _bit_for_pixel(source.getpixel((x, y)), black_is_one)
            if bit:
                output[bit_index // 8] |= 1 << (7 - bit_index % 8)
            bit_index += 1
    return bytes(output)


def build_image_payload(image: Image.Image, *, black_is_one: bool = True) -> bytes:
    source = image.convert("1")
    if source.size not in _PROFILES:
        raise ValueError(f"unsupported image size: {source.size}")
    storage_width, header = _PROFILES[source.size]
    width, height = source.size
    row_bytes = storage_width // 8
    output = bytearray(header)
    for y in range(height):
        row = bytearray(row_bytes)
        for x in range(storage_width):
            if x < width:
                pixel = source.getpixel((x, y))
            else:
                pixel = 255
            if _bit_for_pixel(pixel, black_is_one):
                row[x // 8] |= 1 << (7 - x % 8)
        output.extend(row)
    return bytes(output)


def _chunk_packets(payload: bytes) -> list[bytes]:
    packets = []
    for offset in range(0, len(payload), 256):
        for command, inner_offset in ((0x60, offset), (0x61, offset + 128)):
            chunk = payload[inner_offset : inner_offset + 128]
            if len(chunk) < 128:
                chunk += b"\xFF" * (128 - len(chunk))
            packets.append(bytes([command]) + chunk)
    return packets


def build_bw_packets(image: Image.Image, image_index: int = 0) -> list[bytes]:
    if not 0 <= image_index <= 6:
        raise ValueError("image_index must be between 0 and 6")
    packets = _chunk_packets(build_image_payload(image, black_is_one=True))
    packets.append(bytes([0x62, image_index]) + b"\xFF" * 127)
    return packets


def build_bwr_packets(black: Image.Image, red: Image.Image) -> list[bytes]:
    if black.size != red.size or black.size not in SUPPORTED_RESOLUTIONS:
        raise ValueError("black and red planes must have the same supported size")
    packets = [bytes([0x5E])]
    packets.extend(_chunk_packets(build_image_payload(black, black_is_one=True)))
    packets.append(bytes([0x5F]))
    packets.extend(_chunk_packets(build_image_payload(red, black_is_one=False)))
    packets.append(bytes([0x62]) + b"\xFF" * 128)
    return packets

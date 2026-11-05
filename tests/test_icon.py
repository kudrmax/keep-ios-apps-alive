import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from installer.launcher import AppIcon


def write_png(path: Path, size: int, rgb: tuple) -> None:
    """An opaque square, as an iPhone app icon is."""
    row = b"\0" + bytes(rgb) * size
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(row * size)) + chunk(b"IEND", b""))


def alpha_at(path: Path, x: int, y: int) -> int:
    """The alpha of one pixel of an 8-bit PNG without interlacing, as sips and iconutil write them; RGB is opaque."""
    data = path.read_bytes()
    width, height, depth, color = struct.unpack(">IIBB", data[16:26])
    if color == 2:
        return 255
    assert (depth, color) == (8, 6), (depth, color)
    raw, at = b"", 8
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        if kind == b"IDAT":
            raw += data[at + 8:at + 8 + length]
        at += 12 + length
    pixels, stride, previous = zlib.decompress(raw), width * 4, bytearray(width * 4)
    for line in range(y + 1):
        kind, row = pixels[line * (stride + 1)], bytearray(pixels[line * (stride + 1) + 1:(line + 1) * (stride + 1)])
        for i in range(stride):
            left, up = row[i - 4] if i >= 4 else 0, previous[i]
            corner = previous[i - 4] if i >= 4 else 0
            if kind == 1: row[i] = (row[i] + left) & 0xFF
            elif kind == 2: row[i] = (row[i] + up) & 0xFF
            elif kind == 3: row[i] = (row[i] + (left + up) // 2) & 0xFF
            elif kind == 4:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                row[i] = (row[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 0xFF
        previous = row
    return previous[x * 4 + 3]


class AppIconTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        clone = self.root / "clone"
        icons = clone / "App/Assets.xcassets/AppIcon.appiconset"
        icons.mkdir(parents=True)
        write_png(icons / "icon.png", 1024, (90, 60, 240))
        subprocess.run(["git", "init", "-q", str(clone)], check=True)
        subprocess.run(["git", "-C", str(clone), "add", "."], check=True)
        self.icon = AppIcon(clone)

    def tearDown(self):
        subprocess.run(["trash", str(self.root)])

    def test_a_square_iphone_icon_becomes_a_mac_plate_with_rounded_corners_and_margins(self):
        target = self.root / "AppIcon.icns"
        self.assertTrue(self.icon.write(target))
        subprocess.run(["iconutil", "-c", "iconset", str(target), "-o", str(self.root / "out.iconset")], check=True)
        largest = self.root / "out.iconset/icon_512x512@2x.png"
        self.assertEqual(alpha_at(largest, 512, 512), 255)
        self.assertEqual(alpha_at(largest, 512, 60), 0, "a margin above the plate")
        self.assertEqual(alpha_at(largest, 110, 110), 0, "a rounded corner, not a square one")
        self.assertEqual(alpha_at(largest, 512, 105), 255, "the plate's top edge")


if __name__ == "__main__":
    unittest.main()

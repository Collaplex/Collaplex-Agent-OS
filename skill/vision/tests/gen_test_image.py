#!/usr/bin/env python3
"""造两张测试用的图 (纯标准库, 不依赖 PIL): 一张全白(试"图上没内容")、一张小图(当正常样本).

用法: .venv/bin/python skill/vision/tests/gen_test_image.py
出到 skill/vision/tests/样本/ —— 只在测试时用, 不进 git (见 .gitignore)。
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
样本 = HERE / "样本"


def 写png(路径: Path, 宽: int, 高: int, 像素: bytes) -> None:
    """把一行行像素写成一个 PNG."""

    def 块(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF
        )

    行字节 = 宽 * 3
    原数据 = b"".join(
        b"\x00" + 像素[第行 * 行字节:(第行 + 1) * 行字节] for 第行 in range(高)
    )
    ihdr = struct.pack(">IIBBBBB", 宽, 高, 8, 2, 0, 0, 0)   # 8bit / 真彩
    路径.write_bytes(
        b"\x89PNG\r\n\x1a\n" + 块(b"IHDR", ihdr)
        + 块(b"IDAT", zlib.compress(原数据)) + 块(b"IEND", b"")
    )


def main() -> int:
    样本.mkdir(parents=True, exist_ok=True)

    白 = bytes([255, 255, 255]) * 200 * 200          # 200x200 全白
    写png(样本 / "全白.png", 200, 200, 白)

    红 = bytes([220, 40, 40]) * 64 * 64              # 64x64 纯色
    写png(样本 / "纯色.png", 64, 64, 红)

    print(f"造好了: {样本}")
    for 件 in sorted(样本.glob("*.png")):
        print(f"  {件.name}  {件.stat().st_size} 字节")
    return 0


if __name__ == "__main__":
    sys.exit(main())

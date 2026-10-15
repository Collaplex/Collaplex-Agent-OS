#!/usr/bin/env python3
"""看图 skill 的纯逻辑自检 —— 不花模型钱、不出网, 只验那些"程序该拦住"的地方.

用法: .venv/bin/python skill/vision/tests/看图_check.py

覆盖:
    A 查图三拦: 不在 / 后缀不认 / 超上限 (都要抛 ValueError 且是人话)
    B 单轮闸: 新轮从 1 起数 / 到上限抛 / peek 不改数
    C 端点拼装: .env 有凭据就出云端端点; 缺一个就说明缺哪个
    D 1x1 小图 (status --真读 用的那张) 是合法 PNG
"""

from __future__ import annotations

import copy
import json
import os
import struct
import sys
import tempfile
import zlib
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent            # skill/vision/tests
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import vision_core as core  # noqa: E402
from see import 云端端点, 本地端点  # noqa: E402

过 = 0
错: list[str] = []


def 要(条件: bool, 说明: str) -> None:
    global 过
    if 条件:
        过 += 1
    else:
        错.append(说明)


def 抛人话(做: Any, 含: str, 说明: str) -> None:
    """跑一下, 期望抛 ValueError 且里面含某句话."""
    try:
        做()
    except ValueError as 错信:
        if 含 in str(错信):
            要(True, "")
        else:
            错.append(f"{说明}: 抛了但不是那句话 -> {错信}")
    except Exception as 别的:  # noqa: BLE001
        错.append(f"{说明}: 抛的不是 ValueError -> {type(别的).__name__}: {别的}")
    else:
        错.append(f"{说明}: 竟然没抛")


def main() -> int:
    config = core.load_config()
    tmp = Path(tempfile.mkdtemp(prefix="vision-check-"))

    # ── A 查图三拦 ───────────────────────────────────────────
    抛人话(lambda: core.check_image(str(tmp / "没有这张图.png"), config), "图片不在", "A1 图不在")
    不是图 = tmp / "笔记.txt"
    不是图.write_text("x", encoding="utf-8")
    抛人话(lambda: core.check_image(str(不是图), config), "后缀不认", "A2 后缀不认")
    大图 = tmp / "大图.png"
    大图.write_bytes(b"\x89PNG" + b"\x00" * (9 * 1024 * 1024))
    抛人话(lambda: core.check_image(str(大图), config), "太大", "A3 超上限")

    好图 = tmp / "好图.png"
    好图.write_bytes(core.tiny_png())
    路径, 字节, mime = core.check_image(str(好图), config)
    要(路径 == 好图 and len(字节) > 0 and mime == "image/png", f"A4 正常图应过 -> {路径} / {mime}")

    # ── B 单轮闸 ─────────────────────────────────────────────
    闸配置 = copy.deepcopy(config)
    闸配置["闸"] = {"max_per_round": 2, "round_gap_seconds": 1800,
                    "state": str(tmp / "budget.json")}
    甲 = core.budget(闸配置)
    要(甲["已用"] == 1 and 甲["剩"] == 1, f"B1 第一次应记 1 次 -> {甲}")
    乙 = core.budget(闸配置)
    要(乙["已用"] == 2 and 乙["剩"] == 0, f"B2 第二次应记 2 次 -> {乙}")
    看 = core.budget(闸配置, peek=True)
    要(看["已用"] == 2, f"B3 peek 不该改数 -> {看}")
    try:
        core.budget(闸配置)
    except RuntimeError as 错信:
        要("上限" in str(错信), f"B4 到顶那句该提上限 -> {错信}")
    else:
        错.append("B4 到顶了竟然没抛")

    # 停手超过间隔 -> 自动开新一轮
    甲2 = json.loads((tmp / "budget.json").read_text(encoding="utf-8"))
    甲2["last"] = 0
    (tmp / "budget.json").write_text(json.dumps(甲2), encoding="utf-8")
    丙 = core.budget(闸配置)
    要(丙["已用"] == 1 and 丙["轮次"] >= 2, f"B5 隔久了该开新一轮且从 1 数 -> {丙}")

    # ── C 端点拼装 ───────────────────────────────────────────
    保存 = {k: os.environ.get(k) for k in ("OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_API_KEY")}
    os.environ.update({"OPENAI_BASE_URL": "https://example.invalid/v1",
                       "OPENAI_MODEL": "某模型", "OPENAI_API_KEY": "某钥匙"})
    端, 缺 = 云端端点(config)
    要(端 is not None and 缺 == "" and 端["模型"] == "某模型", f"C1 凭据齐该出端点 -> {端} / {缺}")
    # 缺一个: 不要让真 .env 顶上 —— 把来源指到不存在的路径, 并且只给 BASE_URL
    os.environ.pop("OPENAI_MODEL", None)
    缺配置 = copy.deepcopy(config)
    缺配置["主路"] = {"env前缀": "OPENAI", "env来源": ["/不存在/dotenv"]}
    端2, 缺2 = 云端端点(缺配置)
    要(端2 is None and "OPENAI_MODEL" in 缺2, f"C2 缺一个要说缺哪个 -> {端2} / {缺2}")
    for k, v in 保存.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    端3, 缺3 = 本地端点(config)
    要(端3 is not None and 端3["路"] == "本地", f"C3 本地端点该总能拼出来 -> {端3} / {缺3}")

    # ── D 1x1 小图是合法 PNG ─────────────────────────────────
    小 = core.tiny_png()
    要(小[:8] == b"\x89PNG\r\n\x1a\n", "D1 小图该有 PNG 头")
    宽, 高 = struct.unpack(">II", 小[16:24])
    要((宽, 高) == (1, 1), f"D2 小图该是 1x1 -> {宽}x{高}")
    要(len(小) > 50 and 小[-8:-4] == b"IEND"
       and int.from_bytes(小[-4:], "big") == zlib.crc32(b"IEND"), "D3 小图该收尾完整(IEND + 尾 CRC)")

    print(f"看图 skill 纯逻辑自检: 过 {过} / 错 {len(错)}")
    for 一条 in 错:
        print(f"  ✗ {一条}")
    print("✓ 全过" if not 错 else "✗ 有不过的")
    return 0 if not 错 else 1


if __name__ == "__main__":
    sys.exit(main())

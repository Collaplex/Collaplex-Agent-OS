#!/usr/bin/env python3
"""看图: 把一张本地图片在**那一次请求**里交给视觉模型, 拿回文字.

用法:
    .venv/bin/python skill/vision/main.py 看图 "<图片路径>" [--问 "问题"] [--去 自动|云端|本地] [--json]

定调 (不是参数):
    ① 图只在这一次请求里出现 —— base64 进请求体, 回来文字, 图就散了. 不留库、不进会话历史.
    ② 一次一张 ("查看"就是一眼). 要看好几张就发几条命令.
    ③ 主路云端 → 不成自动兜底本地; 两条都不通就照实说, 绝不编图里有什么.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent      # skill/vision/scripts
sys.path.insert(0, str(HERE))               # 让 core 能被 import (单独跑这个文件也行)

import vision_core as core  # noqa: E402   (要先插 sys.path; 不叫 core 是怕跟 skill_search/scripts/core.py 撞名)

默认问句 = "这张图里有什么? 把图上的字照抄出来, 再说清版式(哪块是什么)。"


def 云端端点(config: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """从 .env 拼云端视觉端点 (主路). 缺东西就回 (None, 缺什么)."""
    前缀 = str(core.as_dict(config.get("主路")).get("env前缀", "OPENAI"))
    来源 = core.env_sources(config, "主路")
    端点 = core.read_env(f"{前缀}_BASE_URL", 来源)
    模型 = core.read_env(f"{前缀}_MODEL", 来源)
    凭据 = core.read_env(f"{前缀}_API_KEY", 来源)
    if not 端点:
        return None, f"缺 {前缀}_BASE_URL"
    if not 模型:
        return None, f"缺 {前缀}_MODEL"
    if not 凭据:
        return None, f"缺 {前缀}_API_KEY"
    return {"路": "云端", "base_url": 端点, "api_key": 凭据, "模型": 模型}, ""


def 本地端点(config: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """拼本地视觉端点 (兜底). 允许用环境变量覆盖 (跟 本地兜底.sh 一套路子)."""
    节 = core.as_dict(config.get("兜底"))
    覆盖 = core.as_dict(节.get("env覆盖"))
    端点 = str(节.get("base_url") or "")
    模型 = str(节.get("模型") or "")
    覆盖端点名 = str(覆盖.get("base_url") or "")
    覆盖模型名 = str(覆盖.get("模型") or "")
    if 覆盖端点名:
        端点 = core.read_env(覆盖端点名, []) or 端点
    if 覆盖模型名:
        模型 = core.read_env(覆盖模型名, []) or 模型
    if not 端点:
        return None, "配置里没写兜底端点 (resources/vision.json 的 兜底.base_url)"
    if not 模型:
        return None, "配置里没写兜底模型名"
    return {"路": "本地", "base_url": 端点, "api_key": str(节.get("api_key") or "local"), "模型": 模型}, ""


def 路们(config: dict[str, Any], 去: str) -> list[tuple[dict[str, Any] | None, str]]:
    """按 --去 决定试哪几条 (自动 = 云端 → 本地)."""
    云端 = 云端端点(config)
    本地 = 本地端点(config)
    if 去 == "云端":
        return [云端]
    if 去 == "本地":
        return [本地]
    return [云端, 本地]


def 落盘(config: dict[str, Any], 记录: dict[str, Any], 问句: str, 结果: dict[str, Any]) -> Path:
    """落一行账 + 一份产出. 只落**文字与账**, 图不动."""
    节 = core.as_dict(config.get("落盘"))
    账 = core.SKILL_DIR / str(节.get("账") or "logs/vision/调用.jsonl")
    账.parent.mkdir(parents=True, exist_ok=True)
    with 账.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(记录, ensure_ascii=False) + "\n")
    目录 = core.SKILL_DIR / str(节.get("产出目录") or "logs/vision")
    目录.mkdir(parents=True, exist_ok=True)
    戳 = datetime.now().strftime("%Y%m%d-%H%M%S")
    产出 = 目录 / f"{戳}-看图.md"
    产出.write_text(
        "\n".join([
            f"# 看图 {戳}",
            "",
            f"- 图: `{记录.get('图')}` ({记录.get('图MB')}MB)",
            f"- 问: {问句}",
            f"- 谁读的: {记录.get('路')} / {记录.get('模型')} ({记录.get('耗时秒')}s)",
            "",
            "## 看到的",
            "",
            str(结果.get("文字") or "").strip(),
            "",
        ]),
        encoding="utf-8",
    )
    return 产出


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="看图", description="把一张本地图片在那一次请求里交给视觉模型, 拿回文字 (主路云端 / 兜底本地)"
    )
    parser.add_argument("图片", help="本地图片路径 (search 的 shot_path, 或任何图)")
    parser.add_argument("--问", dest="问句", default=默认问句, help="问它什么 (默认: 这图里有什么)")
    parser.add_argument("--去", choices=("自动", "云端", "本地"), default="自动",
                        help="走哪条: 自动=云端不成再本地 (默认)")
    parser.add_argument("--json", action="store_true", help="出 JSON (给程序读)")
    args = parser.parse_args()

    config = core.load_config()

    # ① 查图 —— 不在 / 后缀不认 / 超上限, 这里就拦住 (不白花一次模型调用)
    try:
        路径, 字节, mime = core.check_image(str(args.图片), config)
    except ValueError as 错:
        print(f"[看图] {错}")
        return 1

    # ② 闸 —— 单轮次数
    try:
        余额 = core.budget(config)
    except RuntimeError as 错:
        print(f"[看图] {错}")
        return 2

    # ③ 查看
    max_tokens, 温度, 超时 = core.call_config_of(config)
    提示词 = core.system_prompt_of(config)
    图MB = round(len(字节) / 1024 / 1024, 2)
    试过: list[str] = []
    选中: dict[str, Any] | None = None
    结果: dict[str, Any] = {}
    for 端, 缺 in 路们(config, args.去):
        if 端 is None:
            试过.append(f"{缺} (这条跳过)")
            continue
        结果 = core.call_vision(
            base_url=str(端["base_url"]), api_key=str(端["api_key"]), model=str(端["模型"]),
            raw=字节, mime=mime, question=str(args.问句), system_prompt=提示词,
            max_tokens=max_tokens, temperature=温度, timeout=超时,
        )
        if 结果.get("成功"):
            选中 = 端
            break
        试过.append(f"{端['路']}: {结果.get('错误')}")

    if 选中 is None or not 结果.get("成功"):
        记录 = {
            "时间": datetime.now().isoformat(timespec="seconds"), "图": str(路径),
            "图MB": 图MB, "问": str(args.问句), "路": "", "模型": "", "耗时秒": 0.0,
            "成": False, "试过": 试过, "闸": 余额,
        }
        try:
            落盘(config, 记录, str(args.问句), {})
        except OSError:
            pass
        if args.json:
            print(json.dumps(记录, ensure_ascii=False, indent=2))
        else:
            print("[看图] 两条路都不通 —— 图里有什么, 我不知道 (绝不编):")
            for 行 in 试过:
                print(f"  - {行}")
        return 1

    记录 = {
        "时间": datetime.now().isoformat(timespec="seconds"), "图": str(路径), "图MB": 图MB,
        "问": str(args.问句), "路": str(选中["路"]), "模型": str(选中["模型"]),
        "耗时秒": float(结果.get("耗时秒") or 0.0), "成": True,
        "用量": core.as_dict(结果.get("用量")), "闸": 余额,
    }
    产出 = 落盘(config, 记录, str(args.问句), 结果)

    if args.json:
        print(json.dumps({"ok": True, "路": 记录["路"], "模型": 记录["模型"],
                          "耗时秒": 记录["耗时秒"], "图": 记录["图"], "问": 记录["问"],
                          "文字": str(结果.get("文字") or ""), "产出": str(产出),
                          "闸": 余额}, ensure_ascii=False, indent=2))
    else:
        剩 = 余额.get("剩", "?")
        print(f"[看图] {记录['路']} · {记录['模型']} · {记录['耗时秒']}s · 本轮还剩 {剩} 次")
        print(str(结果.get("文字") or "").strip())
    _ = time.time()
    return 0


if __name__ == "__main__":
    sys.exit(main())

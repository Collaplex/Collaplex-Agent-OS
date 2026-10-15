#!/usr/bin/env python3
"""状态: 看两条路各通不通、凭据在不在 (只报在不在, 不打印值) + 本轮还剩几次.

用法:
    .venv/bin/python skill/vision/main.py 状态 [--json] [--真读]

★ --真读 会拿一张 1x1 的图**真读一次**兜底那条 —— 这是唯一能证明
  "本地这支带没带 mmproj" 的判据: 不带的话它必回 `image input is not supported`.
  不带 --真读 就只看端点答不答话 (那证明不了它能读图).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import vision_core as core  # noqa: E402   (不叫 core 是怕跟 skill_search/scripts/core.py 撞名)
from see import 云端端点, 本地端点  # noqa: E402


def 端点通不通(端: dict[str, Any], 超时: float = 5.0) -> tuple[bool, str]:
    """打一下 /models —— 只证明'答话', 不证明'能读图'."""
    打开 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    请求 = urllib.request.Request(
        str(端["base_url"]).rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {端.get('api_key') or 'local'}"},
    )
    try:
        with 打开.open(请求, timeout=超时) as 回:
            return 200 <= 回.status < 300, f"HTTP {回.status}"
    except urllib.error.HTTPError as 错:
        return False, f"HTTP {错.code}"
    except Exception as 错:  # noqa: BLE001 - 网络侧什么都可能
        return False, f"{type(错).__name__}"


def 真读一次(端: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """拿 1x1 的图真读一次 —— 这条才证明'能不能读图'."""
    max_tokens, 温度, 超时 = core.call_config_of(config)
    结果 = core.call_vision(
        base_url=str(端["base_url"]), api_key=str(端.get("api_key") or "local"),
        model=str(端["模型"]), raw=core.tiny_png(), mime="image/png",
        question="这张图是什么颜色? 一个字答。", system_prompt=core.system_prompt_of(config),
        max_tokens=max_tokens, temperature=温度, timeout=min(超时, 60.0),
    )
    return 结果


def main() -> int:
    parser = argparse.ArgumentParser(prog="状态", description="看两条路通不通 + 能不能真读图")
    parser.add_argument("--json", action="store_true", help="出 JSON")
    parser.add_argument("--真读", dest="真读", action="store_true",
                        help="拿一张 1x1 的图真读一次兜底(能证明 mmproj 带没带)")
    args = parser.parse_args()

    config = core.load_config()
    报: dict[str, Any] = {"时间": datetime.now().isoformat(timespec="seconds"), "路": {}}

    for 名, 取 in (("主路云端", 云端端点), ("兜底本地", 本地端点)):
        端, 缺 = 取(config)
        if 端 is None:
            报["路"][名] = {"可用": False, "说明": 缺}
            continue
        # 凭据只报"在不在", 值绝不打印
        有凭据 = bool(str(端.get("api_key") or "")) and str(端.get("api_key")) != "local"
        通, 详 = 端点通不通(端)
        条: dict[str, Any] = {
            "可用": 通, "端点": str(端["base_url"]), "模型": str(端["模型"]),
            "凭据": "有" if 有凭据 else ("本地不需要" if 名 == "兜底本地" else "无"),
            "端点答话": 详,
        }
        if args.真读 and 通:
            读 = 真读一次(端, config)
            条["能不能真读图"] = "能" if 读.get("成功") else f"不能 ({读.get('错误')})"
        报["路"][名] = 条

    报["本轮闸"] = core.budget(config, peek=True)

    if args.json:
        print(json.dumps(报, ensure_ascii=False, indent=2))
        return 0

    print("看图的两条路:")
    for 名, 条 in core.as_dict(报["路"]).items():
        条目 = core.as_dict(条)
        记号 = "✓" if 条目.get("可用") else "×"
        print(f"  {记号} {名}: {条目.get('端点') or '—'} / {条目.get('模型') or '—'} "
              f"/ 凭据 {条目.get('凭据')} / {条目.get('说明') or 条目.get('端点答话')}")
        if "能不能真读图" in 条目:
            print(f"      真读一次: {条目['能不能真读图']}")
    闸 = core.as_dict(报["本轮闸"])
    print(f"  本轮看图: 已用 {闸.get('已用')} / 上限 {闸.get('上限')} (剩 {闸.get('剩')})")
    print("\n★ 兜底那条要能真读图, 起本地模型时必须带 --mmproj (start_models.sh)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

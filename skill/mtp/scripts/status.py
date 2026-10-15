#!/usr/bin/env python3
"""看交叉验证的状态: 开关 / 用哪几家 / 今天花了多少.

钱袋子沿用 outsource (凭据 / 预算 / 记账都在那边), 所以这里也把它一起报出来.
用法: .venv/bin/python skill/mtp/main.py status [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent          # scripts
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent.parent / "skill" / "outsource" / "scripts"))

from budget import as_dict, as_list, env_sources_of, ledger_path_of, read_config, read_env, today_totals  # noqa: E402
from panel import read_mtp_config  # noqa: E402


def house_brief(house: dict[str, Any]) -> str:
    """一家外援的凭据在不在 (只报在不在和长度, 不打印值)."""
    prefix = str(house.get("env前缀", ""))
    key = read_env(f"{prefix}_API_KEY", env_sources_of(house))
    model = read_env(f"{prefix}_MODEL", env_sources_of(house)) or str(house.get("模型", ""))
    return f"{'✓' if key else '✗'} {model}"


def main() -> int:
    parser = argparse.ArgumentParser(description="交叉验证状态")
    parser.add_argument("--json", action="store_true", help="只吐 JSON")
    args = parser.parse_args()

    try:
        money_config = read_config()
        mtp_config = read_mtp_config()
    except (FileNotFoundError, ValueError) as exc:
        print(f"读配置失败: {exc}")
        return 1

    ledger = ledger_path_of(money_config)
    spent, count = today_totals(ledger)
    names = [str(item) for item in as_list(mtp_config.get("家"))]
    houses = as_dict(money_config.get("家"))
    report: dict[str, Any] = {
        "开关": mtp_config.get("开关") is True,
        "用哪几家": names,
        "带本地": mtp_config.get("带本地") is True,
        "今天已花_元": spent,
        "今天次数": count,
        "记账文件": str(ledger),
        "各家": {name: house_brief(as_dict(houses.get(name))) for name in names},
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("交叉验证状态")
    print(f"  开关      {'开' if report['开关'] else '关'}")
    print(f"  用哪几家  {' · '.join(names) if names else '(没配)'}")
    print(f"  带本地    {'是(会慢 30~150 秒)' if report['带本地'] else '否'}")
    print(f"  今天      已花 {spent:.4f} 元 / {count} 次  (跟外援共用一个钱袋子)")
    homes = as_dict(report["各家"])
    for name in names:
        print(f"  {name:<9} {homes.get(name, '(没这家)')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

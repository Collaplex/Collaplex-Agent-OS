#!/usr/bin/env python3
"""看外援的状态: 开关 / 今天花了多少 / 各路凭据在不在.

只报「在不在」「多长」, 绝不打印凭据的值.
用法: .venv/bin/python skill/outsource/main.py status [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent          # scripts
sys.path.insert(0, str(HERE))

from budget import (  # noqa: E402
    as_dict,
    env_sources_of,
    ledger_path_of,
    read_config,
    read_env,
    today_totals,
)


def house_status(house: dict[str, Any]) -> dict[str, Any]:
    """一家外援的凭据在位情况 (只有键名和长度, 不取值)."""
    prefix = str(house.get("env前缀", ""))
    sources = env_sources_of(house)
    key = read_env(f"{prefix}_API_KEY", sources)
    base = read_env(f"{prefix}_BASE_URL", sources)
    model = read_env(f"{prefix}_MODEL", sources) or str(house.get("模型", ""))
    return {
        "凭据": "在" if key else "缺",
        "凭据长度": len(key),
        "端点": base or "(缺, 用配置里的)",
        "模型": model or "(缺)",
        "思考": house.get("思考", True),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="外援状态")
    parser.add_argument("--json", action="store_true", help="只吐 JSON")
    args = parser.parse_args()

    try:
        config = read_config()
    except (FileNotFoundError, ValueError) as exc:
        print(f"读配置失败: {exc}")
        return 1

    ledger = ledger_path_of(config)
    spent, count = today_totals(ledger)
    houses = as_dict(config.get("家"))
    report: dict[str, Any] = {
        "开关": config.get("开关") is True,
        "默认家": config.get("默认家", ""),
        "预算": as_dict(config.get("预算")),
        "今天已花_元": spent,
        "今天次数": count,
        "记账文件": str(ledger),
        "家": {name: house_status(as_dict(entry)) for name, entry in houses.items()},
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("外援状态")
    print(f"  开关      {'开' if report['开关'] else '关'}")
    print(f"  默认家    {report['默认家']}")
    budget = as_dict(report["预算"])
    print(f"  预算      单次 {budget.get('单次上限_元', '?')} 元 / "
          f"每日 {budget.get('每日上限_元', '?')} 元 / {budget.get('每日次数上限', '?')} 次")
    print(f"  今天      已花 {spent:.4f} 元 / {count} 次")
    print(f"  记账      {ledger}")
    homes = as_dict(report["家"])
    for name in sorted(homes):
        row = as_dict(homes[name])
        mark = "✓" if row.get("凭据") == "在" else "✗"
        think = "开" if row.get("思考") is True else "关"
        print(f"  {mark} {name:<9} 凭据{row.get('凭据')}({row.get('凭据长度')}字符) · "
              f"{row.get('模型')} · 思考{think}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""外援的预算与记账回归: 纯逻辑, 不联网, 不发请求.

跑法: .venv/bin/python skill/outsource/tests/test_budget.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

from budget import (  # noqa: E402
    as_dict,
    append_ledger,
    budget_check,
    cost_of,
    now_stamp,
    over_single_limit,
    read_env,
    today_totals,
)

passed = 0
failed = 0


def check(label: str, got: object, want: object) -> None:
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label}: 得到 {got!r}, 想要 {want!r}")


def temp_ledger() -> Path:
    """临时流水文件 (放系统临时目录, 不碰真账)."""
    folder = Path(tempfile.mkdtemp(prefix="outsource-test-"))
    return folder / "用量.jsonl"


def main() -> int:
    print("外援 · 预算与记账")
    ledger = temp_ledger()
    config: dict[str, Any] = {
        "开关": False,
        "预算": {"单次上限_元": 0.3, "每日上限_元": 0.5, "每日次数上限": 3},
        "家": {"deepseek": {"价目": {"输入_每百万": 1.5, "缓存命中_每百万": 0.05, "输出_每百万": 4.5}}},
    }

    print("[1] as_dict")
    check("是字典就原样", as_dict({"a": 1}), {"a": 1})
    check("不是字典给空", as_dict(["a"]), {})
    check("None 给空", as_dict(None), {})

    print("[2] read_env")
    envfile = ledger.parent / ".env"
    envfile.write_text('DEMO_API_KEY=abc123\nDEMO_BASE_URL="https://x/y"\n', encoding="utf-8")
    check("取到值", read_env("DEMO_API_KEY", [str(envfile)]), "abc123")
    check("去掉引号", read_env("DEMO_BASE_URL", [str(envfile)]), "https://x/y")
    check("没有就给空串", read_env("NOPE_KEY", [str(envfile)]), "")
    check("文件不在也不炸", read_env("DEMO_API_KEY", ["/nope/.env"]), "")

    print("[3] 记账与今日累计")
    check("空流水是 0", today_totals(ledger), (0.0, 0))
    append_ledger({"时间": now_stamp(), "家": "deepseek", "金额": 0.1}, ledger)
    append_ledger({"时间": now_stamp(), "家": "deepseek", "金额": 0.05}, ledger)
    ledger.open("a", encoding="utf-8").write(json.dumps({"时间": "2020-01-01T00:00:00", "金额": 9.9}, ensure_ascii=False) + "\n")
    ledger.open("a", encoding="utf-8").write("这不是 json\n")
    spent, count = today_totals(ledger)
    check("只算今天的两笔", (round(spent, 4), count), (0.15, 2))
    check("目录不存在也能建", append_ledger({"时间": now_stamp(), "金额": 0.0}, ledger.parent / "深" / "用量.jsonl").is_file(), True)

    print("[4] budget_check")
    check("开关关着不放行", budget_check(config, ledger)[0], False)
    check("--强制 跳开关", budget_check(config, ledger, force=True)[0], True)
    check("提示里有开关字样", "开关" in budget_check(config, ledger)[1], True)
    config["开关"] = True
    check("打开后放行", budget_check(config, ledger)[0], True)
    check("次数用满就拦", budget_check(config, ledger)[0], True)
    many = temp_ledger()
    for _ in range(3):
        append_ledger({"时间": now_stamp(), "金额": 0.0}, many)
    check("到次数上限拦下", budget_check(config, many)[0], False)
    skint = temp_ledger()
    append_ledger({"时间": now_stamp(), "金额": 0.6}, skint)
    check("到金额上限拦下", budget_check(config, skint)[0], False)
    check("--强制 也跳不了预算", budget_check(config, skint, force=True)[0], False)

    print("[5] cost_of")
    house = as_dict(config["家"]["deepseek"])
    check("1000 输入 + 500 输出", cost_of(house, {"prompt_tokens": 1000, "completion_tokens": 500}), 0.00375)
    check("缓存命中走便宜价", cost_of(house, {"prompt_tokens": 1000, "prompt_cache_hit_tokens": 1000, "completion_tokens": 0}), 0.00005)
    check("缺用量给 0", cost_of(house, {}), 0.0)
    check("缺价目给 0", cost_of({}, {"prompt_tokens": 1000}), 0.0)

    print("[6] over_single_limit")
    check("没超不回话", over_single_limit(config, 0.1), "")
    check("超了有提示", "超过单次上限" in over_single_limit(config, 0.4), True)

    print()
    print("-" * 40)
    print(f"通过 {passed} / 失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

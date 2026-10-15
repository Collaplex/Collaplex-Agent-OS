#!/usr/bin/env python3
"""交叉验证的比对逻辑回归: 指纹 / 分组 / 材料渲染, 纯逻辑不联网.

跑法: .venv/bin/python skill/mtp/tests/test_panel.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

from panel import fingerprint, group_by_answer, normalize, render  # noqa: E402

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


def main() -> int:
    print("交叉验证 · 比对逻辑")

    print("[1] normalize")
    check("去空白与标点", normalize(" 25 克, "), "25克")
    check("转小写", normalize("TRUE"), "true")
    check("去数字尾零", normalize("25.00"), "25")
    check("全角标点也去", normalize("（25），"), "25")

    print("[2] fingerprint")
    check("认 答案: 那行", fingerprint("推导...\n答案: 25"), "25")
    check("认全角冒号", fingerprint("答案：3 小时"), "3小时")
    check("多个就取最后一个", fingerprint("答案: 先算 5\n答案: 25"), "25")
    check("没有答案行就抠最后一个数字", fingerprint("我觉得是 45.1 秒左右"), "45.1")
    check("连数字都没有就取最后一行", fingerprint("不知道\n我也说不好"), "我也说不好")
    check("空回答给空串", fingerprint("   "), "")

    print("[3] group_by_answer")
    agree, split = group_by_answer({"a": "答案: 25", "b": "答案：25", "c": "答案: 30"})
    check("两家一致成一组", agree, [("25", ["a", "b"])])
    check("落单的进分歧", split, [("30", ["c"])])
    agree2, split2 = group_by_answer({"a": "答案: 1", "b": "答案: 2"})
    check("各说各的: 没有一致", agree2, [])
    check("各说各的: 两条分歧", len(split2), 2)

    print("[4] render")
    material = render("1+1=?", {
        "deepseek": {"成功": True, "模型": "deepseek-flash", "耗时秒": 1.1, "内容": "答案: 2"},
        "mimo": {"成功": True, "模型": "mimo-v2.6-flash", "耗时秒": 3.2, "内容": "答案：2"},
    })
    check("有标题", "# 交叉验证参考材料" in material, True)
    check("两家答案都在", ("deepseek-flash" in material) and ("mimo-v2.6-flash" in material), True)
    check("报出一致", "**一致**" in material, True)
    check("一致时不说分歧", "**分歧**" in material, False)

    material2 = render("1+1=?", {
        "deepseek": {"成功": True, "模型": "a", "耗时秒": 1.0, "内容": "答案: 2"},
        "mimo": {"成功": False, "模型": "b", "耗时秒": 0.0, "错误": "HTTP 500: x", "内容": ""},
    })
    check("答不上的写清错误", "没答上来" in material2, True)
    check("只有一家答上就不算一致", "没有任何两家答案一致" in material2, True)
    check("答不上那家不算一个声音", "(没抠出答案" in material2, False)

    print("[5] 真数据撞出来的两处 (2026-10-07 分歧探针)")
    check("百分号不改变数值", normalize("56.25%"), "56.25")
    check("百分号两边归一到同一个数", fingerprint("答案: 56.25%") == fingerprint("答案: 56.25"), True)
    agree3, split3 = group_by_answer({"deepseek": "答案: 56.25%", "mimo": "答案: 56.25"})
    check("同一数不同写法算一致", agree3, [("56.25", ["deepseek", "mimo"])])
    check("同一数不同写法不算分歧", split3, [])
    agree4, split4 = group_by_answer({"deepseek": "答案: 星期三", "mimo": ""})
    check("空回答不进一致", agree4, [])
    check("空回答也不进分歧", split4, [("星期三", ["deepseek"])])

    print()
    print("-" * 40)
    print(f"通过 {passed} / 失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

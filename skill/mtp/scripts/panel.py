#!/usr/bin/env python3
"""交叉验证（MTP）: 同一个问题问几家不同模型, 并排给出参考答案 + 标出分歧.

跟 skill/outsource 的分工:
    outsource  = 摇**一家**干活, 拿回产出 (卡住了摇人)
    mtp        = 摇**多家**答同一题, 把几份答案并排交出去当参考 (外援也不行时才用)
★ 钱只在一处管: 家的凭据 / 价目 / 预算 / 记账 全部沿用 outsource 的配置和流水.
★ 真综合由调用方(小模型)做: 这一件只负责"并排 + 把程序判得出的分歧点挑出来"。

用法:
    .venv/bin/python skill/mtp/main.py ask "<题>" [--家 deepseek,mimo] [--强制] [--安静]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent          # scripts
SKILL_DIR = HERE.parent                        # skill/mtp
PROJECT_ROOT = SKILL_DIR.parent.parent         # 项目根
OUTSOURCE_SCRIPTS = PROJECT_ROOT / "skill" / "outsource" / "scripts"
sys.path.insert(0, str(OUTSOURCE_SCRIPTS))     # 借 outsource 的钱袋子和调用件

from ask import call_house  # noqa: E402
from budget import (  # noqa: E402
    as_dict,
    as_list,
    append_ledger,
    budget_check,
    cost_of,
    house_of,
    ledger_path_of,
    now_stamp,
    read_config,
)

CONFIG_PATH = SKILL_DIR / "resources" / "mtp.json"


def read_mtp_config() -> dict[str, Any]:
    """读交叉验证自己的配置 (家 / 带本地 / 系统提示词)."""
    with CONFIG_PATH.open(encoding="utf-8") as fp:
        data: Any = json.load(fp)
    if not isinstance(data, dict):
        raise ValueError(f"配置根节点必须是对象: {CONFIG_PATH}")
    return as_dict(data)


def normalize(text: str) -> str:
    """答案归一化: 去空白 / 去标点 / 转小写 / 去掉数字尾零.

    ★ 顺序要紧: 必须**先**做数字尾零归一,**再**剥标点 —— 反过来小数点会先被当标点剥掉,
      "25.00" 变 "2500"、"45.1" 变 "451" (单测抓出来的)。
    ★ 小数点要保住: 只剥"不在两个数字之间"的点 (那是句号不是小数点)。
    ★ 百分号也剥: "56.25%" 和 "56.25" 是同一个数 —— 真数据上撞过,
      不剥会把"其实一致"报成**假分歧** (2026-10-07 打八折那道题: 一家写 `56.25%`、一家写 `56.25`)。
    ★ 已知没做的: 量词/单位的不同写法 (`3 小时` vs `3h`、`25 克` vs `25g`) 仍会被判成分歧 ——
      剥了会有**假一致**的风险 (`3 天` 与 `3 年` 会合并), 假一致比假分歧更坏, 所以先不剥。
    """
    cut = text.strip().lower()
    cut = re.sub(r"(\d+)\.0+(?=\D|$)", r"\1", cut)
    cut = re.sub(r"(?<!\d)\.|\.(?!\d)", "", cut)
    return re.sub(r"[\s,，。；;：:!！?？'\"“”‘’()（）\[\]【】%％]", "", cut)


def fingerprint(reply: str) -> str:
    """答案指纹: 用来判"几家答的是不是同一个东西".

    依次退: 最后一行 `答案: X` 的 X -> 整段最后一个数字 -> 最后一行原文.
    """
    text = reply.strip()
    found = re.findall(r"答案[:：]\s*(.+)", text)
    if found:
        return normalize(found[-1])
    numbers = re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if numbers:
        return normalize(numbers[-1])
    rows = [row for row in text.splitlines() if row.strip()]
    return normalize(rows[-1]) if rows else ""


def group_by_answer(answers: dict[str, str]) -> tuple[list[tuple[str, list[str]]], list[tuple[str, list[str]]]]:
    """按指纹分组: 返回 (一致的组, 只有一家那么答的组).

    一致的组 = 至少两家指纹相同 (这才是"交叉验证"的价值所在);
    分歧的组 = 只有一家那么答 (并排列出来, 让小模型自己看)。

    ★ **没答上来的不算一个声音**: 空回答 / 抠不出东西的, 不进分歧 (真数据上撞过 ——
      mimo 思考把 token 吃光返空, 结果"分歧"里挂出一条 `(没抠出答案:mimo)`, 那是失败不是分歧;
      失败在"各家答案"里已经标了 ✗, 再列进分歧只会往参考材料里灌噪声)。
    """
    buckets: dict[str, list[str]] = {}
    for name, reply in answers.items():
        key = fingerprint(reply)
        if not key:
            continue
        buckets.setdefault(key, []).append(name)
    agree = [(key, names) for key, names in buckets.items() if len(names) >= 2]
    split = [(key, names) for key, names in buckets.items() if len(names) < 2]
    agree.sort(key=lambda item: -len(item[1]))
    return agree, split


def render(question: str, results: dict[str, dict[str, Any]]) -> str:
    """把各家答案和程序判出的对照拼成一份参考材料 (markdown)."""
    answers = {name: str(row.get("内容", "")) for name, row in results.items()}
    agree, split = group_by_answer(answers)
    joined = " · ".join(f"{name}/{row.get('模型', '?')}" for name, row in results.items())
    lines: list[str] = [
        "# 交叉验证参考材料",
        "",
        f"- 题: {question}",
        f"- 参与: {joined}",
        "",
        "## 各家答案",
        "",
    ]
    for name, row in results.items():
        state = "✓" if row.get("成功") else "✗"
        lines.append(f"### {state} {name} · {row.get('模型', '?')} · {row.get('耗时秒', '?')} 秒")
        lines.append("")
        if row.get("成功"):
            lines.append(str(row.get("内容", "")).strip())
        else:
            lines.append(f"(没答上来: {row.get('错误', '?')})")
        lines.append("")
    lines += ["## 程序判出来的对照", ""]
    if agree:
        for key, names in agree:
            lines.append(f"- **一致**（{len(names)} 家）: {' / '.join(names)} → `{key}`")
    else:
        lines.append("- 没有任何两家答案一致")
    if split:
        for key, names in split:
            lines.append(f"- **分歧**（只有 {names[0]}）: `{key}`")
    else:
        lines.append("- 无分歧: 各家答案归一化后一致")
    return "\n".join(lines) + "\n"


def run_panel(
    question: str,
    names: list[str] | None = None,
    force: bool = False,
    quiet: bool = True,
) -> dict[str, Any]:
    """问几家 + 记账 + 出参考材料. 给 main() 和自动触发(outsource_hook)共用.

    返回 {可以, 为什么, 家数, 答上, 材料, 落盘, 金额, tok, 各家}
    可以=False 时"为什么"写清原因(开关/预算/家数不够), 材料为空 —— 调用方据此维持原样, 不许胡乱兜底。
    """
    money_config = read_config()           # outsource 的: 家 / 凭据 / 价目 / 预算
    mtp_config = read_mtp_config()         # mtp 的: 用哪几家 / 系统提示词

    picked = names or [str(item) for item in as_list(mtp_config.get("家"))]
    picked = [item for item in picked if item]
    if len(picked) < 2:
        return {"可以": False, "为什么": f"交叉验证至少要两家, 现在: {picked or '(空)'}", "材料": "", "家数": 0}

    allowed, why = budget_check(money_config, force=force)
    if not allowed:
        return {"可以": False, "为什么": f"钱袋子: {why}", "材料": "", "家数": len(picked)}

    houses: dict[str, dict[str, Any]] = {}
    for name in picked:
        _, house = house_of(money_config, name)
        houses[name] = house

    # 拼任务: 用 mtp 自己的系统提示词, 但复用 outsource 的调用件
    call_config = dict(money_config)
    call_config["系统提示词"] = mtp_config.get("系统提示词", "")
    call_config["调用"] = mtp_config.get("调用", money_config.get("调用", {}))

    print(f"交叉验证: {len(picked)} 家 ({', '.join(picked)}) · {why}")
    started = time.time()
    with ThreadPoolExecutor(max_workers=len(picked)) as pool:
        futures = {name: pool.submit(call_house, name, house, call_config, question)
                   for name, house in houses.items()}
        results = {name: future.result() for name, future in futures.items()}
    elapsed = round(time.time() - started, 1)

    rows: list[dict[str, Any]] = []
    total = 0.0
    total_tokens = 0
    for name, row in results.items():
        usage = as_dict(row.get("用量"))
        cost = cost_of(houses[name], usage)
        total += cost
        total_tokens += int(usage.get("total_tokens", 0) or 0)
        rows.append({
            "时间": now_stamp(), "来自": "mtp", "家": name, "模型": row.get("模型", ""),
            "成功": row.get("成功", False), "耗时秒": row.get("耗时秒", 0.0),
            "用量": usage, "金额": cost, "任务摘要": question.strip()[:80],
        })
    for row in rows:
        append_ledger(row, ledger_path_of(money_config))

    ok_count = sum(1 for row in results.values() if row.get("成功"))
    print(f"回来了: {ok_count}/{len(picked)} 家 · 并行 {elapsed} 秒 · 共 {total:.5f} 元 / {total_tokens} tok")

    material = render(question, results)
    folder = PROJECT_ROOT / str(as_dict(mtp_config.get("落盘")).get("产出目录") or "logs/mtp")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{now_stamp().replace(':', '').replace('-', '')}-交叉验证.md"
    target.write_text(material, encoding="utf-8")
    print(f"参考材料落盘: {target}")
    if not quiet:
        print("-" * 60)
        print(material)
    return {
        "可以": True, "为什么": why, "家数": len(picked), "答上": ok_count,
        "材料": material, "落盘": str(target), "金额": round(total, 6),
        "tok": total_tokens, "各家": {name: str(row.get("内容", "")) for name, row in results.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="交叉验证: 同一题问多家模型")
    parser.add_argument("题目", help="要问的题 (写清要求)")
    parser.add_argument("--家", default="", help="逗号分隔, 默认按配置")
    parser.add_argument("--强制", action="store_true", help="跳开关 (不跳预算)")
    parser.add_argument("--安静", action="store_true", help="不把参考材料打到 stdout (仍落盘)")
    args = parser.parse_args()

    names = [item.strip() for item in args.家.split(",") if item.strip()]
    try:
        done = run_panel(args.题目, names or None, force=args.强制, quiet=args.安静)
    except (FileNotFoundError, ValueError) as exc:
        print(f"交叉验证失败: {exc}")
        return 1
    if not done["可以"]:
        print(f"这次不跑交叉验证: {done['为什么']}")
        return 2
    return 0 if int(done["答上"]) >= 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())

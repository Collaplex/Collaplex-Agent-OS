#!/usr/bin/env python3
"""两级检索(冷热召回): 先查二层热 RAG, 命中即返回; 不命中落到三层冷 RAG.

对应 diagrams/rag-memory.drawio:

    模型调用 --no--> 二层rag --yes--> 模型调用
                       |
                      no
                       v
                     三层rag --yes--> 模型调用

- 二层 = 热 RAG: 原始未清洗语料, 已向量处理
- 三层 = 冷 RAG: 完整记忆与知识
- "命中" = top1 相似度 >= hit_threshold (resources/embed.json, 实测标定)
- 每层都用 **两路**: 纯向量 + 别名路(清洗管线产出的 alias.json, 纯字符串匹配不烧算力)

跑法:
    .venv/bin/python skill/rag/scripts/recall.py "上下文窗口怎么管理" -n 5
    .venv/bin/python skill/rag/scripts/recall.py "查询" --json
    .venv/bin/python skill/rag/scripts/recall.py "查询" --tier 3      # 只查某一层
    .venv/bin/python skill/rag/scripts/recall.py                      # 交互模式
前提: 向量服务起着 (scripts/embed_server.sh start), 索引已建 (scripts/embed.py)
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from search import (  # noqa: E402  (必须先插 sys.path 再导入)
    CONFIG_PATH,
    build_retriever,
    load_config,
    resolve_model,
    resolve_tier,
    search_with_alias,
)
import store  # noqa: E402  (关键词兜底要用它)

# 一层只建一次检索器, 交互模式下不重复连接/加载
Retriever = tuple[Callable[[list[float], int], list[dict[str, Any]]], str, int, str]
_CACHE: dict[str, Retriever | None] = {}

DEFAULT_THRESHOLD = 0.53
DEFAULT_ORDER = ("2", "3")


def 拆词(query: str) -> list[str]:
    """把一句问句拆成能拿去 ILIKE 的词: 整句优先, 再按虚词/标点切开, 剩 1 个字的丢掉。"""
    整句 = query.strip()
    词: list[str] = [整句] if 整句 else []
    for 片 in re.split(r"[\s,，、。;；:：!！?？的和与及]", 整句):
        片 = 片.strip()
        if len(片) >= 2 and 片 not in 词:
            词.append(片)
    return 词


def 关键词兜底(
    query: str, config: dict[str, Any], top_k: int, 层: tuple[str, ...]
) -> tuple[list[dict[str, Any]], str]:
    """语义路整条不可用时的兜底: SQL ILIKE 取字面命中的原文。返回 (结果, 出错说明)。

    ★ 为什么要兜底(2026-10-11 实测): 嵌入服务没起时整条向量路都会失败 ——
      以前这里直接 0 命中, 主 agent 于是对用户说"我没有之前对话的记忆",
      把"服务没起"说成了"我记不住"。空 != 没事发生, 降级要说清。
    """
    try:
        conn = store.connect(config)
    except Exception as error:  # noqa: BLE001 - 兜底自己也失败时, 把原因带回去而不是吞掉
        return [], f"关键词兜底连不上库: {type(error).__name__}: {error}"

    merged: dict[str, dict[str, Any]] = {}
    try:
        for 词 in 拆词(query):
            for tier in 层:
                try:
                    rows = store.按词搜(conn, config, tier, 词, top_k)
                except Exception as error:  # noqa: BLE001
                    return (
                        list(merged.values()),
                        f"关键词兜底出错({tier}): {type(error).__name__}: {error}",
                    )
                for row in rows:
                    row = dict(row)
                    row["tier"] = tier
                    key = str(row.get("hash") or str(row.get("text", ""))[:80])
                    merged.setdefault(key, row)
            if merged:
                break  # 整句先试; 整句没中才轮到拆出来的词
    finally:
        conn.close()
    return list(merged.values()), ""


def load_tier(tier: str, config: dict[str, Any]) -> Retriever | None:
    """建某一层的检索器(JSON 还是 PG 由配置决定); 该层没数据返回 None. 结果缓存."""
    if tier not in _CACHE:
        try:
            built = build_retriever(config, tier)
            _CACHE[tier] = built if built[2] > 0 else None
        except (FileNotFoundError, ValueError, RuntimeError):
            _CACHE[tier] = None
    return _CACHE[tier]


def retrieve(
    query: str,
    config: dict[str, Any],
    model_info: dict[str, str],
    top_k: int,
    only_tier: str | None = None,
) -> dict[str, Any]:
    """按图走一遍: 二层命中就回, 不命中落三层."""
    threshold = float(config.get("hit_threshold", DEFAULT_THRESHOLD))
    order = (only_tier,) if only_tier else DEFAULT_ORDER

    alias_note: dict[str, Any] = {}
    notes: list[str] = []
    trace: list[dict[str, Any]] = []
    for tier in order:
        loaded = load_tier(tier, config)
        if loaded is None:
            tier_name, _ = resolve_tier(config, tier)
            trace.append({"tier": tier, "name": tier_name, "state": "该层没数据"})
            continue

        retriever, tier_name, total, _note = loaded
        # 向量路 + 别名路: 别名表是清洗管线从对话里产出的「概念 -> 其他叫法」
        try:
            results, alias_note = search_with_alias(
                query, config, model_info, retriever, top_k
            )
        except Exception as error:  # noqa: BLE001 - 嵌入服务连不上/索引坏了都算"语义路不可用"
            原因 = f"{type(error).__name__}: {error}"
            results, 兜底错 = 关键词兜底(query, config, top_k, order)
            说明 = f"{tier_name} 这层语义检索没走通({原因}) → 改走关键词兜底"
            if 兜底错:
                说明 += f"；{兜底错}"
            if results:
                说明 += f"，字面命中 {len(results)} 条"
            else:
                说明 += "，字面也没命中"
            notes.append(说明)
            trace.append(
                {
                    "tier": tier,
                    "name": tier_name,
                    "state": "语义不可用·关键词兜底",
                    "count": total,
                    "best": 0.0,
                    "note": 说明,
                }
            )
            if results:
                return {
                    "query": query,
                    "tier": tier,
                    "tier_name": tier_name,
                    "hit": True,
                    "降级": "关键词兜底",
                    "threshold": threshold,
                    "alias": alias_note,
                    "note": 说明,
                    "notes": notes,
                    "trace": trace,
                    "results": results,
                }
            continue

        best = float(results[0]["score"]) if results else 0.0
        hit = best >= threshold
        step: dict[str, Any] = {
            "tier": tier,
            "name": tier_name,
            "state": "命中" if hit else "未命中",
            "count": total,
            "best": best,
        }
        if alias_note.get("命中概念"):
            step["别名"] = f"{alias_note['命中概念']} -> {alias_note['别名池']}"
        trace.append(step)
        if hit:
            return {
                "query": query,
                "tier": tier,
                "tier_name": tier_name,
                "hit": True,
                "threshold": threshold,
                "alias": alias_note,
                "trace": trace,
                "results": results,
            }

    return {
        "query": query,
        "tier": None,
        "tier_name": None,
        "hit": False,
        "threshold": threshold,
        "alias": alias_note,
        "note": notes[-1] if notes else "",
        "notes": notes,
        "trace": trace,
        "results": [],
    }


def print_answer(answer: dict[str, Any]) -> None:
    """终端里打印判定过程和完整原文."""
    print(f"\n查询: {answer['query']}")
    print(f"阈值: {answer['threshold']}")
    for step in answer["trace"]:
        line = f"  {step['tier']} {step['name']}: {step['state']}"
        if "best" in step:
            line += f"  (top1 {step['best']:.4f}, 库 {step['count']} 条)"
        if step.get("别名"):
            line += f"\n      别名路: {step['别名']}"
        print(line)

    if not answer["hit"]:
        print("两层都没命中")
        return

    print(f"由 {answer['tier']} {answer['tier_name']} 应答:")
    for result in answer["results"]:
        print("-" * 64)
        print(f"[{result['rank']}] 相似度 {result['score']:.4f}   索引 #{result['index']}   出处 {result.get('source') or '-'}")
        print(str(result["text"]))
    print("-" * 64)


def run_once(
    query: str,
    config: dict[str, Any],
    model_info: dict[str, str],
    top_k: int,
    only_tier: str | None,
    as_json: bool,
) -> None:
    answer = retrieve(query, config, model_info, top_k, only_tier)
    if as_json:
        print(json.dumps(answer, ensure_ascii=False, indent=2))
    else:
        print_answer(answer)


def main() -> None:
    parser = argparse.ArgumentParser(description="两级检索: 二层热 RAG -> 三层冷 RAG")
    parser.add_argument("query", nargs="?", help="查询文本; 不给则进交互模式")
    parser.add_argument("-n", "--top-k", type=int, default=5, help="返回条数 (默认 5)")
    parser.add_argument("--tier", choices=("2", "3"), default=None, help="只查这一层")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args()

    config = load_config(CONFIG_PATH)
    model_info = resolve_model()

    if args.query:
        run_once(args.query, config, model_info, args.top_k, args.tier, args.json)
        return

    threshold = float(config.get("hit_threshold", DEFAULT_THRESHOLD))
    print(f"两级检索 | 阈值 {threshold} | {model_info['model']} | 输入查询, /exit 退出")
    while True:
        try:
            query = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if query in ("/exit", "exit", "quit"):
            break
        if not query:
            continue
        run_once(query, config, model_info, args.top_k, args.tier, args.json)


if __name__ == "__main__":
    main()

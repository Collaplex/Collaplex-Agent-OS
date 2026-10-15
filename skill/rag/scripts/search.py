#!/usr/bin/env python3
"""向量检索: 查询 -> 向量 -> 余弦排序 -> 返回源数据(原文).

只回源数据: 索引 / 原文 / 哈希 / 相似度, 不回向量.

检索走两路: 纯向量 + **别名路**(清洗管线产出的 alias.json, 纯字符串匹配不烧算力)。
别名路补的是语义盲区 —— 问「网络设备」能召回答「软路由/交换机」的条目。
模型调用信息读 .env, 索引路径读 resources/embed.json.

跑法:
    .venv/bin/python skill/rag/scripts/search.py "上下文窗口怎么管理"
    .venv/bin/python skill/rag/scripts/search.py                     # 交互模式
    .venv/bin/python skill/rag/scripts/search.py "查询" -n 3 --json
前提: 向量服务起着 (scripts/embed_server.sh start), 索引已建 (scripts/embed.py)
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable, cast

import numpy as np
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent      # skill/rag/scripts
sys.path.insert(0, str(HERE))

import store  # noqa: E402  (同目录模块, 得先补 sys.path)
SKILL_DIR = HERE.parent                      # skill/rag
ROOT = SKILL_DIR.parent.parent               # 项目根 (放 .env)
CONFIG_PATH = SKILL_DIR / "resources" / "embed.json"
ENV_PATH = ROOT / ".env"

# 本机 http_proxy 会拦 127.0.0.1, 显式清空代理
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

FloatMatrix = np.ndarray[Any, np.dtype[np.float32]]

load_dotenv(ENV_PATH)


# ============================================================
# 配置
# ============================================================

def load_config(config_path: Path) -> dict[str, Any]:
    """读配置 JSON."""
    if not config_path.is_file():
        raise FileNotFoundError(f"配置不存在: {config_path}")
    with open(config_path, "r", encoding="utf-8") as fp:
        config: dict[str, Any] = json.load(fp)
    if not config:
        raise ValueError(f"配置是空的: {config_path}")
    return config


def resolve_model() -> dict[str, str]:
    """模型调用信息统一从 .env 取, 与 embed.py 同一套."""
    base_url = (os.getenv("EMBEDDING_BASE_URL") or "").rstrip("/")
    model = os.getenv("EMBEDDING_MODEL") or ""
    if not base_url or not model:
        raise RuntimeError(f".env 缺 EMBEDDING_BASE_URL 或 EMBEDDING_MODEL: {ENV_PATH}")
    return {"endpoint": f"{base_url}/embeddings", "model": model}


def resolve_tier(config: dict[str, Any], tier: str) -> tuple[str, Path]:
    """层号 -> (层名, 索引路径). 层定义在 resources/embed.json 的 tiers 段."""
    tiers = config.get("tiers")
    if not isinstance(tiers, dict):
        raise ValueError(f"配置缺 tiers 段: {CONFIG_PATH}")
    table = cast(dict[str, Any], tiers)
    entry = table.get(tier)
    if not isinstance(entry, dict):
        raise ValueError(f"配置里没有这一层: {tier}  (可选 {sorted(table)})")
    row = cast(dict[str, Any], entry)
    return str(row.get("name", tier)), SKILL_DIR / str(row["output"])


# ============================================================
# 索引
# ============================================================

def load_index(index_path: Path) -> tuple[list[dict[str, Any]], FloatMatrix]:
    """读索引, 返回 (条目列表, 归一化向量矩阵). 点积即余弦."""
    if not index_path.is_file():
        raise FileNotFoundError(f"索引不存在: {index_path}  (先跑 scripts/embed.py)")

    with open(index_path, "r", encoding="utf-8") as fp:
        data = json.load(fp)

    items: list[dict[str, Any]] = []
    rows: list[list[float]] = []
    for item in data.get("items", []):
        raw_vector = item.get("vector")
        if not isinstance(raw_vector, list):
            continue
        values = cast(list[Any], raw_vector)
        items.append(item)
        rows.append([float(value) for value in values])

    if not items:
        raise ValueError(f"索引里没有可用条目: {index_path}")

    matrix = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return items, matrix / norms


# ============================================================
# 向量
# ============================================================

def embed_query(text: str, config: dict[str, Any], model_info: dict[str, str]) -> list[float]:
    """把查询文本转成向量."""
    payload = json.dumps(
        {"input": [text], "model": model_info["model"]},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        model_info["endpoint"],
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with OPENER.open(request, timeout=float(config["timeout"])) as response:
        body = json.loads(response.read().decode("utf-8"))
    return [float(value) for value in body["data"][0]["embedding"]]


# ============================================================
# 检索
# ============================================================

def search(
    query_vector: list[float],
    matrix: FloatMatrix,
    items: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """余弦排序, 返回源数据. 刻意不带 vector 字段."""
    query = np.asarray(query_vector, dtype=np.float32)
    if query.shape[0] != matrix.shape[1]:
        raise ValueError(
            f"查询向量 {query.shape[0]} 维与索引 {matrix.shape[1]} 维不一致 (模型换过了?)"
        )
    norm = float(np.linalg.norm(query))
    if norm > 0:
        query = query / norm

    scores = matrix @ query
    order = np.argsort(-scores)[: max(top_k, 0)]

    results: list[dict[str, Any]] = []
    for rank, position in enumerate(order, 1):
        item = items[int(position)]
        results.append({
            "rank": rank,
            "score": round(float(scores[int(position)]), 6),
            "index": item.get("index"),
            "hash": item.get("hash"),
            "source": item.get("source", ""),
            "text": item.get("text"),
        })
    return results


# ============================================================
# 别名路（清洗管线产出的 alias.json）
# ============================================================

def load_aliases(config: dict[str, Any]) -> list[dict[str, Any]]:
    """读别名表 —— 清洗管线从对话里产出的「概念 -> 其他叫法」。

    没有这个文件就返回空表, 检索照常走纯向量, 不受影响。
    """
    section = config.get("alias")
    if not isinstance(section, dict):
        return []
    table = cast(dict[str, Any], section)
    path = SKILL_DIR / str(table.get("index", "scripts/alias.json"))
    if not path.is_file():
        return []
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    rows = cast(dict[str, Any], data).get("items", [])
    return [cast(dict[str, Any], x) for x in cast(list[Any], rows) if isinstance(x, dict)]


def expand_query(query: str, rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """查询里提到哪个概念, 就把它的别名取出 —— 返回 (命中概念, 别名池).

    ★ 纯字符串包含匹配: 别名表**不嵌向量**, 这条路几乎不花成本。
      (旧项目实测: 别名路把召回从 9/12 拉到 11/12, 追平手工整理。)
    """
    concepts: list[str] = []
    pool: list[str] = []
    for row in rows:
        concept = str(row.get("概念", "")).strip()
        alias = str(row.get("别名词", "")).strip()
        if not concept or concept not in query:
            continue
        if concept not in concepts:
            concepts.append(concept)
        if alias and alias not in pool:
            pool.append(alias)
    return concepts, pool


def search_with_alias(
    query: str,
    config: dict[str, Any],
    model_info: dict[str, str],
    retrieve: Callable[[list[float], int], list[dict[str, Any]]],
    top_k: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """向量检索 + 别名扩展 —— 返回 (结果, 别名路的说明).

    原文查询取几条, 每个别名再各取几条, **按 index 合并去重保留最高分**。

    补的是向量路的语义盲区: 用户问「网络设备」, 语料里答的是「软路由 / 交换机」,
    机器自己看不出这层对应, 得靠清洗管线产出的别名表告诉它。
    """
    section = config.get("alias")
    table = cast(dict[str, Any], section) if isinstance(section, dict) else {}
    base_k = int(table.get("base_k", 3))
    per_alias = int(table.get("per_alias", 2))
    max_aliases = int(table.get("max_aliases", 4))

    merged: dict[int, dict[str, Any]] = {}

    def absorb(results: list[dict[str, Any]]) -> None:
        for row in results:
            key = int(cast(int, row.get("index") or 0))
            if key not in merged or float(row["score"]) > float(merged[key]["score"]):
                merged[key] = row

    wide = max(base_k, top_k)
    absorb(retrieve(embed_query(query, config, model_info), wide))

    note: dict[str, Any] = {"命中概念": [], "别名池": [], "多召回": 0}
    if bool(table.get("enabled", True)):
        concepts, pool = expand_query(query, load_aliases(config))
        note["命中概念"] = concepts
        note["别名池"] = pool[:max_aliases]
        for alias in pool[:max_aliases]:
            absorb(retrieve(embed_query(alias, config, model_info), max(per_alias, 1)))

    ranked = sorted(merged.values(), key=lambda row: -float(row["score"]))
    note["多召回"] = max(0, len(ranked) - wide)
    final = ranked[: max(top_k, 0)]
    for rank, row in enumerate(final, 1):
        row["rank"] = rank
    return final, note


# ============================================================
# 输出
# ============================================================

def print_results(query: str, results: list[dict[str, Any]]) -> None:
    """终端里逐条打印完整原文."""
    print(f"\n查询: {query}")
    if not results:
        print("  没有命中")
        return
    print(f"命中 {len(results)} 条 (相似度降序):")
    for result in results:
        print("-" * 64)
        print(f"[{result['rank']}] 相似度 {result['score']:.4f}   索引 #{result['index']}   出处 {result['source'] or '-'}")
        print(str(result["text"]))
    print("-" * 64)


# ============================================================
# 主流程
# ============================================================

def run_once(
    query: str,
    config: dict[str, Any],
    model_info: dict[str, str],
    retrieve: Callable[[list[float], int], list[dict[str, Any]]],
    top_k: int,
    as_json: bool,
) -> None:
    results, note = search_with_alias(query, config, model_info, retrieve, top_k)
    if as_json:
        print(json.dumps(
            {"query": query, "alias": note, "results": results},
            ensure_ascii=False, indent=2,
        ))
        return
    if note["命中概念"]:
        print(f"\n别名路: 命中概念 {note['命中概念']} -> 扩了 {note['别名池']}"
              f" (候选比纯向量多 {note['多召回']} 条)")
    print_results(query, results)


def build_retriever(
    config: dict[str, Any], tier: str
) -> tuple[Callable[[list[float], int], list[dict[str, Any]]], str, int, str]:
    """按 store 后端建检索器: 返回 (检索函数, 层名, 条数, 索引说明).

    PG 后端: 向量留在库里, 走 HNSW; JSON 后端: 全量读内存, numpy 暴力(老路).
    """
    tiers = config.get("tiers")
    tier_table = cast(dict[str, Any], tiers) if isinstance(tiers, dict) else {}
    entry = tier_table.get(tier)
    row = cast(dict[str, Any], entry) if isinstance(entry, dict) else {}
    tier_name = str(row.get("name", tier))

    if store.is_pg(config):
        conn = store.connect(config)
        total = store.count(conn, config, tier)

        def retrieve_pg(query_vector: list[float], top_k: int) -> list[dict[str, Any]]:
            return store.search(conn, config, tier, query_vector, top_k)

        return retrieve_pg, tier_name, total, f"PG {store.table_name(config)}"

    index_path = SKILL_DIR / str(row["output"])
    items, matrix = load_index(index_path)

    def retrieve_json(query_vector: list[float], top_k: int) -> list[dict[str, Any]]:
        return search(query_vector, matrix, items, top_k)

    return retrieve_json, tier_name, len(items), f"JSON {index_path.name}"


def main() -> None:
    parser = argparse.ArgumentParser(description="向量检索, 返回源数据")
    parser.add_argument("query", nargs="?", help="查询文本; 不给则进交互模式")
    parser.add_argument("-n", "--top-k", type=int, default=5, help="返回条数 (默认 5)")
    parser.add_argument("--tier", choices=("2", "3"), default=None,
                        help="查哪一层 (2=热 RAG 原始未清洗, 3=冷 RAG 完整记忆与知识)")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args()

    config = load_config(CONFIG_PATH)
    model_info = resolve_model()
    tier = args.tier or str(config.get("tier", "2"))
    retrieve, tier_name, total, source_note = build_retriever(config, tier)

    if args.query:
        run_once(args.query, config, model_info, retrieve, args.top_k, args.json)
        return

    print(f"层 {tier} {tier_name}  [{source_note}]")
    print(f"索引 {total} 条 | {model_info['model']} | 输入查询, /exit 退出")
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
        run_once(query, config, model_info, retrieve, args.top_k, args.json)


if __name__ == "__main__":
    main()

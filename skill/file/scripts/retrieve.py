#!/usr/bin/env python3
"""文件读写命令库的检索件 —— 语料/索引在 file skill, 检索活借 rag 的函数.

分工:
    rag      公共前置件 (切片 chunker / 转向量 embed / 余弦检索 search) —— 本件不重复实现, 也不往 rag 里加东西
    file     自己出三样: 语料 commands/*.md · 索引 commands-index.json · 检索入口 (本件)
    本件独有  倒排(BM25)那一路 —— rag 里没有, 但别的层也能用 (--index 指过去就行)

用法:
    .venv/bin/python skill/file/scripts/retrieve.py index                   # 建/更新命令库索引(按 hash 复用向量)
    .venv/bin/python skill/file/scripts/retrieve.py find "改一个函数" -n 3
    .venv/bin/python skill/file/scripts/retrieve.py find "查询" --mode rrf
    .venv/bin/python skill/file/scripts/retrieve.py find "查询" --index skill/file/commands-index.json
    .venv/bin/python skill/file/scripts/retrieve.py find "查询" --tier 2      # 借 rag 的层定义(仅 JSON 后端; PG 后端请用 rag/scripts/recall.py)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import numpy as np

HERE = Path(__file__).resolve().parent              # skill/file/scripts
SKILL_FILE = HERE.parent                             # skill/file
PROJECT = SKILL_FILE.parent.parent                   # 项目根
RAG_SCRIPTS = PROJECT / "skill" / "rag" / "scripts"
sys.path.insert(0, str(RAG_SCRIPTS))

import embed as rag_embed  # noqa: E402   (要先插 sys.path)
import search as rag_search  # noqa: E402
import store as rag_store  # noqa: E402

COMMANDS = SKILL_FILE / "commands"                   # 语料
INDEX = SKILL_FILE / "commands-index.json"           # 索引
CACHE = SKILL_FILE / "cache"                         # 倒排表缓存 (别往 rag 目录里写)

K1 = 1.2            # BM25 词频饱和
B = 0.75            # BM25 长度归一
RRF_K = 60          # RRF 平滑
TITLE_BOOST = 1     # 标题行(命令名)额外权重: 实测给到 3 没收益, 留开关便于按层调
TOKENIZER_TAG = "tok-v1"


# ============================================================
# 分词: 中文按字符 2-gram, 英文/数字按词 (不引分词库)
# ============================================================

def tokenize(text: str) -> list[str]:
    """中文切 2-gram, 英文数字切单词, 全小写."""
    lower = text.lower()
    tokens: list[str] = []
    word: list[str] = []

    def flush() -> None:
        if word:
            tokens.append("".join(word))
            word.clear()

    for ch in lower:
        if ch.isascii() and (ch.isalnum() or ch in "._-+/"):
            word.append(ch)
        else:
            flush()
            if "\u4e00" <= ch <= "\u9fff":
                tokens.append(ch)
    flush()

    merged: list[str] = []
    run: list[str] = []
    for token in tokens:
        if len(token) == 1 and "\u4e00" <= token <= "\u9fff":
            run.append(token)
            continue
        if run:
            merged.extend(run)
            merged.extend(run[i] + run[i + 1] for i in range(len(run) - 1))
            run.clear()
        merged.append(token)
    if run:
        merged.extend(run)
        merged.extend(run[i] + run[i + 1] for i in range(len(run) - 1))
    return merged


def doc_tokens(text: str) -> list[str]:
    """文档词: 正文词 + 标题行重复 TITLE_BOOST 次."""
    title = next((line for line in text.splitlines() if line.startswith("#")), "")
    body = tokenize(text)
    if not title or TITLE_BOOST <= 1:
        return body
    head = tokenize(title)
    return body + head * TITLE_BOOST


# ============================================================
# 倒排表: 建 / 缓存 / 读
# ============================================================

def corpus_fingerprint(items: list[dict[str, Any]]) -> str:
    """指纹: 分词参数 + 条目数 + 每条 hash —— 换参数或换语料后缓存自动失效."""
    digest = hashlib.sha256()
    digest.update(f"{TOKENIZER_TAG}-k1{K1}-b{B}-boost{TITLE_BOOST}".encode())
    digest.update(str(len(items)).encode())
    for item in items:
        digest.update(str(item.get("hash", "")).encode())
    return digest.hexdigest()[:16]


def table_path(index_path: Path) -> Path:
    """倒排表缓存位置: file skill 的 cache 目录 (不往 rag 目录里写)."""
    return CACHE / f"{index_path.stem}-invert.json"


def build_table(items: list[dict[str, Any]]) -> dict[str, Any]:
    """建倒排: 词 -> [[doc, tf], ...], 外加每篇长度和平均长度."""
    postings: dict[str, list[list[int]]] = {}
    lengths: list[int] = []
    for position, item in enumerate(items):
        tokens = doc_tokens(str(item.get("text", "")))
        lengths.append(len(tokens))
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        for token, tf in counts.items():
            postings.setdefault(token, []).append([position, tf])
    return {
        "fingerprint": corpus_fingerprint(items),
        "docs": len(items),
        "avg_len": (sum(lengths) / len(lengths)) if lengths else 0.0,
        "lengths": lengths,
        "postings": postings,
    }


def load_or_build(index_path: Path, items: list[dict[str, Any]], rebuild: bool = False) -> dict[str, Any]:
    """读缓存的倒排表; 指纹对不上或强制重建就重算并落盘."""
    path = table_path(index_path)
    if not rebuild and path.is_file():
        with open(path, "r", encoding="utf-8") as fp:
            cached = cast(dict[str, Any], json.load(fp))
        if cached.get("fingerprint") == corpus_fingerprint(items):
            return cached
    table = build_table(items)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False)
    return table


def bm25_scores(table: dict[str, Any], query: str) -> list[float]:
    """BM25 打分, 每篇一个分数, 顺序与 items 一致."""
    postings = cast(dict[str, list[list[int]]], table["postings"])
    lengths = cast(list[int], table["lengths"])
    total = int(table["docs"])
    avg_len = float(table["avg_len"]) or 1.0
    scores = [0.0] * total

    for term in set(tokenize(query)):
        rows = postings.get(term)
        if not rows:
            continue
        df = len(rows)
        idf = math.log(1.0 + (total - df + 0.5) / (df + 0.5))
        for doc, tf in rows:
            length = lengths[doc] or 1
            denom = tf + K1 * (1.0 - B + B * length / avg_len)
            scores[doc] += idf * (tf * (K1 + 1.0)) / denom
    return scores


# ============================================================
# 合并 (两路 -> 一路)
# ============================================================

def rank_of(scores: list[float]) -> list[int]:
    """分数降序的 doc 下标序列."""
    return [int(value) for value in np.argsort(-np.asarray(scores, dtype=np.float64))]


def merge_rrf(legs: list[list[int]], total: int) -> list[float]:
    """RRF: 每路按名次给 1/(k+rank)."""
    fused = [0.0] * total
    for ranking in legs:
        for rank, doc in enumerate(ranking, 1):
            fused[doc] += 1.0 / (RRF_K + rank)
    return fused


def merge_weight(legs: list[list[float]], alpha: float) -> list[float]:
    """分数归一(除以各路最大值)后加权."""
    fused = [0.0] * len(legs[0])
    for weight, scores in zip((alpha, 1.0 - alpha), legs):
        top = max(scores) if scores else 0.0
        if top <= 0:
            continue
        for doc, score in enumerate(scores):
            fused[doc] += weight * score / top
    return fused


# ============================================================
# 建索引: 切片/转向量/存盘的活全借 rag
# ============================================================

def build_index(inputs: list[str], output: Path) -> int:
    """建/更新索引: 按语料目录重建条目, 向量按 hash 复用旧索引."""
    config = rag_embed.load_config(rag_search.CONFIG_PATH)
    model_info = rag_embed.resolve_model()
    chunk_size = int(config["chunk_size"])

    files = rag_embed.collect_files(inputs, config)
    print(f"[切片] 文件 {len(files)} 个, 目标块大小 {chunk_size} 字")
    items = rag_embed.build_chunks(files, chunk_size)
    print(f"[切片] 共 {len(items)} 块")

    reused: dict[str, list[float]] = {}
    for item in rag_embed.load_existing(output):
        reused[str(item["hash"])] = cast(list[float], item["vector"])
    rag_embed.embed_items(items, config, reused, model_info)

    export = rag_embed.export_items(items)
    meta: dict[str, Any] = {
        "model": model_info["model"],
        "endpoint": model_info["endpoint"],
        "dimension": len(export[0]["vector"]) if export else 0,
        "count": len(export),
        "chunk_size": chunk_size,
        "mode": "rebuild (向量按 hash 复用)",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    rag_embed.save_index({"meta": meta, "items": export}, output)
    print(f"[落盘] {output}")
    print(f"[完成] {len(export)} 条, {meta['dimension']} 维")
    return 0


# ============================================================
# 检索: 向量路借 rag, 倒排路在本件
# ============================================================

def vector_scores_of(
    matrix: np.ndarray[Any, np.dtype[np.float32]],
    query_vector: list[float],
) -> list[float]:
    """余弦: 索引矩阵已归一, 查询向量归一后点积."""
    query = np.asarray(query_vector, dtype=np.float32)
    norm = float(np.linalg.norm(query))
    if norm > 0:
        query = query / norm
    return [float(value) for value in (matrix @ query)]


def label_of(item: dict[str, Any], strip: str = "") -> str:
    """条目显示名: 出处相对路径 (剥掉给定前缀)."""
    source = str(item.get("source", ""))
    return source[len(strip):] if strip and source.startswith(strip) else source


def find(
    query: str,
    index_path: Path,
    top_k: int,
    mode: str,
    alpha: float,
    full: bool = True,
) -> None:
    """查一层: 向量路 + 倒排路, 按 mode 出结果.

    full=True 时把命中条目的**正文**也贴出来 —— 调 tools 的那一步(exec)要的是
    "这条命令怎么写", 只给个文件名等于让它猜; `-t/--只要表` 关掉, 只要排名表.
    """
    config = rag_search.load_config(rag_search.CONFIG_PATH)
    model_info = rag_search.resolve_model()
    items, matrix = rag_search.load_index(index_path)
    table = load_or_build(index_path, items)

    vec = vector_scores_of(matrix, rag_search.embed_query(query, config, model_info))
    inv = bm25_scores(table, query)
    if mode == "rrf":
        fused = merge_rrf([rank_of(vec), rank_of(inv)], len(items))
    elif mode == "weight":
        fused = merge_weight([vec, inv], alpha)
    else:
        fused = vec

    vec_rank = {doc: rank for rank, doc in enumerate(rank_of(vec), 1)}
    inv_rank = {doc: rank for rank, doc in enumerate(rank_of(inv), 1)}
    strip = str(COMMANDS) + "/"

    print(f"\n查询: {query}")
    print(f"索引 {index_path.name} · {len(items)} 条 · 模式 {mode}")
    print("-" * 92)
    print(f"{'名次':<6}{'出处':<36}{'分':<12}{'向量':<20}倒排")
    hits = rank_of(fused)[:top_k]
    for position, doc in enumerate(hits, 1):
        print(f"{position:<6}{label_of(items[doc], strip):<36}{fused[doc]:<12.4f}"
              f"{vec_rank[doc]:>4} / {vec[doc]:<12.4f}{inv_rank[doc]:>3} / {inv[doc]:.3f}")
    print("-" * 92)

    if full:
        for position, doc in enumerate(hits, 1):
            print(f"\n【{position}】{label_of(items[doc], strip)}   分 {fused[doc]:.4f}")
            print(str(items[doc].get("text", "")).strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="命令库检索件: 语料/索引在 file skill, 检索借 rag")
    sub = parser.add_subparsers(dest="command", required=True)

    index_parser = sub.add_parser("index", help="建/更新命令库索引")
    index_parser.add_argument("inputs", nargs="*", default=[str(COMMANDS)], help=f"语料路径 (默认 {COMMANDS})")
    index_parser.add_argument("-o", "--output", default=str(INDEX), help=f"索引落盘路径 (默认 {INDEX})")

    find_parser = sub.add_parser("find", help="查一层")
    find_parser.add_argument("query", help="查询文本")
    find_parser.add_argument("-n", "--top-k", type=int, default=5, help="返回条数 (默认 5)")
    find_parser.add_argument("--index", default=str(INDEX), help="索引路径 (默认命令库)")
    find_parser.add_argument("--tier", choices=("2", "3"), default=None,
                             help="改用 rag 的层定义: 2=热 RAG, 3=冷 RAG")
    find_parser.add_argument("--mode", choices=("vector", "rrf", "weight"), default="vector",
                             help="vector=只向量(默认) / rrf / weight=两路合并")
    find_parser.add_argument("--alpha", type=float, default=0.5, help="weight 模式下向量的权重")
    find_parser.add_argument("--rebuild", action="store_true", help="强制重建倒排表")
    find_parser.add_argument("-t", "--只要表", dest="table_only", action="store_true",
                             help="只出排名表, 不贴条目正文 (默认贴)")

    args = parser.parse_args()

    if args.command == "index":
        return build_index(list(args.inputs), Path(str(args.output)))

    index_path = Path(str(args.index))
    if args.tier:
        config = rag_search.load_config(rag_search.CONFIG_PATH)
        if rag_store.is_pg(config):
            print("[层] rag 的两层库现在落在 PostgreSQL 里 (store.backend=pg), 本件的 --tier 只认 JSON 后端。")
            print(f"     要查这两层请用: .venv/bin/python skill/rag/scripts/recall.py \"{args.query}\"")
            return 1
        tier_name, index_path = rag_search.resolve_tier(config, str(args.tier))
        print(f"[层] {args.tier} {tier_name}")
    if args.rebuild:
        items, _matrix = rag_search.load_index(index_path)
        load_or_build(index_path, items, True)
    find(args.query, index_path, args.top_k, args.mode, args.alpha,
         full=not bool(args.table_only))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""给一句话, 找出该用哪个 skill.

返回: 命中的 skill 描述 + 相对目录 (设计图要的就是这两样).
语料是各 skill 的 SKILL.md frontmatter, 由 index_skills.py 建.

跑法:
    .venv/bin/python skill/skill_search/scripts/find_skill.py "把 PDF 转成 markdown"
    .venv/bin/python skill/skill_search/scripts/find_skill.py "..." -n 3 --json
    .venv/bin/python skill/skill_search/scripts/find_skill.py            # 交互模式
前提: 向量服务起着 (scripts/embed_server.sh start), 索引已建 (index_skills.py)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from core import (  # noqa: E402  (必须先插 sys.path 再导入)
    cosine,
    embed_texts,
    index_path,
    load_config,
    load_items,
    resolve_model,
    to_matrix,
)


def field_of(frontmatter: str, key: str) -> str:
    """从 frontmatter 原文里取一个字段的值 (只认单行 value)."""
    for line in frontmatter.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return ""


def find(
    query: str,
    config: dict[str, Any],
    model_info: dict[str, str],
    top_k: int,
) -> tuple[list[dict[str, Any]], int, float | None]:
    """查一次. 返回 (命中列表, 库里共几个, 阈值)."""
    path = index_path(config)
    items = load_items(path)
    if not items:
        raise SystemExit(f"[错误] 索引不存在或为空: {path}  (先跑 index_skills.py)")

    query_vector = embed_texts([query], config, model_info)[0]
    results = cosine(query_vector, to_matrix(items), items, top_k)

    for result in results:
        frontmatter = str(result["text"])
        result["name"] = field_of(frontmatter, "name") or str(result["source"]).rstrip("/").split("/")[-1]
        result["description"] = field_of(frontmatter, "description")

    threshold = config.get("hit_threshold")
    limit = float(threshold) if isinstance(threshold, (int, float)) else None
    if limit is not None:
        results = [result for result in results if float(result["score"]) >= limit]

    return results, len(items), limit


def print_results(
    query: str,
    results: list[dict[str, Any]],
    total: int,
    threshold: float | None,
) -> None:
    """终端里打印命中的 skill 描述和目录."""
    print(f"\n查询: {query}")
    print(f"索引 {total} 个 skill" + (f"   阈值 {threshold}" if threshold is not None else ""))
    if not results:
        print("  没有命中的 skill")
        return
    for result in results:
        print("-" * 64)
        print(f"[{result['rank']}] 相似度 {result['score']:.4f}   {result['name']}")
        print(f"    目录: {result['source']}")
        print(f"    描述: {result['description'] or '(frontmatter 里没写 description)'}")
    print("-" * 64)


def run_once(
    query: str,
    config: dict[str, Any],
    model_info: dict[str, str],
    top_k: int,
    as_json: bool,
) -> None:
    results, total, threshold = find(query, config, model_info, top_k)
    if as_json:
        print(json.dumps({
            "query": query,
            "hit": bool(results),
            "threshold": threshold,
            "results": results,
        }, ensure_ascii=False, indent=2))
    else:
        print_results(query, results, total, threshold)


def main() -> None:
    parser = argparse.ArgumentParser(description="给一句话, 找出该用哪个 skill")
    parser.add_argument("query", nargs="?", default="", help="留空进交互模式")
    parser.add_argument("-n", "--top-k", type=int, default=0, help="返回几条 (默认读配置)")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    config = load_config()
    model_info = resolve_model()
    top_k = args.top_k or int(config.get("top_k", 3))

    if args.query.strip():
        run_once(args.query.strip(), config, model_info, top_k, args.json)
        return

    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/exit", "/quit"):
            break
        run_once(line, config, model_info, top_k, args.json)


if __name__ == "__main__":
    main()

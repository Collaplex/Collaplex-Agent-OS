#!/usr/bin/env python3
"""扫 skill 目录, 把每个 skill 的 SKILL.md frontmatter 做成一条索引.

语料 = frontmatter 原文 (里面必有 description, 那正是"这个 skill 是干什么的").
一个 skill 一条, 不切片. 每次全量重建, 语料就这几个, 免得留残片.

跑法:
    .venv/bin/python skill/skill_search/scripts/index_skills.py
    .venv/bin/python skill/skill_search/scripts/index_skills.py --json
前提: 向量服务起着 (scripts/embed_server.sh start)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from core import (  # noqa: E402  (必须先插 sys.path 再导入)
    embed_texts,
    index_path,
    load_config,
    load_items,
    rel_source,
    resolve_model,
    skill_root,
    text_hash,
    write_items,
)

FENCE = "---"


def read_frontmatter(doc: Path) -> str:
    """取 SKILL.md 开头 --- ... --- 之间的 YAML 原文; 没有就返回空串."""
    lines = doc.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != FENCE:
        return ""
    for position in range(1, len(lines)):
        if lines[position].strip() == FENCE:
            return "\n".join(lines[1:position]).strip()
    return ""


def scan_skills(root: Path, exclude: set[str]) -> list[dict[str, str]]:
    """找 root 下每个子目录里的 SKILL.md (大小写都认), 抽出 frontmatter."""
    found: list[dict[str, str]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name in exclude:
            continue
        doc = next(
            (
                path
                for path in sorted(child.iterdir())
                if path.is_file() and path.name.lower() == "skill.md"
            ),
            None,
        )
        if doc is None:
            print(f"[跳过] {child.name}: 目录里没有 SKILL.md")
            continue
        frontmatter = read_frontmatter(doc)
        if not frontmatter:
            print(f"[跳过] {child.name}: SKILL.md 没有 frontmatter")
            continue
        found.append({
            "name": child.name,
            "text": frontmatter,
            "source": rel_source(child),
        })
    return found


def build(entries: list[dict[str, str]], config: dict[str, Any], model_info: dict[str, str]) -> list[dict[str, Any]]:
    """每个 skill 一条; frontmatter 没变的直接复用旧向量, 不打模型."""
    existing = {str(item["source"]): item for item in load_items(index_path(config))}

    fresh: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    for entry in entries:
        item: dict[str, Any] = {
            "index": 0,
            "text": entry["text"],
            "hash": text_hash(entry["text"]),
            "source": entry["source"],
        }
        old = existing.get(entry["source"])
        if old is not None and str(old["hash"]) == item["hash"]:
            item["vector"] = old["vector"]
            print(f"  [复用] {entry['name']}")
        else:
            pending.append(item)
            print(f"  [待算] {entry['name']}")
        fresh.append(item)

    batch_size = int(config["batch_size"])
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        vectors = embed_texts([str(item["text"]) for item in batch], config, model_info)
        for item, vector in zip(batch, vectors):
            item["vector"] = vector

    return fresh


def main() -> None:
    parser = argparse.ArgumentParser(description="扫 skill 目录, 建/刷新 skill 索引")
    parser.add_argument("--json", action="store_true", help="只输出 JSON 摘要")
    args = parser.parse_args()

    config = load_config()
    root = skill_root(config)
    if not root.is_dir():
        raise SystemExit(f"[错误] skill 目录不存在: {root}")

    exclude = {str(name) for name in config.get("exclude_dirs", [])}
    entries = scan_skills(root, exclude)
    if not entries:
        raise SystemExit(f"[错误] {root} 下没扫到带 frontmatter 的 skill")

    model_info = resolve_model()
    if not args.json:
        print(f"[扫到] {len(entries)} 个 skill @ {root}")

    fresh = build(entries, config, model_info)
    path = index_path(config)
    write_items(path, fresh, model_info["model"], model_info["endpoint"])

    if args.json:
        print(json.dumps({
            "root": str(root),
            "index": str(path),
            "count": len(fresh),
            "skills": [{"name": e["name"], "source": e["source"]} for e in entries],
        }, ensure_ascii=False, indent=2))
        return

    print(f"[落盘] {path}")
    print(f"[完成] {len(fresh)} 条, {len(fresh[0]['vector'])} 维")


if __name__ == "__main__":
    main()

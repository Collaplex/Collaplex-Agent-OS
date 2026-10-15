# -*- coding: utf-8 -*-
"""把老 JSON 索引搬进 PG —— 今早(2026-10-08)的迁移只写了代码, 库还没落地。

只搬迁现成的向量(不重新嵌入, 不重算), 幂等: 表用 UNIQUE(tier, hash) 兜重, 重复跑没有副作用。

  tier=2 热  <= scripts/vector-index.json   (11.5MB)
  tier=3 冷  <= scripts/memory-index.json   ( 7.3MB)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

脚本目录 = Path(__file__).resolve().parent
sys.path.insert(0, str(脚本目录))

import refine  # noqa: E402  (rag_config() 在它那儿)
import store  # noqa: E402

SRC = 脚本目录 / "_json-retired-backup"
要迁 = [("2", "vector-index.json", "二层·热"), ("3", "memory-index.json", "三层·冷")]


def main() -> int:
    配置: dict[str, Any] = refine.rag_config()
    if not store.is_pg(配置):
        print(f"✗ 后端不是 pg, 是 {store.store_config(配置).get('backend')!r} —— 先看 resources/embed.json 的 store 段")
        return 1
    表 = store.table_name(配置)
    print(f"目标表: {表}\n")

    总 = 0
    for tier, 名, 说明 in 要迁:
        路径 = SRC / 名
        if not 路径.is_file():
            print(f"  [tier={tier}] {说明}: 找不到 {路径} ✗")
            continue
        try:
            条数 = store.migrate_from_json(配置, tier, 路径)
        except Exception as exc:  # noqa: BLE001  —— 迁移出错要看清, 不吞
            print(f"  [tier={tier}] {说明}: 失败 ✗ {type(exc).__name__}: {exc}")
            continue
        print(f"  [tier={tier}] {说明}: 写入 {条数} 条 ✓  (源 {路径.name} {路径.stat().st_size / 1e6:.1f}MB)")
        总 += 条数

    print()
    with store.connect(配置) as conn:
        for tier, 名, 说明 in 要迁:
            现有 = store.count(conn, 配置, tier)
            print(f"  库里 tier={tier} {说明}: {现有} 条")
    print(f"\n本次共写入 {总} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

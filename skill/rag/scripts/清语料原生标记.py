#!/usr/bin/env python3
"""清语料与热库里模型遗留的工具调用标记 —— 一次性修 (2026-10-09).

为什么要有它
    DeepSeek 接手主线后, 它吐的原生 DSML 标记(全角竖线夹 DSML)会随产出落进语料,
    检索再把它取回上下文 -> 模型看见自己的标记就跟着模仿 -> 污染自我扩散。
    写入口已经堵上了(sub_agent 落语料 / import_hermes_hist 导会话都过 native_marks.strip_all_calls);
    这个脚本负责把**已经躺进去的那批**清掉:
      ① 语料文件: 摘掉标记(原文先备份到 .backup/)
      ② 热库(rag_chunks): 重写 text + 重算 hash + 重算向量 —— 不重算的话向量跟正文就对不上账了

跑法:
    .venv/bin/python skill/rag/scripts/清语料原生标记.py --干跑    # 只看要动哪些, 一条不改
    .venv/bin/python skill/rag/scripts/清语料原生标记.py           # 真清
★ 语料/热库是数据不是代码 —— 跑之前先 --干跑 查看。
★ 不要改这里的库名/表名: 库.py 会自动挂 COLLAPLEX_DB_PREFIX 沙盒前缀。
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from psycopg import sql

HERE = Path(__file__).resolve().parent          # skill/rag/scripts
根 = HERE.parents[2]                            # 项目根
sys.path.insert(0, str(根))
sys.path.insert(0, str(HERE))

import native_marks  # noqa: E402
import 库  # noqa: E402
from embed import request_vectors, resolve_model  # noqa: E402  (复用同一套向量调用)

load_dotenv(根 / ".env")

语料目录 = 根 / "skill" / "rag" / "corpus"
备份根 = 根 / ".backup" / f"语料原生标记-{datetime.now():%Y%m%d-%H%M%S}"
表名 = "rag_chunks"


def 扫语料(干跑: bool) -> int:
    """摘掉语料文件里的**别家原生**标记; 命中几个报几个, 原文先备份.

    ★ 只动别家的(DSML / MiMo)—— 自家的 `<调用>` 在语料里是活例子, 留着。
    """
    命中 = 0
    for 路径 in sorted(语料目录.rglob("*.md")):
        原文 = 路径.read_text(encoding="utf-8")
        if not native_marks.has_native_marker(原文):
            continue
        清过 = native_marks.strip_native_markers(原文)
        if 清过 == 原文:
            # 只是正文里"提到"了 DSML 这个词(比如分析 tokenizer 的任务), 没有真标记 —— 不动
            continue
        print(f"  [语料] {路径.relative_to(根)}  {len(原文)} -> {len(清过)} 字符")
        命中 += 1
        if 干跑:
            continue
        备份 = 备份根 / 路径.relative_to(语料目录)
        备份.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(路径, 备份)
        路径.write_text(清过 + "\n", encoding="utf-8")
    return 命中


def 清热库(干跑: bool) -> int:
    """重写热库里的脏块: 正文清干净 + hash 重算 + 向量重算(三者必须一起动)."""
    表 = sql.Identifier(库.表名(表名))
    模式 = tuple(f"%{针}%" for 针 in native_marks.COARSE_NEEDLES)
    条件 = sql.SQL(" OR ").join([sql.SQL("text LIKE %s")] * len(模式))
    行们 = 库.查(
        sql.SQL("SELECT id, tier, text FROM {} WHERE ").format(表) + 条件,
        模式,
    )
    print(f"  [热库] {库.表名(表名)} 粗筛命中 {len(行们)} 条")

    待办: list[tuple[Any, Any, str, str]] = []
    for 行号, 层级, 正文 in 行们:
        原文 = str(正文)
        清净 = native_marks.strip_native_markers(原文)
        if 清净 == 原文:
            # 只是"提到"了 DSML 这个词, 没有真标记 —— 别为了改而改(会连向量一起白算)
            continue
        待办.append((行号, 层级, 原文, 清净.strip()))
    print(f"  真要动 {len(待办)} 条")
    if 干跑:
        for 行号, 层级, 原文, 清过 in 待办:
            print(f"    id={行号} tier={层级}  {len(原文)} -> {len(清过)} 字符")
        return len(待办)
    if not 待办:
        return 0

    模型 = resolve_model()
    配置 = {"retry": 3, "timeout": 60}
    动了 = 0
    for 行号, 层级, 原文, 清过 in 待办:
        if not 清过:
            # 整条就是一段标记, 清完是空的 —— 留着只会继续污染, 删掉(语料那边已清, 重洗会重建)
            库.执行(sql.SQL("DELETE FROM {} WHERE id = %s").format(表), (行号,))
            print(f"    id={行号} tier={层级}  清完为空 -> 删行")
            动了 += 1
            continue
        向量 = request_vectors([清过], 配置, 模型)[0]
        摘要 = hashlib.sha256(清过.encode("utf-8")).hexdigest()[:16]
        字面 = "[" + ",".join(str(float(值)) for 值 in 向量) + "]"
        库.执行(
            sql.SQL("UPDATE {} SET text = %s, hash = %s, embedding = %s::vector WHERE id = %s").format(表),
            (清过, 摘要, 字面, 行号),
        )
        print(f"    id={行号} tier={层级}  {len(原文)} -> {len(清过)} 字符, 向量重算")
        动了 += 1
    return 动了


def main() -> int:
    ap = argparse.ArgumentParser(description="清语料与热库里的工具调用标记")
    ap.add_argument("--干跑", action="store_true", help="只列要动哪些, 不改任何东西")
    args = ap.parse_args()

    print(f"语料目录: {语料目录}")
    print(f"备份到:   {备份根 if not args.干跑 else '(干跑不备份)'}")
    print("\n① 语料文件")
    语料数 = 扫语料(args.干跑)
    print(f"  命中 {语料数} 个文件")
    print("\n② 热库")
    热库数 = 清热库(args.干跑)
    print(f"  处理 {热库数} 条")
    print(f"\n{'[干跑] ' if args.干跑 else ''}完成: 语料 {语料数} 个文件 / 热库 {热库数} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

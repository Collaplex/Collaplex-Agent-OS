#!/usr/bin/env python3
"""清洗的"失败即停"闸门 —— 模型问不出来时必须**退避重试**, 试满就**全线停**, 绝不写空账。

★ 为什么要有这道测试(2026-10-11 已踩坑): 本地主模型 :8790 掉线那阵, cron 起的清洗把
  "概述 0 / 知识 0" 空账一路写进三层 —— 而且旧概述是在写新的那一步先被删掉的,
  等于越洗越少; 更狠的是跑完还会执行第③步(清二层 + 删语料原文), 原文一删就补不回来。
  想让它在无人值守(每分钟 cron)下安全, 只有两条: 失败重试到成功; 实在不行就当场停住。

跑法: ./.venv/bin/python tests/test_refine_fail_fast.py
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

项目根 = Path("/home/lou/桌面/collaplex_agent")
sys.path.insert(0, str(项目根))
sys.path.insert(0, str(项目根 / "skill" / "rag" / "scripts"))

import refine  # noqa: E402


def 判据(名: str, 通过: bool, 说明: str = "") -> bool:
    print(f"  {'✓' if 通过 else '✗'} {名}" + (f"   {说明}" if 说明 else ""))
    return 通过


def 搭台(目录: Path) -> None:
    """把三层/别名/状态都指到临时目录, 并断掉 PG —— 绝不碰老板的生产库。"""
    脚本 = 目录 / "scripts"
    语料 = 目录 / "corpus"
    状态 = 目录 / "state"
    for 一个 in (脚本, 语料, 状态):
        一个.mkdir(parents=True, exist_ok=True)
    refine.ROOT = 目录
    refine.CORPUS_DIR = 语料
    refine.STATE_DIR = 状态
    refine.TIER2_PATH = 脚本 / "vector-index.json"
    refine.TIER3_PATH = 脚本 / "memory-index.json"
    refine.ALIAS_PATH = 脚本 / "alias.json"
    refine.PENDING_PATH = 状态 / "refine-待重洗.json"
    refine.HEARTBEAT_PATH = 状态 / "refine-心跳.json"
    refine.store.is_pg = lambda _cfg: False
    refine.embed = lambda _text: [0.0] * 1024


def 灌一批() -> str:
    """造一个来源: 语料文件 + 它对应的二层切片。返回来源路径。"""
    文件 = refine.CORPUS_DIR / "q-测试.md"
    文件.write_text("# 测试\n\n一问一答", encoding="utf-8")
    条目 = [
        {
            "index": i,
            "vector": [0.0] * 1024,
            "text": f"第 {i} 片",
            "hash": f"h{i}",
            "source": str(文件),
            "kind": "原文",
        }
        for i in range(2)
    ]
    refine.save_index(refine.TIER2_PATH, {"meta": {}, "items": 条目})
    return str(文件)


def 断路由() -> dict[str, int]:
    """PG 相关的两处出口都拿掉: 一段不查库、一轮不真清。"""
    refine.copy_to_history = lambda _groups: 0
    清过: dict[str, int] = {"清": 0, "记账": 0}
    refine.clear_tier2 = lambda _洗过: (清过.__setitem__("清", 清过["清"] + 1), (0, 0))[1]
    refine.note_refined = lambda: 清过.__setitem__("记账", 清过["记账"] + 1)
    return 清过


def 主() -> int:
    通过: list[bool] = []
    refine.重试基隔 = 0.01          # 测试里别真等 3/6/12 秒
    refine.重试上限 = 4

    with tempfile.TemporaryDirectory() as 临时:
        搭台(Path(临时))
        源 = 灌一批()

        # ── 用例 A: 前两次掉线, 第三次成功 —— 必须重试到成功, 且不许写成空账
        次数 = {"概述": 0}

        def 假模型(system_prompt: str, _content: str) -> Any:
            if "概述" in system_prompt:
                次数["概述"] += 1
                if 次数["概述"] <= 2:
                    raise RuntimeError("模拟模型掉线")
                return {"概述": "洗出来了"}
            if "知识" in system_prompt:
                return {"知识": ["知识甲"]}
            return {"概念": []}

        refine.ask_model = 假模型
        refine.重试上限 = 4
        结果 = refine.clean_one(源, "材料内容")
        通过.append(判据("掉线两次后重试成功", 结果["概述"] == 1, f"概述={结果['概述']}"))
        通过.append(判据("确实试了 3 次(2 败 1 成)", 次数["概述"] == 3, f"实际 {次数['概述']} 次"))
        通过.append(判据("知识照旧落下来", 结果["知识"] == 1, f"知识={结果['知识']}"))

        # ── 用例 B: 一直掉线 —— 问稳 试满上限就抛 全线停(不是静默返回 None)
        def 全炸(_system_prompt: str, _content: str) -> Any:
            raise RuntimeError("模型就是不在")

        refine.ask_model = 全炸
        试了 = {"n": 0}

        def 数着炸(system_prompt: str, content: str) -> Any:
            试了["n"] += 1
            return 全炸(system_prompt, content)

        refine.ask_model = 数着炸
        抛了 = False
        try:
            refine.问稳("概述 的提示词", "材料")
        except refine.全线停:
            抛了 = True
        通过.append(判据("试满上限抛全线停", 抛了))
        通过.append(判据("试的次数 = 上限", 试了["n"] == refine.重试上限, f"实际 {试了['n']} 次"))

        # ── 用例 C: 一轮跑到 全线停 —— 不许执行第③步(清二层/删语料)
        清过: dict[str, int] = 断路由()
        三层前 = len(json.loads(refine.TIER3_PATH.read_text(encoding="utf-8"))["items"])
        refine.文件并发度 = 1
        缓冲 = io.StringIO()
        with contextlib.redirect_stdout(缓冲), contextlib.redirect_stderr(缓冲):
            refine.run_once(quiet=True)
        日志 = 缓冲.getvalue()
        通过.append(判据("日志里明写全线停", "全线停" in 日志))
        通过.append(判据("③ 一次都没执行", 清过["清"] == 0, f"clear_tier2 调了 {清过['清']} 次"))
        通过.append(判据("没记'洗过了'", 清过["记账"] == 0, f"note_refined 调了 {清过['记账']} 次"))
        二层 = json.loads(refine.TIER2_PATH.read_text(encoding="utf-8"))["items"]
        通过.append(判据("二层原样留着", len(二层) == 2, f"实际 {len(二层)} 片"))
        通过.append(判据("语料原文还在", Path(源).is_file()))
        三层 = json.loads(refine.TIER3_PATH.read_text(encoding="utf-8"))["items"]
        通过.append(判据("三层一条空账都没加", len(三层) == 三层前, f"停前 {三层前} 条 → 停后 {len(三层)} 条"))

    print(f"\n{sum(通过)}/{len(通过)} 过")
    return 0 if all(通过) else 1


if __name__ == "__main__":
    raise SystemExit(主())

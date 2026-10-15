#!/usr/bin/env python3
"""跨文件并发清洗不许丢结果 —— 三层是"读全部-改-写全部", 并发时后写的会把先写的覆盖。

★ 为什么必须有这道测试: 加 --并发文件 之前, 清洗是**一个文件一个文件**走的, 谁也碰不到谁;
  一旦多个文件同时在飞, clean_one 里那段"读三层 → 改 → 写回"就会互相覆盖 ——
  表现是**静默丢概述/知识**(一条错都不报), 只能靠数条数发现。
★ 这里绕开 PG: 把 store.is_pg 钉成 False, 三层/别名表全走临时目录的 JSON,
  绝不碰老板的生产库(生产库此刻还在被真清洗写着)。

跑法:
    .venv/bin/python tests/test_refine_concurrent_files.py          # 该全过
    .venv/bin/python tests/test_refine_concurrent_files.py --无锁   # 交掉锁, 应当成片丢(证明这道测试有牙)
"""

from __future__ import annotations

import io
import json
import random
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "skill" / "rag" / "scripts"))

import refine  # noqa: E402

份数 = 8


def 判据(名字: str, 通过: bool, 说明: str = "") -> bool:
    print(f"  {'✓' if 通过 else '✗'} {名字}" + (f"   {说明}" if 说明 else ""))
    return 通过


def 慢假模型(system_prompt: str, content: str) -> Any:
    """假模型: 形状对就行, 但要**慢且抖动** —— 不然几个文件根本重叠不上, 测不出竞态。"""
    time.sleep(random.uniform(0.05, 0.3))
    if "概述" in system_prompt:
        return {"概述": f"概述 {content[:16]}"}
    if "知识" in system_prompt:
        return {"知识": ["知识一", "知识二"]}
    if "别名" in system_prompt:
        条目: dict[str, Any] = {"概念": "内存条", "别名": ["DIMM"], "语境": "说内存时", "上位": ["内存条规格"]}
        return {"概念": [条目]}
    return {}


def 慢索引(延时: float) -> tuple[Any, Any]:
    """把 load_index/save_index 各垫一点延时 —— 读-改-写这个窗口得够宽, 否则并发根本撞不上,
    竞态会被"太快了"掩盖(实测: 不加延时, 交掉锁也一条不丢, 测了个寂寞)。"""
    原读, 原写 = refine.load_index, refine.save_index

    def 读(path: Path) -> dict[str, Any]:
        time.sleep(延时)
        return 原读(path)

    def 写(path: Path, pack: dict[str, Any]) -> None:
        time.sleep(延时)
        原写(path, pack)

    return 读, 写


def 搭台(目录: Path) -> None:
    """路径全指临时目录; 模型换假的; ★ 同时把 PG 关掉(见文件头)。"""
    scripts = 目录 / "scripts"
    corpus = 目录 / "corpus"
    state = 目录 / "state"
    for one in (scripts, corpus, state):
        one.mkdir(parents=True, exist_ok=True)
    refine.TIER2_PATH = scripts / "vector-index.json"
    refine.TIER3_PATH = scripts / "memory-index.json"
    refine.ALIAS_PATH = scripts / "alias.json"
    refine.PENDING_PATH = state / "refine-待重洗.json"
    refine.HEARTBEAT_PATH = state / "refine-心跳.json"
    refine.CORPUS_DIR = corpus
    refine.STATE_DIR = state
    refine.store.is_pg = lambda _cfg: False          # 三层/别名走 JSON, 不碰生产库
    refine.ask_model = 慢假模型
    refine.embed = lambda _text: [0.0] * 1024
    refine.load_index, refine.save_index = 慢索引(0.04)   # 把读改写窗口撑开, 竞态才撞得上


def main() -> int:
    无锁 = "--无锁" in sys.argv
    结果: list[bool] = []
    with tempfile.TemporaryDirectory() as tmp:
        搭台(Path(tmp))
        if 无锁:   # 交掉锁 = 故意回到"会互相顶掉"的老样子, 用来验这道测试真能抓到
            refine.索引锁 = __import__("contextlib").nullcontext()  # type: ignore[assignment]
        refine.TIER3_PATH.write_text(json.dumps({"meta": {}, "items": []}, ensure_ascii=False), encoding="utf-8")
        refine.ALIAS_PATH.write_text(json.dumps({"meta": {}, "items": []}, ensure_ascii=False), encoding="utf-8")

        材料: dict[str, str] = {}
        for i in range(份数):
            材料[str(refine.CORPUS_DIR / f"q-{i:02d}.md")] = f"第 {i} 份原文, 内容各不相同 {i}"

        缓冲 = io.StringIO()
        with redirect_stdout(缓冲):
            with ThreadPoolExecutor(max_workers=6) as 池:
                在飞 = [池.submit(refine.clean_one, 源, 文) for 源, 文 in 材料.items()]
                for 期货 in as_completed(在飞):
                    期货.result()

        pack: dict[str, Any] = json.loads(refine.TIER3_PATH.read_text(encoding="utf-8"))
        概述 = [x for x in pack["items"] if x.get("kind") == "概述"]
        知识 = [x for x in pack["items"] if x.get("kind") == "知识"]
        别名 = json.loads(refine.ALIAS_PATH.read_text(encoding="utf-8"))["items"]
        结果.append(判据(f"{份数} 条概述一条不少", len(概述) == 份数, f"实际 {len(概述)}"))
        结果.append(判据(f"{份数 * 2} 条知识一条不少", len(知识) == 份数 * 2, f"实际 {len(知识)}"))
        结果.append(判据("概述覆盖到每一份", len({x.get("source") for x in 概述}) == 份数,
                          f"覆盖 {len({x.get('source') for x in 概述})} 份"))
        结果.append(判据("别名表还在", len(别名) >= 1, f"{len(别名)} 条"))
        结果.append(判据("没有半截 JSON", isinstance(pack.get("items"), list)))

    print(f"\n{sum(结果)}/{len(结果)} 过" + ("  (--无锁 下就该丢, 丢=测试有牙)" if 无锁 else ""))
    return 0 if all(结果) else 1


if __name__ == "__main__":
    raise SystemExit(main())

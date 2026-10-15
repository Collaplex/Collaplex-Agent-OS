#!/usr/bin/env python3
"""清洗兜底回归 —— 语料文件没了, 那批不能算"洗过了"(实测已踩坑 6 轮).

背景(实测, logs/refine.log 有 6 轮这个样子):

    ② 再清洗 —— 概述 / 知识 / 别名
        skill/rag/corpus/q-ca1903f3.md: 读不到语料原文, 跳过清洗(原文已进三层, 不丢)
    完成: 原文 2 片 / 概述 0 条 / 知识 0 条 / 别名 0 组

原文是进了三层, 却一条概述/知识/别名都没洗出来 —— 没重试、没账, 等于永久半成品。
落地证据: 三层 memory-index.json 里"有原文、没概述"的 source **5 个 22 片**,
名字是 q-ca1903f3 / q-d17d0ae4 / q-d457aaee / q-28eafa2d / q-56ee0409,
跟日志里那几轮**一一对上**。

这里的规矩:
  ① 搬运是"一字不改"的 → **历史对话层(tier=1)** 那批切片就是原文 —— 文件没了就用它回填着洗
     (老账本里 kind='原文' 是这一层的遗留写法, history_raw 两个都认)
  ② 两边都空才记进 state/refine-待重洗.json, 不许静默当"洗过了"
  ③ 历史对话层有原文、经验层(tier=3)没概述的旧半成品, 用 --回填 收尾

测试方法: 模型和嵌入都换成假的(不打网络、不花钱), 索引/语料/状态全在临时目录里,
**存储后端也钉在 JSON 文件上**(见 搭台) —— 真身是 PG, 但这里考的是搬运/回填的逻辑,
连库只是在测 PostgreSQL 的行列约束, 跟被考的代码没关系。

跑法: .venv/bin/python tests/test_refine_fallback.py
"""

from __future__ import annotations

import contextlib
import io
import json
import random
import sys
import tempfile
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "skill" / "rag" / "scripts"))

import refine  # noqa: E402


def 判据(名字: str, 通过: bool, 说明: str = "") -> bool:
    print(f"  {'✓' if 通过 else '✗'} {名字}" + (f"   {说明}" if 说明 else ""))
    return 通过


def 假模型(system_prompt: str, content: str) -> Any:
    """假模型: 只看提示词要哪类产出, 给固定形状的答案(内容不重要, 形状对就行)。"""
    if "概述" in system_prompt:
        return {"概述": "这一次问答的概述"}
    if "知识" in system_prompt:
        return {"知识": ["知识一", "知识二"]}
    if "别名" in system_prompt:
        空: list[str] = []
        条目: dict[str, Any] = {"概念": "内存条", "别名词": "DIMM", "语境": "说内存时", "上位": 空}
        return {"概念": [条目]}
    return {}


def 假嵌入(text: str) -> list[float]:
    """假嵌入: 测试不看相似度, 只要求不要去打网络。"""
    return [0.0] * 8


@contextlib.contextmanager
def 假连接(_配置: dict[str, Any]) -> Generator[Any]:
    """假的 store 连接 —— 用例一个字节都不写真库。"""
    yield None


def 假记历史(_conn: Any, _配置: dict[str, Any], items: list[dict[str, Any]]) -> int:
    """照 store.append_history 的语义(按 source 先删后插)落到临时 tier=1 的文件上。

    ★ ① 搬运这一步就是这么进历史对话层的 —— 落不进这一层, ② 的回填就无从谈起。
    """
    if not items:
        return 0
    本层 = cast(list[dict[str, Any]], refine.load_index(refine.TIER1_PATH).get("items") or [])
    来源们 = {str(条.get("source", "")) for 条 in items}
    留 = [条 for 条 in 本层 if str(条.get("source", "")) not in 来源们]
    refine.save_index(refine.TIER1_PATH, {"meta": {}, "items": 留 + items})
    return len(items)


def 不是库(_配置: dict[str, Any]) -> bool:
    return False


def 不用建表(_conn: Any, _配置: dict[str, Any], _维: int) -> None:
    return None


def 没有指针(_conn: Any, _配置: dict[str, Any]) -> dict[str, str]:
    return {}


def 不许碰库(*_参数: Any, **_开关: Any) -> Any:
    raise AssertionError("这个用例不该走数据库后端 —— is_pg 应该被钉成 False")


def 搭台(目录: Path) -> None:
    """把 refine 的路径常量指到临时目录; 模型/嵌入换假的, 提示词照读真的。"""
    scripts = 目录 / "scripts"
    corpus = 目录 / "corpus"
    state = 目录 / "state"
    for one in (scripts, corpus, state):
        one.mkdir(parents=True, exist_ok=True)
    refine.ROOT = 目录
    refine.CORPUS_DIR = corpus
    refine.STATE_DIR = state
    refine.TIER1_PATH = scripts / "history-index.json"
    refine.TIER2_PATH = scripts / "vector-index.json"
    refine.TIER3_PATH = scripts / "memory-index.json"
    refine.ALIAS_PATH = scripts / "alias.json"
    refine.PENDING_PATH = state / "refine-待重洗.json"
    refine.HEARTBEAT_PATH = state / "refine-心跳.json"
    refine.ask_model = 假模型
    refine.embed = 假嵌入
    # ★★ 把存储后端钉死在"JSON 文件"上(2026-10-11 修): 二层/三层的真身已经是 PG
    #     (vector(1024)), 而 force-JSON 之前这里塞的是 8 维假向量 → 一上来就
    #     psycopg.errors.DataException: expected 1024 dimensions, not 8, 整份用例从第一条起全红。
    #     这些用例考的是"语料文件没了拿什么回填", 跟数据库的维度/列约束无关 ——
    #     该钉后端, 不是把假向量改成 1024 维去迎合库。
    refine.store.is_pg = 不是库
    refine.store.connect = 假连接
    refine.store.ensure_schema = 不用建表
    refine.store.append_history = 假记历史
    refine.store.ids_by_source = 没有指针
    refine.store.upsert = 不许碰库
    refine.store.load_existing = 不许碰库


def 灌二层(来源: Path, 片数: int = 2, 原文: str = "第 {n} 片原文") -> None:
    """往二层塞一批"对话产出" —— source 指 corpus 底下的文件, 磁盘上有没有另说。"""
    items = [
        {
            "index": i,
            "vector": [0.0] * 8,
            "text": 原文.format(n=i + 1),
            "hash": f"h{i}",
            "source": str(来源),
            "kind": "原文",
        }
        for i in range(片数)
    ]
    refine.save_index(refine.TIER2_PATH, {"meta": {}, "items": items})


def 跑(函数: str) -> str:
    """跑一轮, 把 stdout 收回来 —— 日志本身也是判据(不许静默)。"""
    缓冲 = io.StringIO()
    with contextlib.redirect_stdout(缓冲):
        if 函数 == "run_once":
            refine.run_once(quiet=True)
        else:
            refine.backfill(quiet=True)
    return 缓冲.getvalue()


def 摆历史(来源: Path, 片数: int = 2, 原文: str = "第 {n} 片原文") -> None:
    """往**历史对话层**(tier=1)摆一批原文 —— 原文就住这一层, ② 的回填从这里来。

    ★ 用 kind='对话'(① 搬运写在那一层的写法); 老账本里的 kind='原文' 一并认。
    """
    items = [
        {
            "index": i,
            "vector": [0.0] * 8,
            "text": 原文.format(n=i + 1),
            "hash": f"h{i}",
            "source": str(来源),
            "kind": "对话",
        }
        for i in range(片数)
    ]
    refine.save_index(refine.TIER1_PATH, {"meta": {}, "items": items})


def 三层分类() -> dict[str, list[dict[str, Any]]]:
    pack = json.loads(refine.TIER3_PATH.read_text(encoding="utf-8"))
    按类: dict[str, list[dict[str, Any]]] = {}
    for item in pack["items"]:
        按类.setdefault(str(item["kind"]), []).append(item)
    return 按类


def 一层片数() -> int:
    """历史对话层里现在有几片 —— \"原文不丢\"那条断言看这个。"""
    pack = json.loads(refine.TIER1_PATH.read_text(encoding="utf-8"))
    return len(cast(list[Any], pack.get("items") or []))


def 账本() -> dict[str, Any]:
    if not refine.PENDING_PATH.is_file():
        return {}
    return dict(json.loads(refine.PENDING_PATH.read_text(encoding="utf-8")))


def 测_文件在时照旧走文件() -> list[bool]:
    结果: list[bool] = []
    with tempfile.TemporaryDirectory() as tmp:
        搭台(Path(tmp))
        文件 = refine.CORPUS_DIR / "q-aaa.md"
        文件.write_text("# 原文\n\n一问一答的内容", encoding="utf-8")
        灌二层(文件)
        日志 = 跑("run_once")
        类 = 三层分类()
        结果.append(判据("文件在时不当回填办", "历史对话回填" not in 日志))
        结果.append(判据(
            "概述/知识 都进了三层",
            len(类.get("概述", [])) == 1 and len(类.get("知识", [])) == 2,
            说明=f"(概述 {len(类.get('概述', []))} / 知识 {len(类.get('知识', []))})",
        ))
        结果.append(判据("日志开头有时间戳", 日志.startswith("["), 说明=f"(首行 {日志[:22]!r})"))
        结果.append(判据("收尾带耗时", "耗时" in 日志))
        结果.append(判据("心跳落盘", refine.HEARTBEAT_PATH.is_file()))
        结果.append(判据("没记待重洗", 账本() == {}))
    return 结果


def 测_文件没了拿历史对话层回填() -> list[bool]:
    """★ 核心: 实测那 6 轮就是这么坏的 —— 现在得洗得出来。

    ★ 语料文件被上一轮 ③ 删掉的情形: ① 已经把切片原样搬进历史对话层(tier=1),
      ② 读不到文件就回那一层取 —— 这是本用例唯一要证的事。
    """
    结果: list[bool] = []
    with tempfile.TemporaryDirectory() as tmp:
        搭台(Path(tmp))
        来源 = refine.CORPUS_DIR / "q-ca1903f3.md"  # 实测那批里的名字
        灌二层(来源, 片数=2)                          # 只有索引, 磁盘上没这个文件
        日志 = 跑("run_once")
        类 = 三层分类()
        结果.append(判据("日志认出走的是回填", "从历史对话回填清洗" in 日志))
        结果.append(判据("★ 回填洗出了概述", len(类.get("概述", [])) == 1))
        结果.append(判据("★ 回填洗出了知识", len(类.get("知识", [])) == 2))
        结果.append(判据("原文片还在历史对话层(不丢)", 一层片数() == 2, 说明=f"(tier=1 有 {一层片数()} 片)"))
        结果.append(判据("这轮没记待重洗", 账本() == {}))
    return 结果


def 测_两边都空才记账() -> list[bool]:
    结果: list[bool] = []
    with tempfile.TemporaryDirectory() as tmp:
        搭台(Path(tmp))
        来源 = refine.CORPUS_DIR / "q-yyy.md"
        灌二层(来源, 片数=1, 原文="")  # 文件不在, 三层这批原文也是空的
        日志 = 跑("run_once")
        账 = 账本()
        结果.append(判据("记进了待重洗", len(账) == 1, 说明=f"(账上 {len(账)} 个)"))
        结果.append(判据(
            "账里有片数/首次/原因",
            bool(账) and all(key in next(iter(账.values())) for key in ("片数", "首次发现", "原因")),
        ))
        结果.append(判据("日志明说了(不静默)", "记进待重洗" in 日志))
    return 结果


def 测_洗成之后从账本划掉() -> list[bool]:
    结果: list[bool] = []
    with tempfile.TemporaryDirectory() as tmp:
        搭台(Path(tmp))
        来源 = refine.CORPUS_DIR / "q-zzz.md"
        灌二层(来源, 片数=1, 原文="")
        跑("run_once")
        记上了 = len(账本()) == 1
        灌二层(来源, 片数=2)  # 原文回来了(三层这批有真文本了)
        跑("run_once")
        结果.append(判据("先把账记上", 记上了))
        结果.append(判据("洗成之后划掉", 账本() == {}, 说明=f"(洗完剩 {len(账本())} 个)"))
    return 结果


def 测_回填收尾旧半成品() -> list[bool]:
    结果: list[bool] = []
    with tempfile.TemporaryDirectory() as tmp:
        搭台(Path(tmp))
        来源 = refine.CORPUS_DIR / "q-d17d0ae4.md"
        摆历史(来源, 片数=1, 原文="历史对话层里躺着的原文")  # 有原文、经验层没概述 = 半成品
        日志 = 跑("backfill")
        类 = 三层分类()
        结果.append(判据("认出半成品", "回填 1 个半成品" in 日志))
        结果.append(判据("★ 补出了概述", len(类.get("概述", [])) == 1))
        结果.append(判据("补出了知识", len(类.get("知识", [])) == 2))
        结果.append(判据("再跑一遍没事干了", refine.stale_sources() == {}))
    return 结果


def 测_两个新开关从命令行走得通() -> list[bool]:
    结果: list[bool] = []
    with tempfile.TemporaryDirectory() as tmp:
        搭台(Path(tmp))
        来源 = refine.CORPUS_DIR / "q-d457aaee.md"
        摆历史(来源, 片数=1, 原文="历史对话层里躺着的原文")
        老argv = sys.argv
        try:
            sys.argv = ["refine.py", "--回填", "--安静"]
            缓冲 = io.StringIO()
            with contextlib.redirect_stdout(缓冲):
                refine.main()
            日志 = 缓冲.getvalue()
            sys.argv = ["refine.py", "--待重洗"]
            缓冲2 = io.StringIO()
            with contextlib.redirect_stdout(缓冲2):
                refine.main()
            日志2 = 缓冲2.getvalue()
        finally:
            sys.argv = 老argv
        结果.append(判据("--回填 走命令行能跑", "回填完成" in 日志, 说明=f"({日志.strip()[:34]!r})"))
        结果.append(判据("--待重洗 空账时明说", "待重洗是空的" in 日志2))
    return 结果


def 慢假模型(system_prompt: str, content: str) -> Any:
    """内容敏感 + 随机慢的假模型: 让**完成顺序**与提交顺序不一样。"""
    time.sleep(random.uniform(0.0, 0.20))
    if "概述" in system_prompt:
        return {"概述": f"概述<{content}>"}
    if "知识" in system_prompt:
        return {"知识": [f"知识<{content}>"]}
    条目: dict[str, Any] = {"概念": f"概念<{content}>", "别名词": f"别名<{content}>",
                            "语境": "", "上位": []}
    return {"概念": [条目]}


def 测_并发下段序不乱() -> list[bool]:
    """并发跑三遍时结果必须按**段序**回填 —— 顺序错了概述会拼乱、别名去重顺序会变。

    做法: 同一批段, 并发 1 与并发 8 各跑一次, 两边逐项比对必须完全一致 ——
          顺序错了概述会拼乱、别名去重顺序会变。
    """
    结果: list[bool] = []
    段们 = ["甲" * 3, "乙" * 3, "丙" * 3]
    老模型, 老并发 = refine.ask_model, refine.并发度
    try:
        refine.ask_model = 慢假模型
        refine.并发度 = 1
        串行 = refine.三遍并跑(段们)
        refine.并发度 = 8
        并发 = refine.三遍并跑(段们)
        refine.并发度 = 1
    finally:
        refine.ask_model, refine.并发度 = 老模型, 老并发

    预期概述 = [f"概述<{段}>" for 段 in 段们]
    结果.append(判据("并发 8 与串行逐项一致", 串行 == 并发))
    结果.append(判据("三组结果都按段序对齐",
                     [组["概述"] for 组 in 并发[0]] == 预期概述
                     and [条 for 组 in 并发[1] for 条 in 组["知识"]] == [f"知识<{段}>" for 段 in 段们]
                     and [条["概念"] for 组 in 并发[2] for 条 in 组["概念"]] == [f"概念<{段}>" for 段 in 段们]))
    return 结果


def 测_模型不答就全线停() -> list[bool]:
    """模型**真答不上来** → 退避重试到上限, 然后抛 全线停(不再"当空")。

    ★ 老行为是单条失手就返回 None、其余照回(本用例原来就是这么断言的) —— 那会让这次
      清洗"没有概述/知识", 而三层里那条旧概述已经在写新的时候被删掉了:
      **一次掉线 = 永久少一块**。现在的铁律是失败即停, 由 run_once 停住整轮
      (不写空账、不进 ③), 模型修好后下一轮自己接着洗。
    ★ 把重试基隔调成 0 只验"试满上限就抛", 不真等那 200 多秒的退避。
    """
    结果: list[bool] = []
    老模型, 老并发 = refine.ask_model, refine.并发度
    老上限, 老基隔 = refine.重试上限, refine.重试基隔
    次: list[int] = [0]

    def 老不答(system_prompt: str, content: str) -> Any:
        次[0] += 1
        raise RuntimeError("这条故意失败")

    抛的 = ""
    try:
        refine.ask_model = 老不答
        refine.并发度 = 1
        refine.重试上限 = 3
        refine.重试基隔 = 0.0
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                refine.三遍并跑(["甲" * 3])
        except refine.全线停 as error:
            抛的 = str(error)
    finally:
        refine.ask_model, refine.并发度 = 老模型, 老并发
        refine.重试上限, refine.重试基隔 = 老上限, 老基隔
    结果.append(判据("★ 试满就抛 全线停(不当空)", bool(抛的), 说明=f"({抛的[:44]!r})"))
    结果.append(判据("真试满了上限次", 次[0] == 3, 说明=f"(试了 {次[0]} 次)"))
    return 结果


def 主() -> int:
    print("=" * 100)
    print("清洗兜底回归 —— 语料文件没了, 那批不能算\"洗过了\"")
    print("=" * 100)
    全部: list[bool] = []
    全部 += 测_文件在时照旧走文件()
    全部 += 测_文件没了拿历史对话层回填()
    全部 += 测_两边都空才记账()
    全部 += 测_洗成之后从账本划掉()
    全部 += 测_回填收尾旧半成品()
    全部 += 测_两个新开关从命令行走得通()
    全部 += 测_并发下段序不乱()
    全部 += 测_模型不答就全线停()
    通过 = sum(1 for x in 全部 if x)
    print("\n" + "=" * 100)
    print(f"结果: {通过} 通过 / {len(全部) - 通过} 失败")
    print("=" * 100)
    return 0 if 通过 == len(全部) else 1


if __name__ == "__main__":
    raise SystemExit(主())

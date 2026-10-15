"""双后端对拍 —— 库.py 的 pg 路与 sqlite 路必须一模一样。

★ 为什么要有这个(2026-10-11): 为了让 Windows 包"全自动 + 自带空白表", 库.py 加了
sqlite 后端(标准库自带、单文件、首次跑就建表)。两套实现各写一遍必然漂移 ——
所以这里用同一串动作把两边都跑一次, 逐项对结果, 哪边不一样就是哪边写歪了。

沙盒: 跑 pg 那轮用 `COLLAPLEX_DB_PREFIX=测试_` 前缀建表, 跑完自己删 —— 不碰生产表。
sqlite 那轮用临时文件(COLLAPLEX_DB_FILE), 跑完删文件。

用法: ./.venv/bin/python tests/test_库_双后端.py
"""

from __future__ import annotations

import importlib
import os
import pathlib
import sys
import tempfile
from typing import Any

根 = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(根))

失败: list[str] = []
通过 = 0


def 判(条件: bool, 说明: str) -> None:
    global 通过
    if 条件:
        通过 += 1
        print(f"  ok  {说明}")
    else:
        失败.append(说明)
        print(f"  ✗   {说明}")


def 拿库() -> Any:
    """重新 import 库 —— 后端是启动时按环境变量定的, 换了环境要拿新模块。"""
    sys.modules.pop("库", None)
    return importlib.import_module("库")


def 跑一轮(库: Any, 表: str, 值: dict[str, Any]) -> dict[str, Any]:
    """同一串动作: 读空表 -> 写 -> 读回 -> 覆盖写 -> 列表 -> 删 -> 读空。"""
    出: dict[str, Any] = {}
    出["表名"] = 库.表名(表)
    出["空表读"] = 库.读文档(表, "k1")
    库.写文档(表, "k1", 值)
    出["读回"] = 库.读文档(表, "k1")
    库.写文档(表, "k1", {"改了": True, "数": 7})
    出["覆盖后"] = 库.读文档(表, "k1")
    库.写文档(表, "k2", [1, 2, 3])
    出["全部"] = sorted((k, v) for k, v in 库.全部(表))
    出["删掉行数"] = 库.删文档(表, "k1")
    出["删后读"] = 库.读文档(表, "k1")
    出["删不存在的行数"] = 库.删文档(表, "没有这个键")
    出["在不在"] = 库.在不在()
    库.删表(表)
    出["删表后全部"] = 库.全部(表)
    库.关连接()
    return 出


def main() -> int:
    表 = "双后端对拍"
    值: dict[str, Any] = {"序号": 1, "说明": "勘察落点", "中文": "带中文和 emoji 🚀 也照样存"}

    print("-- ① sqlite 后端（临时文件）")
    with tempfile.TemporaryDirectory() as 临时:
        os.environ["COLLAPLEX_DB_BACKEND"] = "sqlite"
        os.environ["COLLAPLEX_DB_FILE"] = str(pathlib.Path(临时) / "t.sqlite")
        os.environ.pop("COLLAPLEX_DB_PREFIX", None)
        库 = 拿库()
        判(库.后端() == "sqlite", "后端判定是 sqlite")
        判(库.库文件().name == "t.sqlite", f"库文件落在指定处: {库.库文件()}")
        sqlite结果 = 跑一轮(库, 表, 值)
        判(sqlite结果["空表读"] is None, "空表读 -> None（表还没建也不抛）")
        判(sqlite结果["读回"] == 值, "写进去的原文读得回来（含中文/emoji）")
        判(sqlite结果["覆盖后"] == {"改了": True, "数": 7}, "整份替换是原子的")
        判(sqlite结果["删掉行数"] == 1, "删文档返回真行数")
        判(sqlite结果["删不存在的行数"] == 0, "删不存在的键 -> 0，不抛")
        判(sqlite结果["在不在"] is True, "在不在() = True")
        判(sqlite结果["删表后全部"] == [], "删表后读全部 = 空表")

    print("-- ② pg 后端（沙盒前缀，不碰生产表）")
    os.environ["COLLAPLEX_DB_BACKEND"] = "pg"
    os.environ.pop("COLLAPLEX_DB_FILE", None)
    os.environ["COLLAPLEX_DB_PREFIX"] = "测试_"
    库 = 拿库()
    if not 库.在不在():
        print("  ?   pg 不通（没配 RAG_PG_DSN 或服务没起）—— 这一步跳过")
        return 收尾()
    判(库.后端() == "pg", "后端判定是 pg")
    判(库.表名(表).startswith("测试_"), f"沙盒前缀生效: {库.表名(表)}")
    pg结果 = 跑一轮(库, 表, 值)

    print("-- ③ 两边逐项对拍（形状必须一致，值必须一致）")
    for 项 in ("表名", "空表读", "读回", "覆盖后", "全部", "删掉行数", "删后读",
               "删不存在的行数", "在不在", "删表后全部"):
        a, b = sqlite结果[项], pg结果[项]
        if 项 == "表名":  # pg 那轮带沙盒前缀，故意不同 —— 只比结尾
            判(str(a).endswith(表) and str(b).endswith(表), f"{项}: {a} / {b}")
        else:
            判(a == b, f"{项} 两边一致: {a!r}")

    os.environ.pop("COLLAPLEX_DB_PREFIX", None)
    os.environ.pop("COLLAPLEX_DB_BACKEND", None)
    return 收尾()


def 收尾() -> int:
    print()
    if 失败:
        print(f"FAIL 双后端 {通过} 过 / {len(失败)} 败")
        for x in 失败:
            print(f"  - {x}")
        return 1
    print(f"OK 双后端 {通过}/{通过}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

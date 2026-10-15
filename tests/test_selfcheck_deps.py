#!/usr/bin/env python3
"""自检那两项新检查的回归 —— 模型 API 的 GET 检查 + skill 依赖检查.

背景: 启动自检加了两件事 ——
  ① 四组模型 API(主模型 / 向量 / 执行体 / 子 agent)各 GET 一次 /models,
     通不通 / Key 对不对 / 名字在不在;
  ② 扫 skill 底下每个包的依赖: python 包(扫 import 后用项目解释器 find_spec)、
     metadata.json 里声明的环境变量、声明的外部工具(如 carve)。

这里的规矩: 能真跑的绝不用假的 —— find_spec 走**真子进程**、网络探测打**真地址**
(拿一个没人监听的端口, 期望"连不上"这个真实结果), 判据函数喂真源码。

跑法: .venv/bin/python tests/test_selfcheck_deps.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))

import selfcheck  # noqa: E402

结果: list[tuple[bool, str]] = []


def 查(名称: str, 条件: bool, 细节: str = "") -> None:
    """记一条, 同时打出来。"""
    结果.append((bool(条件), f"{名称}{(' — ' + 细节) if 细节 else ''}"))


def 主() -> int:
    """运行一次, 打表, 返回退出码。"""
    # ① 扫 import: 顶层名、相对导入不算、语法错不炸
    源码 = (
        "import os\n"
        "import numpy as np\n"
        "from dotenv import load_dotenv\n"
        "import skill.rag.scripts.chunker as chunker\n"
        "from . import 同目录的\n"
        "import json, sys\n"
    )
    拿到 = selfcheck.collect_imports(源码)
    查("扫 import 拿到全部顶层名", {"os", "numpy", "dotenv", "skill", "json", "sys"} <= 拿到,
        f"拿到 {sorted(拿到)}")
    查("相对导入不冒充第三方包", "同目录的" not in 拿到 and "" not in 拿到)
    查("语法错的源码不炸, 返回空集", selfcheck.collect_imports("def (:\n") == set())

    # ② 真项目扫一遍: 有文件、且跳过了缓存/归档
    文件 = selfcheck.skill_python_files()
    查("skill 底下扫到 .py", len(文件) > 0, f"{len(文件)} 个")
    跳过 = {"cache", "_deprecated", "__pycache__", "upstream"}
    脏 = [str(p.relative_to(PROJECT)) for p in 文件 if 跳过 & set(p.relative_to(PROJECT).parts)]
    查("缓存 / 归档 / 上游目录都跳过", not 脏, f"漏进 {脏}" if 脏 else "")

    # ③ 真子进程 find_spec: 有的不报缺, 没有的必须报出来
    缺 = selfcheck.find_missing_modules({"numpy", "dotenv", "os"}, sys.executable)
    查("装着的包不报缺 (真子进程 find_spec)", 缺 == [], f"误报 {缺}")
    缺2 = selfcheck.find_missing_modules({"zzz_no_such_pkg_xyz"}, sys.executable)
    查("没装的包一定报出来", 缺2 == ["zzz_no_such_pkg_xyz"], f"报的是 {缺2}")
    查("空集合不打子进程", selfcheck.find_missing_modules(set(), sys.executable) == [])

    # ④ 真 metadata: 每个 skill 都有 name 与 needs(依赖检查的数据源)
    元 = selfcheck.skill_metadata()
    查("读到各 skill 的 metadata", len(元) >= 4, f"{sorted(元)}")
    缺字段 = [名 for 名, 数据 in 元.items() if not 数据.get("name") or "needs" not in 数据]
    查("metadata 里 name / needs 齐", not 缺字段, f"缺 {缺字段}")

    # ⑤ 模型 API 的 GET 检查: 真打一个没人监听的端口 -> 期望"连不上"(状态码 0)
    码, 名字 = selfcheck.api_get_models("http://127.0.0.1:1/v1", "", 2.0)
    查("连不上时返回 0 且不炸", 码 == 0 and 名字 == [], f"拿到 {码} / {名字}")
    码2, 名字2 = selfcheck.api_get_models("", "", 1.0)
    查("base 空时不炸", 码2 == 0 and 名字2 == [])

    # ⑥ 状态码翻译: 401 得说人话(模型 API 最常见的那个)
    查("401 说成 Key 不对", "Key" in selfcheck.http_reason(401), selfcheck.http_reason(401))
    查("5xx 说成服务端出错", "服务端" in selfcheck.http_reason(503), selfcheck.http_reason(503))

    # ⑦ 四组 API 的键名是 .env 里的真键(不要写错一个字母)
    键 = {"OPENAI_BASE_URL", "EMBEDDING_BASE_URL", "EXEC_BASE_URL", "SUBAGENT_BASE_URL"}
    用过 = {行[1] for 行 in selfcheck.API_GROUPS}
    查("四组 API 的 base 键对得上", 用过 == 键, f"表里是 {sorted(用过)}")

    通过 = sum(1 for 好, _ in 结果 if 好)
    for 好, 说明 in 结果:
        print(("  ✓ " if 好 else "  ✗ ") + 说明)
    print("\n" + "=" * 100)
    print(f"结果: {通过} 通过 / {len(结果) - 通过} 失败")
    print("=" * 100)
    return 0 if 通过 == len(结果) else 1


if __name__ == "__main__":
    raise SystemExit(主())

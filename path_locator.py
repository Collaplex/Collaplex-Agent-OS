#!/usr/bin/env python3
"""按名字找「件」（一个可执行的 Python 模块文件）—— 三种形态都认。

同一个 skill 可能以三种形态存在，取决于它是怎么分发出去的:

    源码形态    scripts/retrieve.py
    字节码形态  scripts/retrieve.pyc          （cpython + 字节码打包: 不带源码）
    编译件形态  scripts/retrieve.cpython-314-x86_64-linux-gnu.so   （Cython/Nuitka 编过）

代码里凡是"某件在不在""取它的路径"的地方，都该走这里，别直接拼 `.py` ——
自己拼 .py 的写法会让字节码包直接报"件不在"，而那是**假报错**（件明明在）。

用法::

    import path_locator as 件定位
    脚本 = 件定位.件路径(SCRIPTS, "retrieve.py")     # -> Path 或 None
    if 脚本 is None: ...
    件定位.有件(SCRIPTS, "retrieve.py")              # -> bool（给"列出动作"标 [缺文件] 用）
    返回码 = 件定位.跑件(脚本, ["find", "磁盘满了"], ROOT)

★ `跑件` 按形态分流: `.py` / `.pyc` 能当脚本直接执行（子进程，跟以前一模一样，
  还吃 venv 解释器）；`.so` 不能当脚本跑，只能在进程内导入。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def 件路径(目录: Path, 名字: str) -> Path | None:
    """在 `目录` 里按 `名字` 找件, 认出源码 / 字节码 / 编译件。找不到回 None。

    `名字` 可以带后缀（retrieve.py）也可以不带（retrieve）；也可以带子目录
    （skill/timer/main.py）—— 一律按"去掉后缀的那条路"去找。
    """
    干路 = (目录 / 名字).with_suffix("") if Path(名字).suffix else (目录 / 名字)

    直接 = 目录 / 名字
    if 直接.is_file():
        return 直接                       # 原名就是它（可能是 .md/.json 这类非代码件）

    for 候 in (干路.with_suffix(".py"), 干路.with_suffix(".pyc")):
        if 候.is_file():
            return 候

    缓存 = 干路.parent / "__pycache__"
    if 缓存.is_dir():
        for 候 in sorted(缓存.glob(f"{干路.name}.*.pyc")) + [缓存 / f"{干路.name}.pyc"]:
            if 候.is_file():
                return 候

    for 候 in sorted(干路.parent.glob(f"{干路.name}.*.so")) + [干路.with_suffix(".so")]:
        if 候.is_file():
            return 候
    return None


def 有件(目录: Path, 名字: str) -> bool:
    """`件路径` 的布尔版。"""
    return 件路径(目录, 名字) is not None


def 跑件(件: Path, 参数: list[str], 工作目录: Path | None = None,
        解释器: str | None = None) -> int:
    """按形态把件跑起来, 回退出码。

    `.py` / `.pyc` 走子进程（能当脚本直接执行, 输出不截断、退出码原样带回）;
    `.so` 进程内导入后调它的 `main()`。

    `解释器` 传 None 就用当前解释器; 入口脚本一般传自己那份 `python_bin()`
    （优先项目 venv, 与改动前的行为一致）。
    """
    if 件.suffix in (".py", ".pyc"):
        命令 = [解释器 or sys.executable, str(件), *参数]
        try:
            return subprocess.run(命令, cwd=str(工作目录) if 工作目录 else None).returncode
        except KeyboardInterrupt:
            return 130

    import importlib

    目录 = str(件.parent)
    sys.path.insert(0, 目录)
    try:
        模块 = importlib.import_module(件.name.split(".")[0])
    finally:
        sys.path.remove(目录)
    原argv, sys.argv = sys.argv, [str(件), *参数]
    try:
        return int(模块.main())
    finally:
        sys.argv = 原argv

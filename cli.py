#!/usr/bin/env python3
"""Collaplex Agent 的总入口 —— 一个命令管住所有启动方式。

用法:
    collaplex-agent web                  起 web；浏览器打开就是启动页, 页面上选怎么启动
    collaplex-agent web --本地            起 web 并自动走「以本地模型启动」
    collaplex-agent web --端口 9000       换端口
    collaplex-agent web --不打开          不自动开浏览器
    collaplex-agent 自检                   只跑自检（配置 / 依赖 / 库 / 代码 / 结构 / 定时）
    collaplex-agent 模型 start|stop|status  单独管本地模型服务
    collaplex-agent chat                  命令行对话（跟以前一样）

★ 为什么收成一个入口: 以前要照 README 记一串命令(起模型 / 跑自检 / python -m web.server),
  漏一步的表现都是"页面打不开"或"一问就报错", 得挨个排查。现在前置按顺序自己做。

★ --本地 时不在这里等——先把启动链丢后台线程, web 立刻起来; 页面一边显示进度
  一边等它跑完。要是先跑完几十秒再起 web, 用户对着一片黑等, 那不成黑盒了。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

根 = Path(__file__).resolve().parent
if str(根) not in sys.path:      # 从任何地方点进来都能 import 到本项目的模块
    sys.path.insert(0, str(根))

VENV_PY = 根 / ".venv" / "bin" / "python"


def _开浏览器(地址: str) -> None:
    """等 web 真答话了再开浏览器 —— 早开就是个连接被拒的错页。"""
    import urllib.error
    import urllib.request

    for _ in range(40):
        try:
            with urllib.request.urlopen(地址, timeout=2) as r:  # noqa: S310
                if int(r.status) < 500:
                    break
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.5)
    try:
        webbrowser.open(地址)
    except Exception:  # noqa: BLE001 —— 开不了浏览器不影响服务本身
        pass


def 起web(端口: int, 本地: bool, 开: bool) -> int:
    from web import start as 启动, server

    地址 = f"http://127.0.0.1:{端口}/启动"   # ★ 软件启动先站到启动页, 不是直接进主页面
    if 本地:
        启动.开线程(web端口=端口, 本地=True)
    if 开:
        threading.Thread(target=_开浏览器, args=(地址,), daemon=True).start()
    return server.跑(端口, "127.0.0.1")


def 跑自检() -> int:
    """直接把 selfcheck 的输出透传出来（--只查: 不要去 execv main.py）。"""
    甲 = 根 / "selfcheck.py"
    if not 甲.is_file():
        print("找不到 selfcheck.py", file=sys.stderr)
        return 1
    程序 = str(VENV_PY if VENV_PY.is_file() else sys.executable)
    return subprocess.run([程序, str(甲), "--只查"], cwd=str(根)).returncode  # noqa: S603


def main(argv: list[str] | None = None) -> int:
    解析 = argparse.ArgumentParser(
        prog="collaplex-agent",
        description="Collaplex Agent OS —— 程序管记忆, 模型管推理",
    )
    子 = 解析.add_subparsers(dest="命令")

    网 = 子.add_parser("web", help="起 web 界面")
    网.add_argument("--端口", type=int, default=8791)
    网.add_argument("--本地", action="store_true", help="自动走「以本地模型启动」")
    网.add_argument("--不打开", action="store_true", help="不自动开浏览器")

    子.add_parser("自检", aliases=["selfcheck", "--selfcheck"], help="跑自检(配置 / 依赖 / 库 / 代码 / 结构 / 定时)")
    # ★ ASCII 别名不是花哨: Windows 的 启动器.bat 必须保持纯 ASCII（cmd 按 GBK 读 .bat，
    #   UTF-8 中文会被拆成乱命令），所以批处理只能传 ASCII，中文交给 python 这边认。

    型 = 子.add_parser("模型", aliases=["models"], help="管本地模型服务")
    型.add_argument("动作", nargs="?", default="status", choices=["start", "stop", "status"])

    子.add_parser("chat", help="命令行对话")

    参数 = 解析.parse_args(argv)

    if 参数.命令 == "web":
        return 起web(参数.端口, bool(参数.本地), not 参数.不打开)
    if 参数.命令 == "自检" or 参数.命令 in ("selfcheck", "--selfcheck"):
        return 跑自检()
    if 参数.命令 == "模型" or 参数.命令 == "models":
        from web import start as 启动
        return 启动.管模型(参数.动作)
    if 参数.命令 == "chat":
        import main as 对话
        对话.main()
        return 0

    解析.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

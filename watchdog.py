#!/usr/bin/env python3
"""看门狗 —— 监控四个服务, 哪个挂了就拉起哪个。

    主模型  127.0.0.1:8790   挂了 -> 起回来（start_models.sh start）
    向量    127.0.0.1:8199   挂了 -> 起回来（同上, 那条命令会跳过已经在跑的）
    web     127.0.0.1:8791   挂了 -> 重新拉起 web.server
    PG      /var/run/postgresql  挂了 -> systemctl start postgresql
            ★ PG 不一样: 只在"见过它活着"之后才兜底 —— 开机本来没起(系统单元 disabled,
              老板手动控制), 看门狗不该自作主张拉起来。

用法:
    ./.venv/bin/python watchdog.py               常驻（默认每 30 秒看一次）
    ./.venv/bin/python watchdog.py --一次         只看一遍就退（启动页用它拿状态）
    ./.venv/bin/python watchdog.py --间隔 60      改间隔
    ./.venv/bin/python watchdog.py --web端口 9000 监控别的 web 端口

★ 按端口探活, 不看进程表。理由: "进程还在、但服务僵死"(端口能握手、应用层全死)
  这种事故判进程表是"活着", 可用户那边已经打不开了 —— 云服那次内存僵死就是这么来的。

★ 它自己也不能跟着 web 一起死: 拉 web 时脱开会话, 这样 web 挂了看门狗还在, 能把
  web 拉回来（POSIX 用 start_new_session, Windows 用 DETACHED_PROCESS）。

★ Windows 包也认（2026-10-12 接上）：PG 走随包/官方那份 pg_ctl、向量走随包 llama-server
  （都复用 web/start.py 的现成实现）, 没有本地主模型的机器不监控 8790。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

根 = Path(__file__).resolve().parent
VENV_PY = 根 / ".venv" / "bin" / "python"
日志 = 根 / "logs" / "watchdog.log"

是Windows = os.name == "nt"
装目录 = 根.parent          # ★ Windows 包里：<安装目录>\app ⇒ 上一级才是 llama/ models/ pgsql/


def _借启动() -> Any:
    """把 web/start.py 借来用 —— 平台的活都在它那儿（PG 走 pg_ctl、向量走随包 llama）。"""
    if str(根) not in sys.path:
        sys.path.insert(0, str(根))
    from web import start as _模  # noqa: PLC0415

    return _模


def _本机python() -> Path:
    r"""本机解释器：POSIX 用 .venv/bin/python，Windows 包用 <安装目录>\python\python.exe。"""
    for 候选 in (VENV_PY, 装目录 / "python" / "python.exe"):
        if 候选.is_file():
            return 候选
    return Path(sys.executable)


def _脱开参数() -> dict[str, Any]:
    """把子进程从本进程的作业/控制台里脱出来（等于 POSIX 的 start_new_session）。

    ★ 看门狗自己就是被 web 拉起来的：不脱开的话 web 一死它跟着死, 就没人把 web 拉回来了。
    ★ `DETACHED_PROCESS` / `CREATE_NEW_PROCESS_GROUP` 只有 **Windows 的 subprocess** 才有 ——
      用 `getattr` 取：本机（Linux）的类型定义里没这两个名字，直接写属性会被类型检查判成
      "不是已知属性"（2026-10-13 清除这类红点时修改，行为完全不变：Windows 上取到真值，别处取 0）。
    """
    if 是Windows:
        脱开 = int(getattr(subprocess, "DETACHED_PROCESS", 0))
        新进程组 = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        return {"creationflags": 脱开 | 新进程组}
    return {"start_new_session": True}

主模型端口 = 8790
向量端口 = 8199


def 记(话: str) -> None:
    """往 logs/watchdog.log 追加一行（带时间）—— 看门狗的动作要留痕。"""
    行 = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {话}"
    print(行, flush=True)
    try:
        日志.parent.mkdir(parents=True, exist_ok=True)
        with 日志.open("a", encoding="utf-8") as f:
            f.write(行 + "\n")
    except OSError:
        pass  # 写不了日志不该把看门狗带停


def 探(端口: int, 路: str = "/health", 秒: float = 2.5) -> bool:
    """这一个端口答不答话。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{端口}{路}", timeout=秒) as r:  # noqa: S310
            return 200 <= int(r.status) < 500
    except (urllib.error.URLError, OSError, ValueError):
        return False


def 看(web端口: int) -> dict[str, bool]:
    """四个服务各自的死活。web 没有 /health, 探根路径。

    ★ 没有本地主模型的机器（Windows 包）不监控 8790：它永远不通, 每轮都会空拉一次。
    """
    try:
        有主模型 = bool(_借启动().有本地模型())
    except Exception:  # noqa: BLE001
        有主模型 = not 是Windows
    return {
        "主模型": 探(主模型端口) if 有主模型 else True,
        "向量": 探(向量端口),
        "web": 探(web端口, "/"),
        "PG": 探pg(),
    }


PG主机 = "/var/run/postgresql"   # 系统实例（rag/清洗都用它）; 用户实例在 /home/lou/pgdata/socket
_见过pg = False                  # ★ 只在"见过它活着"之后才兜底: PG 是老板手动控制的东西
                                 #   （系统单元就是 disabled）, 开机本来就没起时看门狗不该自作主张
                                 #   拉起来; 但跑着跑着挂了要接住 —— 13:20 那次 PG 被重启,
                                 #   清洗空等了一下午。


def 探pg(秒: float = 4.0) -> bool:
    """PG 能不能接受连接。

    ★ 不看进程表: PG 僵死时进程照样在（云服那次内存僵死就是端口能握手、应用层全死）。
      pg_isready 会真走一次连接握手, 比"进程在不在"可信。
    """
    if 是Windows:
        # ★ Windows 上没有 pg_isready 那种系统命令 —— 借 启动.PG就绪()（它会真连一次监听口）。
        try:
            return bool(_借启动().PG就绪())
        except Exception:  # noqa: BLE001 —— 探活本身不能把看门狗带停
            return False
    try:
        r = subprocess.run(  # noqa: S603
            ["pg_isready", "-h", PG主机, "-q"], timeout=秒, check=False, capture_output=True,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def 拉pg() -> None:
    """把 PG 拉起来。"""
    if 是Windows:
        try:
            好 = bool(_借启动().起PG())
        except Exception as 错:  # noqa: BLE001
            记(f"✗ 拉 PG 出错: {错}")
            return
        记("  PG 拉起 ✓（pg_ctl）" if 好 else "✗ PG 没起来 —— 看 logs/pgsql.log")
        return
    try:
        r = subprocess.run(  # noqa: S603
            ["systemctl", "start", "postgresql"], timeout=90, check=False,
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            记("  PG 拉起 (systemctl start postgresql)")
        else:
            记(f"✗ 拉 PG 出错: {(r.stderr or '').strip()[:120]}")
    except (OSError, subprocess.SubprocessError) as 错:
        记(f"✗ 拉 PG 出错: {错}")


def 拉模型() -> None:
    """起本机模型服务（start_models.sh 自己会跳过已经在跑的）。"""
    if 是Windows:
        # ★ Windows 包不自带本地主模型, 只有随包的向量模型（CPU）—— 拉它就行。
        try:
            好 = bool(_借启动().起向量模型())
        except Exception as 错:  # noqa: BLE001
            记(f"✗ 拉模型出错: {错}")
            return
        记("  向量模型拉起 ✓" if 好 else "✗ 向量模型没起来 —— 看 logs/embed.log")
        return
    甲 = 根 / "start_models.sh"
    if not 甲.is_file():
        记("✗ 找不到 start_models.sh, 没法拉模型")
        return
    try:
        r = subprocess.run(  # noqa: S603
            ["bash", str(甲), "start"],
            cwd=str(根), capture_output=True, text=True, timeout=300,
        )
        for 行 in (r.stdout or "").strip().splitlines():
            记("  " + 行)
    except (OSError, subprocess.SubprocessError) as 错:
        记(f"✗ 拉模型出错: {错}")


def 拉web(端口: int) -> None:
    """把 web 重新拉起来。脱开会话, 免得它一死把看门狗也带走。"""
    程序 = str(_本机python())
    起 = [程序, "-m", "web.server", "--端口", str(端口)]
    (根 / "logs").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if 是Windows:
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env["PYTHONPATH"] = str(装目录 / "deps")
    try:
        with (根 / "logs" / "web.log").open("a", encoding="utf-8") as 收:
            p = subprocess.Popen(  # noqa: S603
                起, cwd=str(根), stdout=收, stderr=subprocess.STDOUT, env=env, **_脱开参数(),
            )
        记(f"  web 拉起 (pid {p.pid}) —— 日志 logs/web.log")
    except OSError as 错:
        记(f"✗ 拉 web 出错: {错}")


def 走一遍(web端口: int, 动手: bool) -> dict[str, Any]:
    """看一遍, 该拉的就拉。动手=False 时只看不动（--一次 用）。"""
    global _见过pg
    状态 = 看(web端口)
    if 状态["PG"]:
        _见过pg = True          # 见过它活着 → 以后它再挂, 我就兜底拉起来
    差 = [k for k, v in 状态.items() if not v]
    if not 差:
        return {"状态": 状态, "动作": []}

    动作: list[str] = []
    if 动手:
        if not 状态["主模型"] or not 状态["向量"]:
            缺 = " / ".join(k for k in ("主模型", "向量") if not 状态[k])
            记(f"⚠ {缺} 不通, 拉起来")
            拉模型()
            动作.append(f"拉模型({缺})")
        if not 状态["web"]:
            记(f"⚠ web(:{web端口}) 不通, 拉起来")
            拉web(web端口)
            动作.append("拉web")
        if _见过pg and not 状态["PG"]:
            记("⚠ PG 不通, 拉起来")
            拉pg()
            动作.append("拉PG")
    return {"状态": 状态, "动作": 动作 or ["(只看, 没动手)"]}


def main() -> int:
    解析 = argparse.ArgumentParser(description="Collaplex 看门狗")
    解析.add_argument("--一次", action="store_true", help="只看一遍（不动手）")
    解析.add_argument("--间隔", type=int, default=30, help="多久看一次, 秒")
    解析.add_argument("--web端口", type=int, default=8791)
    参数 = 解析.parse_args()

    if 参数.一次:
        出 = 走一遍(参数.web端口, 动手=False)
        状态 = cast(dict[str, bool], 出["状态"])
        for 名, 好 in 状态.items():
            print(f"  {名}  {'通' if 好 else '不通'}")
        return 0 if all(状态.values()) else 1

    记(f"看门狗上岗 —— 每 {参数.间隔} 秒看一次（主模型/向量/web(:{参数.web端口})/PG）")
    while True:
        try:
            出 = 走一遍(参数.web端口, 动手=True)
            for 话 in cast(list[str], 出["动作"]):
                记(f"  {话}")
        except KeyboardInterrupt:
            记("看门狗下岗")
            return 0
        except Exception as 错:  # noqa: BLE001 —— 看门狗不能因为一次失手就死
            记(f"✗ 这一轮出错: {错}")
        time.sleep(max(5, 参数.间隔))


if __name__ == "__main__":
    sys.exit(main())

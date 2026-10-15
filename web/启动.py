#!/usr/bin/env python3
"""启动链 —— 「以本地模型启动」时按顺序要办的那几件事。

    起 PG → 拉模型(8790 + 8199) → 检查单(二次核对) → 跑自检 → 起看门狗 + 起清洗 → 放开页面

★ 为什么放在程序里、而不是写成一个 shell 脚本: 启动页要**边做边把日志显示出来**。
  一步跑几十秒(模型加载), 用户得看见它在动; 跑完才知道结果等于黑盒等待。
  所以每一步都往 _进度 里记一行, 页面轮询 日志() 增量取。

★ 对外就三样:
    _在跑 / 进度  —— 现在到哪一步了
    跑()          —— 执行一遍（后台线程, 不堵 HTTP 请求）
    状态()        —— 四个服务各自通不通 + 跑完的结果码
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

根 = Path(__file__).resolve().parent.parent
VENV_PY = 根 / ".venv" / "bin" / "python"
自检 = 根 / "selfcheck.py"
看门狗 = 根 / "watchdog.py"

主模型端口 = 8790
向量端口 = 8199
PG单元 = "postgresql@18-main"   # ★ 本地 RAG 库(二层/三层)就落在这个集群上
间隔 = 30                        # 看门狗多久看一次(秒)

def 有本地模型() -> bool:
    """这台机器有没有"本地模型栈"（项目自带的那套 llama.cpp：vendor/llama.cpp）。

    ★ 没有它（比如 Windows 独立包不带 vendor/）就：启动页把「以本地模型启动」灰掉、
      检查单不查模型那两站、自检也不把"模型端点没配"当错 —— 那是"这台机器就不打算跑
      本地模型"，不是配置漏了（老板 2026-10-12）。
    """
    return (根 / "vendor" / "llama.cpp" / "build" / "bin" / "llama-server").is_file()

def 找嵌入模型() -> Path | None:
    """包里自带的那份向量模型（Windows 包：models\\Qwen3-Embedding-0.6B-Q8_0.gguf）。"""
    目录 = 根.parent / "models"   # ★ 模型在安装目录下（根是 app/，上一层才是安装目录）
    if not 目录.is_dir():
        return None
    for 文件 in sorted(目录.glob("*.gguf")):
        return 文件
    return None


def 有打包向量() -> bool:
    """包里带没带 llama.cpp(CPU) + 向量模型 —— 带了就能把向量模型拉起来（正常启动也拉）。"""
    return (根.parent / "llama" / "llama-server.exe").is_file() and 找嵌入模型() is not None


def 补向量环境() -> None:
    """把 .env 的 EMBEDDING_* 指向刚拉起来的这个本地向量服务（占位串也算没填）。

    ★ 为什么放在启动链里：装好那一刻的 .env 是模板（写着"在这里填"），
      如果只在安装时补一次，用户改了库/换机器就又会撞上；启动链每次核对一遍最稳。
    """
    环境 = 根 / ".env"
    if not 环境.is_file():
        return
    要填 = {
        "EMBEDDING_BASE_URL": f"http://127.0.0.1:{向量端口}/v1",
        "EMBEDDING_MODEL": "qwen3-embedding-0.6b",
        "EMBEDDING_API_KEY": "sk-local",
    }
    占位 = {"在这里填", "填这里", "todo", "TODO", "sk-xxx"}
    行们 = 环境.read_text(encoding="utf-8", errors="replace").splitlines()
    见过: set[str] = set()
    出: list[str] = []
    改了 = False
    for 行 in 行们:
        if "=" in 行 and not 行.lstrip().startswith("#"):
            键, _, 值 = 行.partition("=")
            if 键.strip() in 要填:
                见过.add(键.strip())
                净 = 值.strip().strip("\"'")
                if 净 and 净 not in 占位:
                    出.append(行)          # 自己配过（比如接云端）就别动
                else:
                    出.append(f"{键.strip()}={要填[键.strip()]}")
                    改了 = True
                continue
        出.append(行)
    for 键, 值 in 要填.items():
        if 键 not in 见过:
            出.append(f"{键}={值}")
            改了 = True
    if 改了:
        环境.write_text("\n".join(出) + "\n", encoding="utf-8")
        记("已将 .env 的向量端点指向本地 :8199（EMBEDDING_BASE_URL / MODEL / KEY）")


def 起向量模型(等秒: float = 240.0) -> bool:
    """把向量（嵌入）模型拉起来：包里自带的 llama.cpp，纯 CPU（-ngl 0），端口 8199。

    ★ 为什么要它：记忆检索（二层热库 / 三层冷库 / 语料）全靠嵌入。Windows 包不带主模型，
      但向量模型小、纯 CPU 就能跑 —— 所以「正常启动」这条路也把它拉起来（老板 2026-10-12）。
    ★ 插件式落盘：子进程脱离本进程（DETACHED），面板窗口关了它照样活着。
    """
    if 探(向量端口):
        记("向量模型已在运行 ✓")
        补向量环境()
        return True
    exe = 根.parent / "llama" / "llama-server.exe"
    模型 = 找嵌入模型()
    if not exe.is_file() or 模型 is None:
        记("  跳过：包内无 llama.cpp 或向量模型")
        return False
    (根.parent / "logs").mkdir(parents=True, exist_ok=True)
    记(f"拉起向量模型（CPU，{模型.name}）→ 127.0.0.1:{向量端口} …… 第一次加载要几十秒")
    命令 = [
        str(exe), "-m", str(模型), "--host", "127.0.0.1", "--port", str(向量端口),
        "-ngl", "0", "--alias", "qwen3-embedding-0.6b", "--embedding",
    ]
    try:
        出 = (根.parent / "logs" / "embed.log").open("a", encoding="utf-8")
        子 = subprocess.Popen(  # noqa: S603
            命令, cwd=str(根.parent / "llama"), stdout=出, stderr=出,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except OSError as 错:
        记(f"  ✗ 向量模型起不来: {错}")
        return False
    好 = 等就绪(向量端口, 等秒)
    if 好:
        补向量环境()
    记(f"向量模型就绪 ✓ (pid {子.pid})" if 好 else "✗ 向量模型没起来 —— 看 logs/embed.log")
    return 好



_锁 = threading.Lock()
_进度: list[str] = []
_在跑 = False
_结果 = ""          # "" 没跑过 / "好" 全过 / "坏" 哪一步断了
_线程: threading.Thread | None = None


# ────────────────────────── 对外 ──────────────────────────

def 清空() -> None:
    """把上一轮的日志清掉，开始新的一轮。"""
    global _进度, _结果
    with _锁:
        _进度 = []
        _结果 = ""


def 记(话: str) -> None:
    """记一行进度（带时刻）—— 页面就是这么看到"它在动"的。

    ★ 同时追加到 logs/启动.log: 页面那一份是内存里的(重启就没), 而设置页的
      「日志」要看的是**落盘**的 —— 两处都要留。
    """
    行 = f"[{time.strftime('%H:%M:%S')}] {话}"
    with _锁:
        _进度.append(行)
    print(行, flush=True)
    try:
        with (根 / "logs" / "启动.log").open("a", encoding="utf-8") as f:
            f.write(行 + "\n")
    except OSError:
        pass  # 写不了落盘那份, 不该把启动链带停


def 进度(起: int = 0) -> list[str]:
    """从第 起 行开始取日志（页面每轮传上次拿到的行数, 增量取）。"""
    with _锁:
        return list(_进度[起:])


def 在跑() -> bool:
    return _在跑


def 结果() -> str:
    return _结果


def 探(端口: int, 路: str = "/health", 秒: float = 2.5) -> bool:
    """这一个端口答不答话（答了就算活, 不追究状态码）。

    ★ 必须抓 HTTPError: urlopen 对非 2xx 会抛异常, 直接吞成 False 就出事 ——
      llama-server 加载权重期间 /health 正好回 503, 那几十秒里模型明明起来了,
      启动链却判"没起来"（2026-10-08 老板点启动页撞上的就是这个; 而 start_models.sh
      那边用 curl 不带 -f、"连上就算活", 于是两边判据打架, 日志里同时出现
      "起来了"和"没起来"）。
    """
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{端口}{路}", timeout=秒) as r:  # noqa: S310
            return 200 <= int(r.status) < 500
    except urllib.error.HTTPError:
        return True      # 答了话就是活的（503=还在加载权重也算）
    except (urllib.error.URLError, OSError, ValueError):
        return False


def 等就绪(端口: int, 秒: float = 240.0, 步: float = 2.0) -> bool:
    """等它真能吃请求 —— 光"答话"不算, 要 2xx。

    llama-server 加载权重那几十秒 /health 一直回 503, 而 start_models.sh 是
    "连上就算活", 所以它会先说"起来了"。启动链必须自己等到真就绪, 不然就是
    师傅说到了、门口还锁着。
    """
    截至 = time.monotonic() + 秒
    while time.monotonic() < 截至:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{端口}/health", timeout=3.0) as r:  # noqa: S310
                if 200 <= int(r.status) < 300:
                    return True
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(步)
    return False


def 状态(web端口: int = 8791) -> dict[str, Any]:
    """四个服务 + 自检 + 这一轮跑到哪了。页面靠它画那四盏灯。"""
    return {
        "PG": PG就绪(),
        "主模型": 探(主模型端口),
        "向量": 探(向量端口),
        "web": 探(web端口, "/"),
        "本地模型": 有本地模型(),      # 页面靠它决定「以本地模型启动」亮不亮
        "在跑": _在跑,
        "结果": _结果,
    }


# ────────────────────── 每一步 ──────────────────────

def _pg目标() -> tuple[str, int]:
    """从 .env 的 RAG_PG_DSN 取出 (主机, 端口)。

    ★ 两种写法都要认（2026-10-12 修）：URL 形 `postgresql://用户:口令@主机:端口/库`
      与 关键字形 `host=... port=...`。以前只认后者 —— Windows 包里那种 URL 形的
      DSN 被整条忽略、退回 Linux 默认的 /var/run/postgresql，接着 _pg连得上() 去碰
      socket.AF_UNIX（Windows 的 socket 模块没有这个属性）→ AttributeError →
      /api/启动/状态 500 → 页面上显示"拉日志失败"。
    ★ Windows 上默认回环 TCP：那边没有 Unix 套接字可连。
    """
    主机, 端口 = ("127.0.0.1", 5433) if os.name == "nt" else ("/var/run/postgresql", 5432)
    dsn = os.environ.get("RAG_PG_DSN", "")
    甲 = 根 / ".env"
    if not dsn and 甲.is_file():
        for 行 in 甲.read_text(encoding="utf-8", errors="replace").splitlines():
            if 行.strip().startswith("RAG_PG_DSN="):
                dsn = 行.split("=", 1)[1].strip().strip("\"'")
                break
    dsn = dsn.strip()
    if dsn.startswith(("postgresql://", "postgres://")):
        try:
            from urllib.parse import urlparse  # noqa: PLC0415

            解 = urlparse(dsn)
            if 解.hostname:
                主机 = 解.hostname
            if 解.port:
                端口 = int(解.port)
            return 主机, 端口
        except ValueError:
            pass
    for 段 in dsn.split():
        if 段.startswith("host="):
            主机 = 段.split("=", 1)[1]
        elif 段.startswith("port="):
            try:
                端口 = int(段.split("=", 1)[1])
            except ValueError:
                pass
    return 主机, 端口


def _pg连得上() -> bool:
    """连一下 PG 的监听口 —— 连上就算它活着（不真发查询）。"""
    主机, 端口 = _pg目标()
    # ★ Windows 的 socket 模块可能没有 AF_UNIX（实测 AttributeError: module 'socket'
    #   has no attribute 'AF_UNIX'），Unix 套接字路径在那边本来也不可用 —— 退回 TCP 回环。
    走套接字 = 主机.startswith("/") and hasattr(socket, "AF_UNIX")
    if 主机.startswith("/") and not 走套接字:
        主机 = "127.0.0.1"
    try:
        if 走套接字:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(1.5)
                s.connect(f"{主机}/.s.PGSQL.{端口}")
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.5)
                s.connect((主机, 端口))
        return True
    except OSError:
        return False


def PG就绪(秒: float = 0.0) -> bool:
    """PG 起没起、连不连得上（秒 > 0 时等它，最多等这么久）。"""
    截至 = time.monotonic() + max(0.0, 秒)
    while True:
        if _pg连得上():
            return True
        if time.monotonic() >= 截至:
            return False
        time.sleep(0.5)


def _起PG本机(试: int = 3) -> bool:
    """Windows / 没有系统集群的机器：用随包或官方装的那份，pg_ctl 按需拉起来。

    ★ 为什么单独一条：上面那条走 systemd（`systemctl start postgresql@18-main`），
      Windows 上既没有 systemd 也没有那个集群 —— 不区分的话「正常启动」第一站就断。
      两种来历都认：官方安装器装的在 <安装目录>\\pgsql\\data，包里自带的在 data\\pg。
    """
    数据目录 = None
    for 候选 in (根 / "pgsql" / "data", 根 / "data" / "pg"):
        if (候选 / "PG_VERSION").is_file():
            数据目录 = 候选
            break
    pg_ctl = 根 / "pgsql" / "bin" / "pg_ctl.exe"
    if 数据目录 is None or not pg_ctl.is_file():
        记("✗ 未找到本机 PostgreSQL（pgsql\\data 与 data\\pg 均不存在）")
        return False
    端口 = _pg目标()[1]
    好 = False
    for 第 in range(1, 试 + 1):
        抬头 = f"（第 {第} 次）" if 第 > 1 else ""
        记(f"拉起本机 PostgreSQL（{数据目录}）{抬头}……")
        try:
            # ★ 抓输出会永远等 EOF：pg_ctl 把 postgres 拉成常驻子进程，管道写端不关
            subprocess.run(  # noqa: S603
                [str(pg_ctl), "-D", str(数据目录), "-l", str(根 / "logs" / "pgsql.log"),
                 "-o", f"-p {端口} -c listen_addresses=127.0.0.1", "-w", "-t", "60", "start"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        except (OSError, subprocess.SubprocessError) as 错:
            记(f"  ✗ pg_ctl 出错: {错}")
        else:
            if PG就绪(30.0):
                好 = True
                break
            记("  … 尚未连接，3 秒后重试")
        if 第 < 试:
            time.sleep(3)
    记("PostgreSQL 就绪 ✓" if 好 else "✗ 本机那份 PG 没起来 —— 看 logs/pgsql.log")
    return 好


def 起PG(试: int = 3) -> bool:
    """把 PostgreSQL 拉起来（系统集群 —— 本地 RAG 库就在它上面）。

    ★ 判据要**以「socket 连得上」为准, 不看 systemctl 的退出码**: 本机另有一个
      lou 的用户实例占着 0.0.0.0:5432（`-D /home/lou/pgdata`）, 系统集群只能退到
      [::1] + unix socket; 刚停完立刻起时 `systemctl start` 常报「连接超时」/失败,
      隔几秒重试就成 —— 2026-10-08 实测头一次失败、第二次成功。

    ★ 为什么加这一站: RAG 库(二层/三层)从 JSON 挪到 PG(`store.backend=pg`)后,
      PG 不在, 二层热库/三层冷库全读不到。老板点「正常启动」时自检报的那两条错,
      根因就是启动链里没有 PG 这一站、而系统集群又只是 `enabled-runtime`
      （重启后不会自己起来）。
    """
    if PG就绪():
        记("PostgreSQL 已在运行 ✓")
        return True
    if os.name == "nt":
        # ★ Windows：没有 systemd 那套 —— 直接走本机那份（pg_ctl）
        return _起PG本机(试)
    好 = False
    for 第 in range(1, 试 + 1):
        抬头 = f"（第 {第} 次）" if 第 > 1 else ""
        记(f"拉起 PostgreSQL（{PG单元}）{抬头}…… 本地 RAG 库在它上面")
        try:
            r = subprocess.run(  # noqa: S603
                ["systemctl", "start", PG单元], capture_output=True, text=True, timeout=90,
            )
        except (OSError, subprocess.SubprocessError) as 错:
            记(f"  ✗ systemctl 出错: {错}")
        else:
            for 行 in ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[:2]:
                记("  " + 行)
            if PG就绪(30.0):
                好 = True
                break
            记("  … 尚未连接，3 秒后重试")
        if 第 < 试:
            time.sleep(3)
    记("PostgreSQL 就绪 ✓" if 好 else f"✗ PG 试了 {试} 次都没起来 —— 查 journalctl -u {PG单元}")
    return 好


def 检查单(web端口: int = 8791) -> bool:
    """二次核对: 自检之前把几个要害逐条打勾（起没起 / 答不答话）。

    ★ 与自检分工不同 —— 这一关只核**服务在不在**（PG / 主模型 / 向量 / web）;
      自检核的是**数据与配置对不对**（库能不能读、维度对不对、提示词齐不齐）。
      服务没起全就去跑自检, 报的是一堆"库读不到"的连环错, 看不出真因。
    """
    项: list[tuple[str, bool, str]] = [
        ("PostgreSQL", PG就绪(), "真连一次监听口"),
    ]
    if 有本地模型():
        项 += [
            ("主模型 :8790", 探(主模型端口), "/health 答话"),
            ("向量 :8199", 探(向量端口), "/health 答话"),
        ]
    elif 有打包向量():
        # Windows 包不带主模型，但带了 CPU 版向量模型 —— 这一站要查
        项.append(("向量 :8199", 探(向量端口), "/health 答话（包里自带的 CPU 版）"))
    else:
        记("  跳过：本地模型两级（本机无 vendor/llama.cpp，且未打包向量模型）")
    项.append((f"web :{web端口}", 探(web端口, "/"), "页面答话"))
    记("检查单（二次核对）—— 逐条确认:")
    全 = True
    for 名, 好, 判据 in 项:
        全 = 全 and 好
        记(f"  [{'✓' if 好 else '✗'}] {名} —— {判据}")
    记("检查单全过 ✓" if 全 else "✗ 检查单有没过项 —— 先补上再自检")
    return 全


def 拉模型() -> bool:
    """起本机两个模型服务。start_models.sh 自己会跳过已经在跑的、并等到就绪。"""
    if not 有本地模型():
        记("  跳过：本机无本地模型栈（vendor/llama.cpp 不存在）")
        return False
    甲 = 根 / "start_models.sh"
    if not 甲.is_file():
        记("✗ 未找到 start_models.sh")
        return False
    记("启动本地模型（主模型 8790 / 向量 8199）…… 首次加载权重较慢")
    try:
        r = subprocess.run(  # noqa: S603
            ["bash", str(甲), "start"],
            cwd=str(根), capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as 错:
        记(f"✗ 拉模型失败: {错}")
        return False
    for 行 in (r.stdout or "").strip().splitlines():
        记("  " + 行)
    for 行 in (r.stderr or "").strip().splitlines()[:5]:
        记("  ! " + 行)
    记("  等待两个模型加载完成（以 /health 返回 2xx 为准）……")
    好 = 等就绪(主模型端口) and 等就绪(向量端口)
    记("模型就绪 ✓" if 好 else "✗ 模型没起来 —— 看 logs/chat.log 和 logs/embed.log")
    return 好


def 跑自检() -> bool:
    """30 项自检。--只查: 不在终端上也只出结果, 不要去 execv main.py。"""
    if not 自检.is_file():
        记("✗ 未找到 selfcheck.py")
        return False
    记("运行自检（30 项：配置 / 接口 / 模型 / 库 / 代码）……")
    程序 = str(VENV_PY if VENV_PY.is_file() else sys.executable)
    try:
        r = subprocess.run(  # noqa: S603
            [程序, str(自检), "--只查"],
            cwd=str(根), capture_output=True, text=True, timeout=300,
            # ★ 子进程吐的是 UTF-8（PYTHONIOENCODING），父进程默认按本地码页(cp936)解
            #   → 中文变乱码、报错摘要会成空括号（2026-10-12 Windows 实测）—— 这里定死 UTF-8。
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as 错:
        记(f"✗ 自检跑不起来: {错}")
        return False
    出 = (r.stdout or "").strip().splitlines()
    for 行 in 出[-16:]:            # 尾巴那段是统计, 前面的明细太多
        记("  " + 行)
    好 = r.returncode == 0
    记("自检全过 ✓" if 好 else f"✗ 自检有报错（{' '.join(出[-2:])}）")
    return 好


def 起看门狗(web端口: int = 8791) -> bool:
    """挂上看门狗（盯四个服务, 谁挂拉谁）。已经有一个在跑就不重复挂。"""
    if _看门狗在跑():
        记("看门狗已在运行，不重复挂载")
        return True
    if not 看门狗.is_file():
        记("✗ 未找到 watchdog.py")
        return False
    记(f"挂看门狗（每 {间隔} 秒看一次 主模型/向量/web/PG）…… 日志 logs/watchdog.log")
    程序 = str(VENV_PY if VENV_PY.is_file() else sys.executable)
    (根 / "logs").mkdir(parents=True, exist_ok=True)
    try:
        # ★ stdout / stderr 都扔掉: 看门狗自己会用 记() 往 logs/watchdog.log 写。
        #   这里再把它的 stdout 重定向到同一个文件, 就成了每条写两遍(日志里
        #   一模一样的两行"上岗"就是这么来的, 看着像起了两个看门狗)。
        p = subprocess.Popen(  # noqa: S603
            [程序, str(看门狗), "--间隔", str(间隔), "--web端口", str(web端口)],
            cwd=str(根), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as 错:
        记(f"✗ 看门狗起不来: {错}")
        return False
    记(f"看门狗上岗 ✓ (pid {p.pid})")
    return True


清洗脚本 = 根 / "skill" / "rag" / "scripts" / "refine.py"


def 起清洗() -> bool:
    """把清洗挂上（热层下沉到经验层, 到点自己干一轮, 常驻）。

    ★ Windows 包也挂（2026-10-12 接上）: 以前只在 Linux 侧靠 cron 跑, 日志页那一格永远是
      "还没有", 老板读成"没接线"。跟看门狗一样用脱开的子进程常驻, 输出进 logs/refine.log。
    """
    if not 清洗脚本.is_file():
        记("✗ 未找到 skill/rag/scripts/refine.py")
        return False
    程序 = str(VENV_PY if VENV_PY.is_file() else sys.executable)
    (根 / "logs").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    是win = os.name == "nt"
    if 是win:
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env["PYTHONPATH"] = str(根.parent / "deps")
    记(f"挂清洗（热层下沉到经验层, 到点自己干一轮）…… 日志 logs/refine.log")
    # ★ DETACHED_PROCESS / CREATE_NEW_PROCESS_GROUP 只有 Windows 的 subprocess 才有（本机类型定义里没有，
    #   直接写属性会被判"不是已知属性"）—— 跟起向量模型那一处同样用 getattr 取。
    脱开旗 = int(getattr(subprocess, "DETACHED_PROCESS", 0)) | int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        with (根 / "logs" / "refine.log").open("a", encoding="utf-8") as 收:
            p = subprocess.Popen(  # noqa: S603
                [程序, str(清洗脚本), "--看守", "--安静"],
                cwd=str(根), env=env, stdout=收, stderr=subprocess.STDOUT,
                creationflags=脱开旗 if 是win else 0,
                start_new_session=not 是win,
            )
    except OSError as 错:
        记(f"✗ 清洗起不来: {错}")
        return False
    记(f"清洗上岗 ✓ (pid {p.pid})")
    return True


def _看门狗在跑() -> bool:
    """按命令行精确点名（不要用 pgrep -f: 会匹配到我自己这条命令）。"""
    目标 = "watchdog" + ".py"
    if os.name == "nt":
        # ★ Windows 没有 /proc —— 借 CIM 问一句：有哪个 python 的命令行带 watchdog.py。
        try:
            r = subprocess.run(  # noqa: S603
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                 "Where-Object { $_.CommandLine -like '*watchdog.py*' } | Measure-Object).Count"],
                capture_output=True, text=True, timeout=30,
            )
            return (r.stdout or "").strip().isdigit() and int((r.stdout or "0").strip()) > 0
        except (OSError, subprocess.SubprocessError, ValueError):
            return False
    for pid in Path("/proc").iterdir():
        if not pid.name.isdigit():
            continue
        try:
            命令行 = (pid / "cmdline").read_bytes().decode("utf-8", "ignore").replace("\0", " ")
        except OSError:
            continue
        if 目标 in 命令行 and "启动" + ".py" not in 命令行:
            return True
    return False


def 管模型(动作: str) -> int:
    """转发给 start_models.sh（启动页的"起/停/看状态"）。"""
    if not 有本地模型():
        print("本机无本地模型栈（vendor/llama.cpp 不存在），模型 start/stop 不可用。")
        return 1
    甲 = 根 / "start_models.sh"
    if not 甲.is_file():
        print("未找到 start_models.sh", file=sys.stderr)
        return 1
    return subprocess.run(["bash", str(甲), 动作], cwd=str(根)).returncode  # noqa: S603


# ────────────────────── 全套 ──────────────────────

def 全套(web端口: int = 8791, 本地: bool = True) -> tuple[bool, str]:
    """走一遍启动链（阻塞）。返回 (成不成, 说明)。页面在后台线程里调它。"""
    global _在跑, _结果
    with _锁:
        if _在跑:
            return False, "已有一轮在运行"
        _在跑 = True
    try:
        记("=" * 46)
        记("以本地模型启动" if 本地 else "正常启动（不拉本地主模型）")
        记("=" * 46)
        # ① 逐个启动 —— 自检前先把该起的一站一站起起来（缺哪一站, 自检会报一串连环错）
        记("① 逐个启动")
        if 本地 and not 有本地模型():
            记("  本机无本地模型栈（vendor/llama.cpp 不存在）—— 按正常启动执行，不加载模型")
            本地 = False
        if not 起PG():
            _结果 = "坏:PG"
            return False, "PostgreSQL 未启动"
        if 本地:
            if not 拉模型():
                _结果 = "坏:模型"
                return False, "模型没起来"
            撤闸门()      # ★ 模型起来了才撤停机闸门 —— 清洗下一分钟自己接着干
        else:
            记("  跳过：加载本地主模型")
            起向量模型()      # ★ 正常启动也把向量模型拉起来（CPU）—— 记忆检索要用它

        # ② 检查单 —— 起全了没有, 逐条打勾（管"服务在不在", 与自检分工不同）
        记("② 检查单（二次核对）")
        if not 检查单(web端口):
            _结果 = "坏:检查单"
            return False, "检查单有没过项"

        # ③ 自检 —— 管"数据与配置对不对"
        记("③ 自检")
        if not 跑自检():
            _结果 = "坏:自检"
            return False, "自检有报错"

        # ④ 看门狗 + 清洗 —— ★ 两种启动方式都挂（老板 2026-10-12：这俩才是"接线"）
        if not 起看门狗(web端口):
            记("看门狗未挂载，但主流程可继续 —— 继续")
        if not 起清洗():
            记("清洗未挂载，但主流程可继续 —— 继续")

        _结果 = "好"
        记("=" * 46)
        记("启动完成 —— 可以开始使用")
        return True, "好"
    finally:
        with _锁:
            _在跑 = False


def 开线程(web端口: int = 8791, 本地: bool = True) -> bool:
    """后台跑 全套()，立刻返回 —— HTTP 请求不能被几十秒的启动堵住。"""
    global _线程
    if 在跑():
        return False
    清空()
    _线程 = threading.Thread(target=全套, args=(web端口, 本地), daemon=True)
    _线程.start()
    return True


def 读日志(哪: str = "chat", 行数: int = 120) -> str:
    """读本地那个 log 的尾巴 —— 启动页的"日志"框直接显示它。

    ★ 直接读文件, 不缓存: 模型加载时日志一行行往外吐, 缓存了就成了假进度。
    """
    对照 = {"chat": "chat.log", "embed": "embed.log", "看门狗": "watchdog.log", "web": "web.log"}
    名 = 对照.get(哪, "chat.log")
    甲 = 根 / "logs" / 名
    if not 甲.is_file():
        return f"（还没有 logs/{名}）"
    try:
        全部 = 甲.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as 错:
        return f"（读不了 logs/{名}: {错}）"
    return "\n".join(全部[-max(1, 行数):])


def 日志() -> dict[str, str]:
    """三个日志的尾巴一起给页面（一次请求拿全, 免得页面发三个）。"""
    return {k: 读日志(k, 60) for k in ("chat", "embed", "看门狗")}


# ────────────────────────── 关闭 ──────────────────────────

# ★ 停机闸门(state/停机): cron 里的清洗(refine)和灌语料每分钟/每十分钟醒一次 ——
#   机器停了模型之后, 它们会一直"起来 → 问不到模型 → 退避重试 → 全线停 → 下分钟再来"地
#   空转, 白耗 CPU、日志全是重试行。所以关模型时落个闸门文件, 两边一看就跑。
#   开机走「以本地模型启动」会自动撤掉; 手动撤 = rm state/停机。
闸门 = 根 / "state" / "停机"


def 落闸门(原因: str = "") -> None:
    """落下停机闸门(清洗/灌语料下一轮就收手)。"""
    闸门.parent.mkdir(parents=True, exist_ok=True)
    闸门.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')} 停机{f' —— {原因}' if 原因 else ''}\n",
                    encoding="utf-8")
    记("  清洗闸门落下: state/停机（清洗 / 灌语料下一轮不再启动）")


def 撤闸门() -> None:
    """撤掉停机闸门 —— 只在"模型真的起来了"之后调, 否则清洗起来也没模型可问。"""
    if 闸门.exists():
        try:
            闸门.unlink()
        except OSError as 错:
            记(f"  ✗ 闸门撤不掉: {错}")
            return
        记("  清洗闸门撤除: state/停机 已删除（清洗下一分钟自行接续）")


def 停看门狗() -> int:
    """把看门狗停掉（它一停, 就不会再把服务自动拉起来）。返回停掉几个。"""
    目标 = "watchdog" + ".py"
    停 = 0
    for 项 in Path("/proc").iterdir():
        if not 项.name.isdigit():
            continue
        try:
            命令行 = (项 / "cmdline").read_bytes().decode("utf-8", "ignore").replace("\0", " ")
        except OSError:
            continue
        if 目标 in 命令行 and "启动" + ".py" not in 命令行:
            try:
                os.kill(int(项.name), signal.SIGTERM)
                停 += 1
            except OSError:
                pass
    if 停:
        记(f"看门狗停了 {停} 个")
    return 停


def 关模型() -> dict[str, Any]:
    """停本机两个模型服务（主模型 8790 + 向量 8199）。

    ★ 必须**先停看门狗**: 不然它 30 秒后就把刚关掉的模型又拉起来了 ——
      用户看到的是"关了又自己起来", 会以为按钮坏了。
    """
    停看门狗()
    落闸门("关模型")
    么 = 根 / "start_models.sh"
    if not 么.is_file():
        return {"好": False, "说明": "未找到 start_models.sh"}
    记("正在停本地模型……")
    try:
        r = subprocess.run(  # noqa: S603
            ["bash", str(么), "stop"], cwd=str(根),
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as 错:
        return {"好": False, "说明": f"停模型出错: {错}"}
    for 行 in (r.stdout or "").strip().splitlines():
        记("  " + 行)
    好 = not (探(主模型端口) or 探(向量端口))
    记("模型已停 ✓" if 好 else "✗ 还有端口在答话")
    return {"好": 好, "说明": "模型已停" if 好 else "还有服务没停掉"}


def 关自己(延迟: float = 1.5) -> None:
    """把 web 自己关掉。

    ★ 必须延迟: 这个 HTTP 响应此刻还没发回去, 立刻退的话页面那头只看到
      "连接被重置", 老板会以为没关成功（还看不到一句说明）。等它把响应和
      页面上那句"已关闭"收完再退。
    ★ 用 os._exit 而不是 sys.exit: 现在跑在后台线程里, sys.exit 只结束那个线程,
      而 serve_forever 还活着 —— 服务其实没关。
    """
    def _到点() -> None:
        time.sleep(max(0.2, 延迟))
        os._exit(0)

    threading.Thread(target=_到点, daemon=True).start()


if __name__ == "__main__":
    好, 说明 = 全套(本地="--正常" not in sys.argv)
    print(说明)
    raise SystemExit(0 if 好 else 1)

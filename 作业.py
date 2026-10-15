#!/usr/bin/env python3
"""作业 —— 把长活丢后台跑，定时回来看它跑完没有 + 取结果。

为什么要有这件东西（2026-10-09 老板定）:
    定时器原来只有两件: 「到点提醒我」「就在这等着读秒」。要的是更实用的那半边 ——
    **延时让写好的脚本 / 命令跑完，然后看结果**: 起活 → 等它跑完 → 把退出码 + 日志尾收回来。

怎么用:
    id = 作业.起(["python", "skill/rag/scripts/refine.py", "--强制"], 说明="重洗语料")
    作业.查(id)             -> {"状态": "在跑"|"跑完"|"失败", "退出码": int|None, "日志尾": str}
    作业.等(id, 每秒=回调)   -> 等到它结束再返回, 每秒回调一次读秒
    作业.列()              -> 这个项目起过的活

账在 state/作业.json, 日志在 logs/作业-<id>.log —— 都在项目目录里, 进程重启也读得回来。
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable, cast

根 = Path(__file__).resolve().parent
账本 = 根 / "state" / "作业.json"
日志目录 = 根 / "logs"


def _读() -> dict[str, Any]:
    文 = 账本
    if not 文.exists():
        return {}
    try:
        原 = json.loads(文.read_text(encoding="utf-8"))
    except Exception:                            # noqa: BLE001 - 账坏了不该把活也带崩
        return {}
    return cast(dict[str, Any], 原) if isinstance(原, dict) else {}


def _写(账: dict[str, Any]) -> None:
    账本.parent.mkdir(parents=True, exist_ok=True)
    临时 = 账本.with_suffix(".json.tmp")
    临时.write_text(json.dumps(账, ensure_ascii=False, indent=2), encoding="utf-8")
    临时.replace(账本)


def 起(命令: str | list[str], 说明: str = "", 冷却秒: float = 0.0) -> str:
    """把命令丢到后台跑（另开一个会话, 这一轮结束也不牵连它）。

    命令给字符串就走 shell（解析重定向、管道用得上）, 给列表就直接 exec（不经 shell）。
    返回活号; 说明是给主 agent 自己看的（"重洗语料""跑完看结果"）。
    """
    号 = time.strftime("%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    if 冷却秒:
        time.sleep(冷却秒)
    日志目录.mkdir(parents=True, exist_ok=True)
    日 = 日志目录 / f"作业-{号}.log"
    退文 = 日志目录 / f"作业-{号}.退出"
    命令串 = 命令 if isinstance(命令, str) else " ".join(shlex.quote(str(x)) for x in 命令)
    # ★ 必须用 sh -c 包住: nohup 只认「简单命令」, "nohup for i in …" 会直接失败并立即退出(已踩坑)。
    # ★ 退出码由活自己写到 .退出 文件: 活被 init 收养、不是我们的子进程, waitpid 拿不到。
    # ★ 变量名必须 ASCII(dash 不认 状=…, 会 "not found" 且把后头写歪); 两行自描述, 不做空格切分。
    # 起止都让活自己写(shell 整秒口径一致): 混用 Python 浮点起、shell 整秒止, 2 秒的活会记成 1 秒。
    包 = f't0=$(date +%s); ( {命令串} ); rc=$?; {{ echo "$rc"; echo "$t0"; date +%s; }} > {shlex.quote(str(退文))}'
    # ★ 用 nohup ... & 起, 外面那层 sh 立刻退 —— 活被 init 收养:
    #   ① 不跟着这一轮的进程组被一起收  ② 不留僵尸(★ start_new_session 那版会留僵尸,
    #   父进程活着它就永远"还在", os.kill(pid, 0) 对僵尸照样成功 → 等它跑完会等到天荒地老)
    手 = subprocess.Popen(                         # noqa: S603 - 命令是老板/主 agent 自己给的
            f"nohup sh -c {shlex.quote(包)} >> {shlex.quote(str(日))} 2>&1 & echo $!",
        shell=True, cwd=str(根), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, stdin=subprocess.DEVNULL,
    )
    小 = (手.stdout.read() if 手.stdout else "").strip()
    真进程 = int(小) if 小.isdigit() else 手.pid
    手.wait()
    账 = _读()
    账[号] = {
        "号": 号, "说明": 说明, "命令": 命令串,
        "进程": 真进程, "日志": str(日), "退出文件": str(退文), "起于": time.time(),
        "状态": "在跑", "退出码": None, "止于": None,
    }
    _写(账)
    return 号


def _活着(进程: int) -> bool:
    """进程还在不在 —— 认 /proc 的状态位, 不认 os.kill(pid, 0)。

    ★ os.kill(进程, 0) 对**僵尸进程**也成功(pid 还在, 只是无人回收), 用它判活会把"已经跑完"
      判成"还在跑"。Z = 已经完了, 只是父进程还没退、没人收尸。
    """
    if not 进程:
        return False
    try:
        文 = Path(f"/proc/{进程}/stat").read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, ProcessLookupError):
        return False
    后 = 文.rpartition(")")[2].split()
    return not (后 and 后[0] == "Z")


def _收尾(条: dict[str, Any]) -> dict[str, Any]:
    """把一条活收成「跑完/失败」。**可重复调用** —— 收早了也能补。

    ★ 为什么不能一次定死(已踩坑): 进程刚结束、活还没来得及写 .退出 的那一瞬间被收一次,
      状态就成了"跑完·退出码 None"; 之后见到"已收过"直接返回 → 退出码**永久 None**,
      时长还记成"我们看见的时刻"(实测 2 秒的活记成 1 秒)。所以: 退出码没拿到就一直
      允许补收, 结束时刻以活自己写的为准。
    """
    if 条.get("状态") == "在跑":
        进程 = int(条.get("进程") or 0)
        if _活着(进程):
            return 条
        条["状态"] = "跑完"                          # 先按跑完记(退出码可能还没落地), 下面补
        条["止于"] = time.time()
    退, 真起, 真止 = _读退出(条)
    if 退 is not None:
        条["退出码"] = 退
        条["状态"] = "跑完" if 退 == 0 else "失败"
    if 真起:
        条["起于"] = 真起                            # 起止都以活自己写的为准(同一口径)
    if 真止:
        条["止于"] = 真止
    return 条


def _读退出(条: dict[str, Any]) -> tuple[int | None, float | None, float | None]:
    """活自己写下来的「退出码 + 结束时刻」——活被 init 收养, waitpid 拿不到, 只能让它交作业。

    ★ 结束时刻为什么要活自己写: 让它等于「我们去看的时刻」的话, 1 秒的活会被记成 3 秒
      (3 秒后我们才去查)。时长是给人看的, 得是真的。
    """
    文 = Path(str(条.get("退出文件") or ""))
    if not 文.exists():
        return None, None, None
    行 = [x.strip() for x in 文.read_text(encoding="utf-8").splitlines()]
    码 = int(行[0]) if 行 and 行[0].lstrip("-").isdigit() else None
    起 = float(行[1]) if len(行) > 1 and 行[1].isdigit() else None
    止 = float(行[2]) if len(行) > 2 and 行[2].isdigit() else None
    return 码, 起, 止


def 待交付(日志尾行数: int = 8) -> list[dict[str, Any]]:
    """跑完 / 失败、但还没交给主 agent 的活 —— 取待办() 每轮开场把它们取出来。

    ★ 交付是「拉」不是「推」: 活跑完的那一刻没人叫醒主 agent, 所以由下一轮开场去拉。
      进程重启、这一轮没跑, 结果都还在账上, 不会漏。
    """
    账 = _读()
    出: list[dict[str, Any]] = []
    for 号, 条 in list(账.items()):
        新 = _收尾(dict(条))
        账[号] = 新
        if 新.get("状态") in ("跑完", "失败") and not 新.get("已交付"):
            出.append(查(号, 日志尾行数))
    _写(账)
    return 出


def 交掉(号: str) -> None:
    """把这条活标成「已交给主 agent」——交过的下一次不再重复交。"""
    账 = _读()
    if 号 in 账:
        账[号]["已交付"] = True
        账[号]["交付于"] = time.time()
        _写(账)


def 结果话(条: dict[str, Any], 日志尾行数: int = 8) -> str:
    """一条活的结果, 拼成给主 agent 的开场话(它拿这个接着说)。"""
    说 = str(条.get("说明") or 条.get("命令") or "这件活")
    码 = 条.get("退出码")
    头 = f"[作业] {说}（{条.get('状态')}" + (f"·退出码 {码}" if 码 is not None else "") + f"，跑了 {条.get('跑了')}）"
    尾 = str(条.get("日志尾") or "").rstrip()
    return 头 + ("\n  日志尾：\n" + "\n".join("    " + x for x in 尾.splitlines()) if 尾 else "")


def 查(号: str, 日志尾行数: int = 12) -> dict[str, Any]:
    """查看这个活: 状态 + 退出码 + 日志尾（主 agent 以此接着说）。"""
    账 = _读()
    条 = 账.get(号)
    if not 条:
        return {"状态": "没这个活", "退出码": None, "日志尾": ""}
    条 = _收尾(dict(条))
    账[号] = 条
    _写(账)
    尾 = ""
    文 = Path(str(条.get("日志") or ""))
    if 文.exists():
        行 = 文.read_text(encoding="utf-8", errors="replace").splitlines()
        尾 = "\n".join(行[-日志尾行数:])
    秒 = int((条.get("止于") or time.time()) - float(条.get("起于") or 0))
    return {"号": 号, "说明": 条.get("说明"), "命令": 条.get("命令"), "状态": 条.get("状态"),
            "退出码": 条.get("退出码"), "跑了": f"{秒} 秒", "日志尾": 尾}


def 列(算全: bool = True) -> list[dict[str, Any]]:
    """列起过的活。★ 默认跟 查() 同一个形状(带 跑了 / 日志尾) —— web 卡片直接吃这个。

    ★ 之前直接回原始账, 卡片上「跑了」「日志尾」就永远是空的(只有 查() 才算这两个) ——
      界面上表现为右边停在 "跑完 · 退出码 0 ·" 后头空着(2026-10-09 老板截图抓出来)。
    """
    账 = _读()
    for 号, 条 in list(账.items()):
        账[号] = _收尾(dict(条))
    _写(账)
    号们 = sorted(账, key=lambda k: str(账[k].get("起于") or 0))
    return [查(号) for 号 in 号们] if 算全 else [{"号": k, **账[k]} for k in 号们]


def 等(号: str, 每秒: Callable[[float], None] | None = None, 上限秒: float = 0.0) -> dict[str, Any]:
    """等这个活结束(或到上限秒)再返回, 每秒回调一次读秒 —— 「延时等它跑完」就是它。"""
    账 = _读()
    条 = 账.get(号)
    if not 条:
        return {"状态": "没这个活", "退出码": None, "日志尾": ""}
    起于 = time.time()
    while True:
        果 = 查(号)
        if 果["状态"] != "在跑":
            return 果
        等过 = time.time() - 起于
        if 上限秒 and 等过 >= 上限秒:
            果["状态"] = "还在跑(到上限了)"
            return 果
        if 每秒:
            每秒(等过)
        time.sleep(1.0)


def 停(号: str) -> bool:
    """中途放弃: 连同它的整个进程组一起收（另立会话, 否则子进程会变成孤儿）。"""
    账 = _读()
    条 = 账.get(号)
    if not 条 or 条.get("状态") != "在跑":
        return False
    进程 = int(条.get("进程") or 0)
    try:
        os.killpg(os.getpgid(进程), signal.SIGTERM)
    except Exception:                             # noqa: BLE001 - 已经没了就是成功
        return False
    条["状态"] = "停了"
    条["止于"] = time.time()
    账[号] = 条
    _写(账)
    return True



def _交代(果: dict[str, Any]) -> str:
    """命令行给人/agent 看的那一行(不是给机器解析的 JSON)。"""
    if not 果.get("号"):
        return str(果.get("状态") or "没这个活")
    return 结果话(果)


if __name__ == "__main__":
    import argparse

    解 = argparse.ArgumentParser(prog="作业", description="起长活 -> 延时等它跑完 -> 取结果")
    子 = 解.add_subparsers(dest="动作", required=True)
    起解 = 子.add_parser("起", help="把命令丢后台跑, 回一个活号")
    起解.add_argument("命令", help="要跑的脚本/命令(整条用引号包住)")
    起解.add_argument("说明", nargs="?", default="", help="给主 agent 自己看的说明")
    查解 = 子.add_parser("查", help="看状态 / 退出码 / 日志尾")
    查解.add_argument("号")
    等解 = 子.add_parser("等", help="等到它跑完(或到 --上限秒)再返回")
    等解.add_argument("号")
    等解.add_argument("--上限秒", type=float, default=0.0, help="0 = 一直等")
    子.add_parser("列", help="列所有活")
    停解 = 子.add_parser("停", help="半路不要了(连它那一窝一起收)")
    停解.add_argument("号")
    参 = 解.parse_args()

    if 参.动作 == "起":
        print(起(参.命令, 参.说明))
    elif 参.动作 == "查":
        print(_交代(查(参.号)))
    elif 参.动作 == "列":
        for 一条 in 列():
            print(f"  {一条.get('号')}  {一条.get('状态')}  {一条.get('说明') or 一条.get('命令')}")
    elif 参.动作 == "等":
        果 = 等(参.号, 每秒=lambda 过: print(f"  等了 {过:.0f} 秒...", flush=True), 上限秒=参.上限秒)
        print(_交代(果))
    elif 参.动作 == "停":
        print("停了" if 停(参.号) else "没在跑")

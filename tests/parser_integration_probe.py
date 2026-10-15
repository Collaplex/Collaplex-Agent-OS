"""解析层真机集成测试 —— 起临时端口的 web、真模型跑一轮、真 SSE、真记账。

★ 为什么要有它：解析层（`解析器/`）的样本自测与既有回归都是**离线**的，
  而"最终正文是谁产出的"这件事只有**真跑**才看得出来 —— 实测就是这么抓到
  **exec 支路**（左链判定要动手 → 递交 exec）压根没过解析层，模型回的那份汇总
  带着末尾 json 一路糊进正文与存档（那一轮 886 字里 192 字之后全是 json）。

跑法：`./.venv/bin/python tests/parser_integration_probe.py ["<问句>"]`
  · 缺省问句是闲聊（走主 agent 自答那条路）；**要验 exec 支路就传一句要动手的**
    （例：「用 df 查看本机磁盘还剩多少空间，一句话说结果」）—— 两条支路各跑一次才算验完。
  · 临时端口默认 8792（**不碰老板的 8791**）；跑完只收 8792 的监听方
    （★ 不 fuser -k -n tcp —— 那会连自己的浏览器一起杀）。

三条判据（任何一条不成立就红）：
  ① 正文非空
  ② `"```json"` / `"任务结束"` **没漏进正文**（末尾那段 json 被解析层拦住了）
  ③ `state/web-对话.jsonl` 行数 **+1**（真记了账）
另附一条确定性复现：把「整段回答被包进 json 围栏」注入 `bridge.流式自答` 的真代码路径，
  final 要取回原句、并带一条说明。
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

项目 = Path(__file__).resolve().parent.parent
端口 = int(os.environ.get("解析探针端口") or 8792)
存档 = 项目 / "state" / "web-对话.jsonl"
失败: list[str] = []


def 数存档() -> int:
    return len(存档.read_text(encoding="utf-8").splitlines()) if 存档.exists() else 0


def 等端口(超时: float = 25.0) -> bool:
    末 = time.time() + 超时
    while time.time() < 末:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", 端口)) == 0:
                return True
        time.sleep(0.5)
    return False


def 收监听pid() -> int | None:
    出 = subprocess.run(["ss", "-ltnp", f"sport = :{端口}"], capture_output=True, text=True).stdout
    for 段 in 出.replace("=", " ").split():
        if 段.startswith("pid="):
            return int(段[4:].split(",")[0])
    return None


def 打一轮(问: str) -> tuple[str, list[str], list[str]]:
    """真 POST /api/ask，把 SSE 里的事件收齐。返回 (正文, 说明们, 事件种类)。"""
    体 = json.dumps({"问": 问}).encode()
    请 = urllib.request.Request(
        f"http://127.0.0.1:{端口}/api/ask", data=体,
        headers={"Content-Type": "application/json"},
    )
    正文 = ""
    说明: list[str] = []
    种类: list[str] = []
    with urllib.request.urlopen(请, timeout=300) as 响:
        for 行 in 响:
            行 = 行.decode("utf-8", "replace").strip()
            if not 行.startswith("data:"):
                continue
            try:
                件 = json.loads(行[5:].strip())
            except json.JSONDecodeError:
                continue
            种 = str(件.get("kind") or "")
            种类.append(种)
            if 种 == "answer":
                正文 += str(件.get("text") or "")
            elif 种 == "final":
                正文 = str(件.get("text") or "")
            elif 种 in ("note", "error"):
                说明.append(str(件.get("text") or ""))
    return 正文, 说明, 种类


class _增:
    def __init__(self, 文: str) -> None:
        self.content = 文
        self.reasoning_content = None


class _芯:
    def __init__(self, 文: str) -> None:
        self.delta = _增(文)


class _块:
    def __init__(self, 文: str) -> None:
        self.choices = [_芯(文)]
        self.usage = None


class _流:
    def __init__(self, 文: str) -> None:
        self.文 = 文

    def __iter__(self) -> Any:
        yield _块(self.文)


class _假创:
    def __init__(self, 文: str) -> None:
        self.文 = 文

    def create(self, **_件: Any) -> _流:
        return _流(self.文)


def 整段围栏复现() -> None:
    """确定性复现：模型把整段回答放进 ```json 围栏 —— 走 bridge 真代码路径。"""
    sys.path.insert(0, str(项目))
    sys.path.insert(0, str(项目 / "web"))
    import bridge

    class 假聊:
        completions = _假创("")

    class 假客:
        chat = 假聊()

    原文 = "```json\n{\"回答\": \"作业要交三样：① 展开图 ② 立体照片 ③ 细节照片\", \"任务结束\": true}\n```"
    假客.chat.completions = _假创(原文)
    事件 = list(bridge.流式自答(假客(), "假模型", "提示词", "问", {}))
    终 = [e for e in 事件 if e.get("kind") == "final"]
    说明 = [e for e in 事件 if e.get("kind") == "note"]
    正文 = str(终[0].get("text") or "") if 终 else ""
    print(f"    kind: {[e.get('kind') for e in 事件]}")
    print(f"    final 正文: {正文!r}")
    print(f"    说明: {[e.get('text') for e in 说明]}")
    if not 正文.strip():
        失败.append("整段围栏场景: final 正文还是空的（静默消失没堵住）")
    if "展开图" not in 正文:
        失败.append("整段围栏场景: 没把 json 里的内容捞出来")
    if not 说明:
        失败.append("整段围栏场景: 没给说明（界面上看不出走过兜底）")


def 主() -> int:
    问 = sys.argv[1] if len(sys.argv) > 1 else "用一句话回答：你叫什么名字？"
    行前 = 数存档()
    print(f"[存档] 打之前 {行前} 行 · 问句：{问}")

    日志路径 = 项目 / "logs" / f"解析探针-{端口}.log"
    日志 = 日志路径.open("wb")
    服 = subprocess.Popen(
        [str(项目 / ".venv" / "bin" / "python"), "-m", "web.server", "--端口", str(端口)],
        cwd=str(项目), stdout=日志, stderr=subprocess.STDOUT, start_new_session=True,
    )
    try:
        if not 等端口():
            失败.append("web 没起在临时端口")
            print("[起服务] ✗ 25 秒没起来，日志尾巴：")
            print(日志路径.read_text(encoding="utf-8", errors="replace")[-800:])
            return 1
        print(f"[起服务] ✓ 临时端口 {端口} 起来了 (pid={服.pid})")

        print("[真跑一轮] 真模型 / 真 SSE / 真记账 …")
        正文, 说明, 种类 = 打一轮(问)
        print(f"    SSE 事件种类: {sorted(set(种类))}")
        print(f"    正文 {len(正文)} 字: {正文[:160]!r}")
        print(f"    过程里的说明: {说明}")

        if not 正文.strip():
            失败.append("真跑一轮: 正文是空的")
        if "```json" in 正文 or "任务结束" in 正文:
            失败.append("真跑一轮: 末尾那段 json 标记漏进正文了（解析层没拦住）")
        行后 = 数存档()
        print(f"[存档] 打之后 {行后} 行")
        if 行后 != 行前 + 1:
            失败.append(f"真跑一轮: 存档没 +1（{行前} → {行后}）")

        print("[确定性复现] 整段回答被包进 json 围栏（走 bridge 真路径）")
        整段围栏复现()
    finally:
        服.send_signal(signal.SIGTERM)
        time.sleep(1.5)
        pid = 收监听pid()
        if pid:
            os.kill(pid, signal.SIGKILL)      # ★ 只杀这个端口的监听方
        print(f"[收服务] {端口} 监听方: {'已收掉' if not 收监听pid() else '还在（要人工看）'}")
        日志.close()

    print()
    if 失败:
        print("失败:")
        for 一 in 失败:
            print(f"  ✗ {一}")
        return 1
    print("✓ 真机集成测试全过（真模型一轮 + 整段围栏复现 + 记账 +1）")
    return 0


if __name__ == "__main__":
    raise SystemExit(主())

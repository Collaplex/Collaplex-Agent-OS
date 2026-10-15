"""用真 agent 完整跑几轮 —— 这一轮的重点是走新做的 vision skill(看图)。

四轮:
  R1 该看:     给一张真截图, 问图上写着什么 -> 看它会不会自己走 看图(主路云端)
  R2 顺着看:   先让它去搜, 再看截图 -> 看 search 那条支路("只回截图")能不能接上 看图
  R3 不该看:   一道算数 -> 验证路由不串(vision 不该抢 math 的活)
  R4 看不到:   给一张不存在的图 -> 看它会不会照实说(不编图里有什么)

★ 看图这条链上要跑命令(云端请求 3~10s; 本地兜底 38s/张), 所以 quiet_for 不能小 ——
  上一版 search 的 probe 用 15 秒误判过"这轮完了", 把整条 exec 链的输出丢了(证据在
  logs/exec/ 里)。这一版 45 秒静默 + 单轮上限 240 秒。

输出: 每轮的原始 REPL 输出(不加工) + 本轮耗时 + 汇总。
另有 logs/exec/<时间>-NN.txt 记着每一步真跑的命令与回显。
"""

import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path

ROOT = "/home/lou/桌面/collaplex_agent"
WAIT_BETWEEN = 45.0


def 找一张真截图() -> str:
    """从 search 的截图缓存里挑最新的一张当样本 (没有就报错退出)."""
    目录 = Path(ROOT) / "skill" / "search" / "cache" / "shots"
    图们 = sorted(目录.glob("*.jpg"), key=lambda 件: 件.stat().st_mtime, reverse=True)
    if not 图们:
        print(f"[探针] {目录} 里没有截图 —— 先跑一轮 search(要它出网取页), 或手动放一张进去", flush=True)
        raise SystemExit(2)
    return str(图们[0])


def main() -> int:
    样本 = 找一张真截图()
    没有的图 = "/home/lou/.hermes/cache/scratch/根本没有这张图.png"

    turns: list[tuple[str, str]] = [
        ("R1", f"看一眼 {样本} 这张图, 页面上最显眼的标题写的是什么? 出处就说这张图"),
        ("R2", "上网搜一下 浙江工业职业技术学院 的官网, 如果取回来的正文没什么内容, 就看看那张截图里写了什么"),
        ("R3", "算一下 3 乘 7 等于多少"),
        ("R4", f"看一眼 {没有的图} 里面写了什么"),
    ]
    print(f"[探针] 样本图: {样本}\n", flush=True)

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [f"{ROOT}/.venv/bin/python", "main.py"],
        cwd=ROOT,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave)
    buffer = ""

    def drain(seconds: float, quiet_for: float = 45.0) -> str:
        """读输出直到"安静 quiet_for 秒"(或总时长 seconds 到点).

        quiet_for 不能小: 执行链上要真去跑命令(一次模型请求 + 图上编码), 安静几十秒不等于这轮完了.
        """
        nonlocal buffer
        got = ""
        deadline = time.time() + seconds
        last_output = time.time()
        while time.time() < deadline:
            ready, _, _ = select.select([master], [], [], 0.5)
            if not ready:
                if got and time.time() - last_output >= quiet_for:
                    break
                continue
            try:
                chunk = os.read(master, 65536).decode("utf-8", "replace")
            except OSError:
                break
            got += chunk
            last_output = time.time()
        buffer += got
        return got

    drain(8.0)  # 等启动
    log: list[str] = []
    for label, question in turns:
        print(f"\n{'=' * 20} {label} 问: {question}", flush=True)
        started = time.time()
        os.write(master, (question + "\n").encode("utf-8"))
        out = drain(240.0)
        spent = time.time() - started
        print(out, flush=True)
        log.append(f"{label}\t{spent:.0f}s\t{question}")

        if label != turns[-1][0]:
            print(f"\n---- 等 {WAIT_BETWEEN:.0f} 秒(让清洗管线有机会动手) ----", flush=True)
            time.sleep(WAIT_BETWEEN)
            drain(2.0)

    os.write(master, b"exit\n")
    drain(3.0)
    # 收干净: start_new_session 起了新进程组, 光 terminate() 杀不掉 REPL 本体
    try:
        os.killpg(os.getpgid(proc.pid), 15)
    except OSError:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except OSError:
            proc.kill()
    print("\n==== 汇总 ====", flush=True)
    for row in log:
        print("  " + row, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

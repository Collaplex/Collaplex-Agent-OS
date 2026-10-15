"""多轮问答 + 记忆召回 真跑探针 —— 自己驱动 REPL(工具写不进中文, 用 pty)。

四轮设计(每轮之间等 75 秒, 跨过清洗管线的窗口):
  T1 普通问答(不入库路径): 说一个事实
  T2 追问那个事实        -> 看能不能召回
  T3 触发 exec(会入二层): 让 math 算个数
  T4 追问 T3 的结果      -> 看能不能召回

输出: 每轮的 [子agent] 简报(记忆条数) + 回答 + 本轮耗时。
"""

import os
import pty
import select
import subprocess
import sys
import time

ROOT = "/home/lou/桌面/collaplex_agent"
WAIT_BETWEEN = 75.0

TURNS: list[tuple[str, str]] = [
    ("T1", "记一下：我下个月的房租是 2500 元"),
    ("T2", "我刚说的房租是多少？"),
    ("T3", "算一下 2500 乘 12 等于多少"),
    ("T4", "刚才算的那个数再乘 2 是多少？"),
]


def main() -> int:
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

    def drain(seconds: float, quiet_for: float = 15.0) -> str:
        """读输出直到"安静 quiet_for 秒"(或总时长 seconds 到点)。

        ★ quiet_for 不能小: 模型生成时本来就有几秒空档(执行链上还要跑命令),
        0.4 秒没输出就当"这轮完了"会把整条 exec 链截掉(实测每轮只等到 2 秒)。
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

    drain(6.0)  # 等启动
    log: list[str] = []
    for label, question in TURNS:
        print(f"\n{'=' * 20} {label} 问: {question}", flush=True)
        started = time.time()
        os.write(master, (question + "\n").encode("utf-8"))
        out = drain(150.0)
        spent = time.time() - started
        print(out, flush=True)
        log.append(f"{label}\t{spent:.0f}s\t{question}")

        if label != TURNS[-1][0]:
            print(f"\n---- 等 {WAIT_BETWEEN:.0f} 秒(让清洗管线有机会动手) ----", flush=True)
            time.sleep(WAIT_BETWEEN)
            drain(2.0)

    os.write(master, b"exit\n")
    drain(3.0)
    # ★ 收干净: start_new_session 起了新进程组, 光 terminate() 杀不掉 REPL 本体
    #   (实测留下 150245/154159 两个孤儿 REPL 占着模型与状态文件)
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

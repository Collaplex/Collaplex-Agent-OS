"""用真 agent 完整跑几轮 —— 这一轮的重点是走新做的 search skill(真出网闭环)。

四轮(每轮之间等 60 秒, 让清洗管线有机会动手):
  R1 触发 search: 让它真出网搜一所学校 -> 看能不能自己走 热库 / 搜 / 取 / 正文
  R2 指代追问:   "刚才那所…" -> 看这一轮的会话上下文能不能接上(不靠检索)
  R3 给具体网址: 让它打开并说清这页是什么 -> 看 取 + 正文 这条
  R4 换 skill(算数): 验证路由不串 —— search 不该抢 math 的活

★ 取页要真起浏览器(2~4s 起步, 中间还有整段没有输出), 所以 quiet_for 不能小:
  上一版用 15 秒, 结果\"正在执行…\"之后被判成\"这轮完了\", 整条 exec 链的输出全丢了
  (那条链其实跑得好好的: 热库 -> 取 百度百科, 200, 14878 字, 截图落盘 ——
   证据在 logs/exec/<时间>-NN.txt 里)。这一版 45 秒, 单轮上限 240 秒。

输出: 每轮的原始 REPL 输出(不加工) + 本轮耗时 + 汇总。
另有 logs/exec/<时间>-NN.txt 记着每一步真跑的命令与回显。
"""

import os
import pty
import select
import subprocess
import sys
import time

ROOT = "/home/lou/桌面/collaplex_agent"
WAIT_BETWEEN = 60.0

TURNS: list[tuple[str, str]] = [
    ("R1", "上网搜一下 浙江工业职业技术学院, 看看这所学校在哪个城市, 把出处链接也给我"),
    ("R2", "刚才你搜的那所学校, 它官网的网址是什么?"),
    ("R3", "打开 https://www.zjipc.com/ 看看这页主要写了什么"),
    ("R4", "算一下 3 乘 7 等于多少"),
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

    def drain(seconds: float, quiet_for: float = 45.0) -> str:
        """读输出直到\"安静 quiet_for 秒\"(或总时长 seconds 到点)。

        quiet_for 不能小: 执行链上要真去跑命令(出网 + 起浏览器), 安静几十秒不等于这轮完了。
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
    for label, question in TURNS:
        print(f"\n{'=' * 20} {label} 问: {question}", flush=True)
        started = time.time()
        os.write(master, (question + "\n").encode("utf-8"))
        out = drain(240.0)
        spent = time.time() - started
        print(out, flush=True)
        log.append(f"{label}\t{spent:.0f}s\t{question}")

        if label != TURNS[-1][0]:
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

"""流式渲染的回归测试 —— 逐字符喂, 看"实时"到底有没有丢。

★ 这个 bug 反复出现在同一个地方: 渲染器要扣着"可能是末尾 json 围栏"的那一行,
但**判据一宽(比如"这行里有反引号")就会把整段回答扣着不打** —— 用户看到的是
"实时输出没了", 等答完一次性糊出来。所以这里量的不是"最后打全了没", 而是
**最长的一次卡顿**(喂了多少字还一个字没吐)。
"""

import io
import pathlib
import re
import sys
from collections.abc import Iterable

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import main  # noqa: E402  (要在 sys.path 里插了项目根之后再导)

ANSI = re.compile(r"\033\[[0-9;]*m")

# 反引号密集的回答(实测老板那两问就是这种) + 末尾那段 json
BACKTICK_HEAVY = (
    "桌面上有 9 个条目：**6 个目录 + 3 个文件**。\n\n"
    "**目录**：\n"
    "- `Revelation`、`collaplex_agent`、`demo`、`llama.cpp`、`vllm`、`工作区`\n\n"
    "**文件**：\n"
    "- `collaplex_agent.7z`（约 47 MB，最大的一个）\n"
    "- `demo.txt`（1.6 KB）\n"
    "- `口令.md`（386 B）\n\n"
    "```json\n"
    '{"任务结束": true}\n'
    "```\n"
)

# 正文里自带代码块 + 末尾 json: 代码块要打出来, json 不许漏
WITH_CODE_BLOCK = (
    "查完是这样：\n\n"
    "```bash\n"
    "ss -ltnp | grep 8899\n"
    "```\n\n"
    "进程名与 pid 都在里面，端口是 8899。\n\n"
    "```json\n"
    '{"任务结束": true}\n'
    "```\n"
)

# 模型偶尔在真围栏前面多吐一个空围栏: 那行也不许漏
STRAY_FENCE = "就这样。\n\n```\n```json\n" '{"任务结束": true}\n' "```\n"

PLAIN = "1 加 1 等于 2。\n"

# ⑤ 模型把**整段回答**套进 ```json 里 —— 这一种原来会变成"空答案", 界面上只剩过程行、
#    存档也不落这条(2026-10-11 老板撞上, 原话"坏了又是bug")。不许再静默。
ALL_JSON = (
    "```json\n"
    '{"回答": "作业要交：电子展开图 1 张（源文件+JPG）、手绘展开图照片 1 张、立体照片 3 个角度", '
    '"任务结束": true}\n'
    "```\n"
)


def render(answer: str) -> tuple[str, list[tuple[int, int]]]:
    """逐字符喂进去, 返回 (打到终端的东西, [(已喂字数, 已打出字数), ...])。"""
    fed = 0
    marks: list[tuple[int, int]] = []

    class Spy(io.StringIO):
        def write(self, text: str) -> int:
            written = super().write(text)
            marks.append((fed, len(self.getvalue())))
            return written

    spy = Spy()

    def chunks() -> Iterable[tuple[str, str]]:
        nonlocal fed
        for char in answer:
            fed += 1
            yield "answer", char

    real_stdout = sys.stdout
    sys.stdout = spy
    try:
        main.render_stream(chunks())
    finally:
        sys.stdout = real_stdout
    return spy.getvalue(), marks


def plain(text: str) -> str:
    return ANSI.sub("", text)


def max_stall(marks: list[tuple[int, int]]) -> int:
    """最长的一次卡顿: 这段时间里一个字都没往终端吐。"""
    worst = 0
    printed_seen = 0
    last_grow_at = 0
    for fed, printed in marks:
        if printed > printed_seen:
            printed_seen = printed
            last_grow_at = fed
        else:
            worst = max(worst, fed - last_grow_at)
    return worst


def main_() -> int:
    failures: list[str] = []

    # ① 反引号密集: json 不许漏 + 不许整段扣着不打
    visible, marks = render(BACKTICK_HEAVY)
    shown = plain(visible)
    if "任务结束" in shown or '{"' in shown:
        failures.append("① 末尾那段 json 漏到终端上了")
    body = BACKTICK_HEAVY[: BACKTICK_HEAVY.index("```json")].rstrip("\n")
    if body not in shown:
        failures.append("① 正文没打全")
    stall = max_stall(marks)
    if stall > 60:
        failures.append(f"① 最长卡顿 {stall} 字 —— 又整段扣着不打了(修前就是这个症状)")
    if len(marks) < 8:
        failures.append(f"① 只打印了 {len(marks)} 次, 不是流式")

    # ② 正文里的代码块要打出来(不能当成尾巴 json 误吞)
    visible2, _ = render(WITH_CODE_BLOCK)
    shown2 = plain(visible2)
    if "ss -ltnp | grep 8899" not in shown2:
        failures.append("② 正文里的代码块被误吞了")
    if "任务结束" in shown2:
        failures.append("② json 漏了")

    # ③ 多吐的空围栏不许漏
    visible3, _ = render(STRAY_FENCE)
    shown3 = plain(visible3)
    if "任务结束" in shown3:
        failures.append("③ json 漏了")
    if "```" in shown3:
        failures.append(f"③ 多吐的空围栏漏出来了: {shown3!r}")

    # ④ 没有 json 的回答: 一个字都不能少
    visible4, _ = render(PLAIN)
    if "1 加 1 等于 2。" not in plain(visible4):
        failures.append("④ 普通回答没打全")

    # ⑤ 整段被围栏吞掉(模型把回答写进 json 块) —— 不许变成空答案、不许不交代
    可见五, _ = render(ALL_JSON)
    正文五, 说明五 = main.捞正文(ALL_JSON)
    if not 正文五.strip():
        failures.append("⑤ 整段围栏时正文又是空串 —— 又静默丢一轮")
    if "作业要交" not in 正文五:
        failures.append(f"⑤ 没从 json 里把内容捞出来：{正文五!r}")
    if not 说明五:
        failures.append("⑤ 走了兜底却没给说明(界面/终端看不到交代)")
    if "作业要交" not in plain(可见五):
        failures.append("⑤ 终端上一个字都没补出来")
    正文六, 说明六 = main.捞正文(BACKTICK_HEAVY)
    if "任务结束" in 正文六 or "```json" in 正文六:
        failures.append("⑥ 正常回答里那段 json 没被切掉")
    if 说明六:
        failures.append("⑥ 正常回答不该走兜底")
    正文七, 说明七 = main.捞正文(PLAIN)
    if 正文七.strip() != PLAIN.strip() or 说明七:
        failures.append("⑦ 普通回答被兜底搅了")

    if failures:
        print("✗ 流式渲染回归:")
        for item in failures:
            print("   -", item)
        return 1

    print(f"✓ 流式渲染 7/7 (反引号密集那题最长卡顿 {max_stall(marks)} 字; 整段围栏也捞得回正文)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_())

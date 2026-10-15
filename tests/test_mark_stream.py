"""协议标记的**边流边吐**回归 —— 逐片喂, 看标记会不会从片段缝里漏进正文区。

★ 这个 bug 的形状(2026-10-09 web 上真出的):
    web 的正文区先是"跑着时露一串原始md"(`<调用>find . -name '*.py' …` 整条命令), 一刀改成
    "跑的时候不写正文, 只在 final 一次成型" —— 结果又变成"流式输出没了"。
    两头都不对: 该做的是**边流边把人话吐出去, 协议块整段扣住**。
    逐片 strip 做不到(片段边界会把标记切在两半, 单看哪一片都不成标记), 所以判据落在
    native_marks.StreamFilter: 每次拿"攒到现在的全量"重扫一遍 —— 完整块整段跳过,
    开了头没闭合的就停在那等下一片。

这里量四条(片长 1/3/7/13 各跑一次):
    ① 标记块里的命令/参数一个字都不许漏进正文区
    ② 块前后的人话一片都不许丢, 顺序不乱也不重复
    ③ 吐出来的正文 == 落语料那套 strip_all_calls 的结果(两处判据不许分叉)
    ④ 不带标记的普通回答逐字喂必须原样吐完 —— 防"怕漏标记就把整段扣着不打"那个病
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import native_marks  # noqa: E402  (要在 sys.path 里插了项目根之后再导)

VBAR = "\uff5c"  # ｜
LOW = "\u2581"   # ▁
M = "\uff5c\uff5cDSML\uff5c\uff5c"

# ① 自家: exec 那轮"边想边说"的草稿 —— 前面一段人话, 中间整块工具调用, 后面接着人话
自家形 = (
    "先数一遍行数再挑最大的。\n"
    "<调用>find . -name '*.py' -print0 | xargs -0 wc -l | grep -v ' total$'"
    " | sort -rn | head -5</调用>"
    "命令跑完了, 结果里 sub_agent.py 最大, 1404 行。"
)

# ② 小米 MiMo: <tool_call><parameter=command>…</parameter></tool_call>
米莫形 = (
    "我来查一下。\n"
    "<tool_call>\n<parameter=command>ls -la /home/lou</parameter>\n</tool_call>\n"
    "看到了, 目录里有 9 个条目。"
)

# ③ DeepSeek DSML: 标记本体 = 全角竖线×2 + DSML + 全角竖线×2, 后头紧跟标签名(实测形状)
DSML形 = (
    "先看看目录。\n"
    "<" + M + "tool_calls>\n"
    "<" + M + 'invoke name="execute_command">\n'
    "<" + M + 'parameter name="command" string="true">ls -la</' + M + "parameter>\n"
    "</" + M + "invoke>\n"
    "</" + M + "tool_calls>\n"
    "命令跑完了, 目录里 9 个条目。"
)

# ④ DeepSeek 官方 chat_template: <｜tool▁call▁begin｜>function<｜tool▁sep｜>bash + ```json …```
官方形 = (
    "查一下。\n"
    f"<{VBAR}tool{LOW}calls{LOW}begin{VBAR}><{VBAR}tool{LOW}call{LOW}begin{VBAR}>"
    f"function<{VBAR}tool{LOW}sep{VBAR}>bash\n"
    '```json\n{"command": "ls -la"}\n```\n'
    f"<{VBAR}tool{LOW}call{LOW}end{VBAR}><{VBAR}tool{LOW}calls{LOW}end{VBAR}>\n"
    "好了, 9 个条目。"
)

样例 = [
    ("自家", 自家形, "先数一遍行数再挑最大的", "命令跑完了, 结果里 sub_agent.py 最大, 1404 行。"),
    ("米莫", 米莫形, "我来查一下", "看到了, 目录里有 9 个条目。"),
    ("DSML", DSML形, "先看看目录", "命令跑完了, 目录里 9 个条目。"),
    ("官方", 官方形, "查一下", "好了, 9 个条目。"),
]

# 正文区里不许出现的字眼: 命令本体 + 各家标记的零件
禁止出现在正文 = [
    "<调用>", "</调用>", "<tool_call", "DSML", VBAR, LOW,
    "ls -la", "find .", "xargs", "parameter", "invoke", "tool_calls", "```", "function",
]

# 不带标记的普通回答: 逐字喂必须原样吐出(第 ④ 条判据的样本)
普通回答 = (
    "本地小模型做 agent，核心是用能力换自主权。\n\n"
    "好处是数据不出机器、延迟低、可离线；代价是智力天花板明显，多步推理容易翻车。\n"
    "- 小模型管路由、清洗、格式化\n"
    "- 难题上抛给云端大模型\n"
)


def 逐片喂(全文: str, 片长: int) -> tuple[str, list[int]]:
    """按固定片长喂, 返回(吐出来的总正文, 每片吐出多少字)."""
    滤 = native_marks.StreamFilter()
    出: list[str] = []
    每片出字: list[int] = []
    for 起 in range(0, len(全文), 片长):
        t = 滤.feed(全文[起 : 起 + 片长])
        出.append(t)
        每片出字.append(len(t))
    出.append(滤.flush())
    return "".join(出), 每片出字


def 最长卡顿(每片出字: list[int], 片长: int) -> int:
    """连着多少片一个字没吐(折成字数) —— 就是"实时输出断流"的时长."""
    最长 = 当前 = 0
    for n in 每片出字[:-1]:  # flush 那一片不算
        if n == 0:
            当前 += 片长
            最长 = max(最长, 当前)
        else:
            当前 = 0
    return 最长


def main_() -> int:
    过 = 0
    总 = 0

    for 名, 全文, 人头, 人尾 in 样例:
        参照 = native_marks.strip_all_calls(全文)  # 落语料那套判据 = 期望的正文
        for 片长 in (1, 3, 7, 13):
            总 += 1
            吐, _ = 逐片喂(全文, 片长)
            问题: list[str] = []
            漏 = [w for w in 禁止出现在正文 if w in 吐]
            丢 = [w for w in (人头, 人尾) if w not in 吐]
            if 漏:
                问题.append(f"漏了 {漏}")
            if 丢:
                问题.append(f"丢了 {丢}")
            if 吐.strip() != 参照.strip():
                问题.append(f"与 strip_all_calls 分叉: {吐!r} != {参照!r}")
            if 问题:
                print(f"✗ {名} 片长{片长}: " + "; ".join(问题))
            else:
                过 += 1

    # ④ 无标记的普通回答: 逐字喂必须原样吐完, 且不许有长卡顿
    for 片长 in (1, 3, 7):
        总 += 1
        吐, 每片 = 逐片喂(普通回答, 片长)
        if 吐 != 普通回答:
            印 = 吐.replace("\n", "⏎")
            print(f"✗ 无标记正文 片长{片长}: 吐回 {印[:60]}… (原样 {len(普通回答)} 字, 吐了 {len(吐)} 字)")
        elif 最长卡顿(每片, 片长) > 24:
            print(f"✗ 无标记正文 片长{片长}: 最长卡顿 {最长卡顿(每片, 片长)} 字(该 ≤ 24)")
        else:
            过 += 1

    if 过 == 总:
        print(f"✓ 协议标记边流边吐 {过}/{总}")
        return 0
    print(f"✗ 协议标记边流边吐 {过}/{总}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main_())

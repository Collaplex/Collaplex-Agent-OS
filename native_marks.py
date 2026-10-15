#!/usr/bin/env python3
"""各家模型的原生工具调用标记 —— 一处识别齐全, 无论命令提取还是语料写入都由它挡一道.

为什么单独一个模块
    它要被三层用, 而这三处分属不同目录:
      · exec_agent.py                           命令提取(把"它说要跑的命令"接过来)
      · sub_agent.save_to_tier2                 落语料(任务产出写成 corpus 里的 md)
      · skill/rag/scripts/import_hermes_hist.py 把 Hermes 会话导出成语料
    后面那个脚本只补一条 sys.path 就能 import 这里。所以本文件**只放纯正则, 零依赖**
    —— 免得给一个导出脚本拖进 dotenv/openai 那一整串。

认哪几家 (都是实测出来的, 不是照文档抄的)
    ① 本项目约定  <调用>命令</调用>
    ② 小米 MiMo   <tool_call><parameter=command>…</parameter></tool_call>
    ③ DeepSeek    DSML —— 标记本体 = 全角竖线×2 + DSML + 全角竖线×2。
       (它 tokenizer 里那个单 token 是"全角竖线包着 DSML", 模型吐成正文时两侧各多一个全角竖线)
       ★ 实测三种形状, 三种都要认 / 都要清:
         a) 成对的 tool_calls 块 (parameter 里装着命令; 名字不一定叫 command)
         b) 只有半截闭合标记(没有开标签) —— 最常撞见的形状, 它会把正文尾部吞掉
         c) <调用> 没收尾、后面直接跟 DSML 标记 —— 2026-10-09 老板看到"炸了"的那一次
    ④ DeepSeek 官方模板 —— 模型自己那份 tokenizer_config.json 的 chat_template 里, 官方渲染
       工具调用用的是另一串标记(和 DSML 不是一个东西):
           <｜Assistant｜><｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function<｜tool▁sep｜>名字
           ```json
           {"command": "..."}
           ```<｜tool▁call▁end｜><｜tool▁calls▁end｜>
       ★ 2026-10-09: 照模板原文造样本喂给我们自己的parser —— 一条命令都提取不出、一个标记都清不掉,
         跟 DSML 那次同形的坑, 所以补上。清的时候按整族 token 清(<｜…｜> 与 <|…|>)。

★ 为什么非要清: 这不是"当轮好不好看"的问题。这些标记会随产出落进语料, 检索再把它喂回上下文,
  模型看见自己的标记就跟着模仿 —— 污染会自我扩散。所以**写语料的每一处**都要过
  strip_all_calls()。

★ 标记只在源码里用转义拼(\uff5c), 不让不可见字符直接出现在源文件中。
"""

from __future__ import annotations

import json
import re
from typing import Any, cast

# ---- 标记的原子 (全角竖线 ｜ 与词内分隔 ▁ 都用转义拼, 不让不可见字符躺进源文件) ----
_VBAR = "\uff5c"  # ｜ 各家都拿它当括号
_LOW = "\u2581"  # ▁  官方长名字里的分隔符
# ③ DeepSeek 的标记本体 —— 全角竖线×2 + DSML + 全角竖线×2。
DSML = "\uff5c\uff5cDSML\uff5c\uff5c"
# ③ 方言的标签有两种外壳, 都在它 tokenizer 里备着:
#   a) ｜｜DSML｜｜  (实测外泄的就是这种)
#   b) dsml:       (tokenizer 里躺着 <dsml: 与 </dsml: 两个 token —— 同族另一种写法)
_DSML_HEAD = "(?:" + DSML + "|dsml:)"
# 任何一家的标记开头 —— 半截 <调用> 就是靠它识别"收尾被谁顶掉了"
_ANY_MARK_HEAD = "(?:" + _DSML_HEAD + "|" + _VBAR + ")"


def _mark(name: str) -> str:
    """官方标记的字面量 <｜名字｜>."""
    return "<" + _VBAR + name + _VBAR + ">"


# ============ ① 本项目约定 ============
OWN_CALL_PATTERN = re.compile(r"<调用>(.*?)</调用>", re.DOTALL)
# 半截 <调用>: 收尾被别家的标记顶掉了 —— 语料里实测就是这个形状。命令照收, 正文里也一并清掉。
OWN_UNCLOSED_PATTERN = re.compile(r"<调用>(.*?)(?=</?" + _ANY_MARK_HEAD + r"|\Z)", re.DOTALL)

# ============ ② 小米 MiMo ============
MIMO_CALL_PATTERN = re.compile(r"<tool_call>.*?</tool_call>", re.DOTALL)
MIMO_COMMAND_PATTERN = re.compile(r"<parameter=command>\s*(.*?)\s*</parameter>", re.DOTALL)

# ============ ③ DeepSeek 的 DSML ============
# 标签外壳见上文 _DSML_HEAD(两种都认)。
# 闭合名字放宽成 (tool_)?calls —— 实测两种都见过(块头写 tool_calls, 收尾却写 calls)。
DSML_CALLS_PATTERN = re.compile(
    "<" + _DSML_HEAD + r"tool_calls>(.*?)</" + _DSML_HEAD + r"(?:tool_)?calls>", re.DOTALL
)
DSML_PARAM_PATTERN = re.compile(
    "<" + _DSML_HEAD + r'parameter\b[^>]*name="?([A-Za-z_.\-]+)"?[^>]*>(.*?)</' + _DSML_HEAD + r"parameter>",
    re.DOTALL,
)
DSML_TAG_PATTERN = re.compile("</?" + _DSML_HEAD + r"[^>]*>")

# ============ ④ DeepSeek 官方 chat_template 那套 ============
# 出处: 模型自己那份 tokenizer_config.json 里的 chat_template —— 官方渲染工具调用就用这串标记:
#     <｜Assistant｜><｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function<｜tool▁sep｜>run_command
#     ```json
#     {"command": "ls -la"}
#     ```<｜tool▁call▁end｜><｜tool▁calls▁end｜>
# ★ 2026-10-09 拿官方模板原文喂给我们自己的parser: 一条命令都提取不出、一个标记都清不掉 ——
#   和 DSML 那次一模一样的坑, 所以补上。字面量用 _mark() 拼(竖线/▁ 都走转义)。
# 名字里只可能出现 字母/数字/下划线 与 ▁ 分隔符 —— 照 tokenizer.json 的 added_tokens 抄的
OFFICIAL_TOKEN_PATTERN = re.compile(
    "<" + _VBAR + r"[A-Za-z0-9_]*(?:" + _LOW + r"[A-Za-z0-9_]+)*" + _VBAR + ">"
)
OFFICIAL_ASCII_TOKEN_PATTERN = re.compile(r"<\|[A-Za-z0-9_]+\|>")
OFFICIAL_CALLS_BLOCK_PATTERN = re.compile(
    _mark("tool" + _LOW + "calls" + _LOW + "begin") + ".*?" + _mark("tool" + _LOW + "calls" + _LOW + "end"),
    re.DOTALL,
)
OFFICIAL_CALL_BLOCK_PATTERN = re.compile(
    _mark("tool" + _LOW + "call" + _LOW + "begin") + "(.*?)" + _mark("tool" + _LOW + "call" + _LOW + "end"),
    re.DOTALL,
)
OFFICIAL_SEP = _mark("tool" + _LOW + "sep")  # ...<｜tool▁sep｜>名字\n{参数}
OFFICIAL_FENCE_PATTERN = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)
OFFICIAL_BRACE_PATTERN = re.compile(r"\{.*?\}", re.DOTALL)

# 扫语料时只认"会漏进产出被模仿"的那几族: 工具调用块 + role 标记。
# ★ 不把 bos/eos/fim/视觉占位那些算进来 —— 语料里正儿八经讲 tokenizer 本来就会提到它们,
#   那是内容不是污染(文件里写一句"特殊 token 有 <｜begin▁of▁sentence｜>" 不该被当成脏东西清掉)。
LEAKY_OFFICIAL_PATTERN = re.compile(
    "|".join(
        re.escape(_mark(name))
        for name in (
            "tool" + _LOW + "calls" + _LOW + "begin",
            "tool" + _LOW + "calls" + _LOW + "end",
            "tool" + _LOW + "call" + _LOW + "begin",
            "tool" + _LOW + "call" + _LOW + "end",
            "tool" + _LOW + "outputs" + _LOW + "begin",
            "tool" + _LOW + "outputs" + _LOW + "end",
            "tool" + _LOW + "output" + _LOW + "begin",
            "tool" + _LOW + "output" + _LOW + "end",
            "tool" + _LOW + "sep",
            "User",
            "Assistant",
        )
    )
)

# 粗筛用的针(先在语料 / 库里全文筛一遍候选, 细判交给 has_native_marker 与 strip 前后比对)
OFFICIAL_TOOL_HEAD = "<" + _VBAR + "tool"  # 官方那族都以它开头(<｜tool▁call▁begin｜>…)
DSML_ALT_HEAD = "<dsml:"
COARSE_NEEDLES = (DSML, "<tool_call", OFFICIAL_TOOL_HEAD, DSML_ALT_HEAD)

# 参数名里带这些字样的才算"要跑的命令" —— 别家可能叫 command / cmd / shell_command。
COMMAND_KEYS = ("command", "cmd", "shell")


def _pick_command(table: dict[str, Any]) -> str | None:
    """壳里有 command/cmd/shell 字段就拿出来."""
    for key in COMMAND_KEYS:
        picked = table.get(key)
        if isinstance(picked, str) and picked.strip():
            return picked.strip()
    return None


def _command_from_json(raw: str) -> str | None:
    """parameter 的值是个 JSON 壳时, 从里面挑出命令; 挑不到返回 None.

    识别两层: 顶层就是 {"command": ...}(官方模板渲染的样子),
    或者套一层 {"arguments": {"command": ...}}(OpenAI 那套 function.arguments 的样子)。
    """
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    table = cast(dict[str, Any], parsed)
    picked = _pick_command(table)
    if picked is not None:
        return picked
    for value in table.values():
        if isinstance(value, dict):
            picked = _pick_command(cast(dict[str, Any], value))
            if picked is not None:
                return picked
    return None


def dsml_commands(text: str) -> list[str]:
    """从 DSML 片段里提取命令 —— 两种识别方式, 任一命中即取.

    ① 参数名本身就带 command/cmd/shell  (name="command")
    ② 参数值是个 JSON 壳, 壳里有命令字段 (name="arguments" + {"command": ...})
    """
    out: list[str] = []
    for name, value in DSML_PARAM_PATTERN.findall(text):
        raw = value.strip()
        if raw.startswith("{"):
            picked = _command_from_json(raw)
            if picked is not None:
                out.append(picked)
                continue
        if raw and any(key in name.lower() for key in COMMAND_KEYS):
            out.append(raw)
    return out


def official_commands(text: str) -> list[str]:
    """④ 从官方 chat_template 那套标记里提取命令.

    形状: <｜tool▁call▁begin｜>{type}<｜tool▁sep｜>{name}\\n```json\\n{参数}\\n```<｜tool▁call▁end｜>
    参数装在 ```json 围栏里(官方模板就这样渲染), 也容忍裸 JSON 外壳。提取不出即视为未给命令。
    """
    out: list[str] = []
    blocks = OFFICIAL_CALL_BLOCK_PATTERN.findall(text)
    if not blocks:
        # 收尾少了 call▁end 时退一级取整个 calls 块, 不把它整段漏掉
        blocks = OFFICIAL_CALLS_BLOCK_PATTERN.findall(text)
    for block in blocks:
        for raw in (*OFFICIAL_FENCE_PATTERN.findall(block), *OFFICIAL_BRACE_PATTERN.findall(block)):
            picked = _command_from_json(raw.strip())
            if picked is not None:
                out.append(picked)
                break
    return out


def extract_native_calls(answer: str) -> list[str]:
    """把别家原生标记里"它说要跑的命令"提取出来 (② MiMo + ③ DSML + ④ DeepSeek 官方模板).

    判据始终是"是否真提取出命令" —— 提取不出即为表演, 不入库。
    """
    calls: list[str] = []
    for block in MIMO_CALL_PATTERN.findall(answer):
        calls.extend(
            item.strip() for item in MIMO_COMMAND_PATTERN.findall(block) if item.strip()
        )
    blocks = DSML_CALLS_PATTERN.findall(answer)
    if blocks:
        for block in blocks:
            calls.extend(dsml_commands(block))
    if not calls:
        # 只有半截闭合标记(没有成对块)时退回整段扫一遍参数, 不把命令漏掉
        calls.extend(dsml_commands(answer))
    if not calls:
        calls.extend(official_commands(answer))
    return calls


def strip_own_calls(text: str) -> str:
    """清掉本项目约定的 <调用>命令</调用> —— 连没收尾的半截写法一起清."""
    text = OWN_CALL_PATTERN.sub("", text)
    return OWN_UNCLOSED_PATTERN.sub("", text)


def own_unclosed_calls(answer: str) -> list[str]:
    """提取"收敛尾被别家标记顶掉"的半截 <调用> 里的命令.

    ★ 只在完全没有成对 <调用> 时才该调它 —— 否则它会把正常的 `</调用>` 一起吞进命令里
      (它的槽位是"到 DSML 标记或文末为止")。
    """
    return [item.strip() for item in OWN_UNCLOSED_PATTERN.findall(answer) if item.strip()]


def strip_native_markers(text: str) -> str:
    """清掉别家的原生标记(含各自半截变体) —— 调用块连内容一起清, 不留标记, 也不动正文。"""
    text = MIMO_CALL_PATTERN.sub("", text)
    text = DSML_CALLS_PATTERN.sub("", text)
    text = DSML_TAG_PATTERN.sub("", text)
    # ④ 官方那套: 先把整块调用(含 ```json 参数壳)端走, 再扫剩下零散的 <｜…｜> / <|…|> token
    text = OFFICIAL_CALLS_BLOCK_PATTERN.sub("", text)
    text = OFFICIAL_CALL_BLOCK_PATTERN.sub("", text)
    text = OFFICIAL_TOKEN_PATTERN.sub("", text)
    return OFFICIAL_ASCII_TOKEN_PATTERN.sub("", text)


def strip_all_calls(text: str) -> str:
    """落语料之前过这一道: 本项目约定 + 别家原生, 全部清掉.

    ★ 顺序不能换: 先清自家的(半截 <调用> 要靠"后面跟着 DSML 标记"才认得出边界),
      再清别家的标记。
    """
    return strip_native_markers(strip_own_calls(text)).strip()


def has_native_marker(text: str) -> bool:
    """正文里有没有**别家原生**标记 —— 扫语料查污染用.

    只识别别家的(DSML 方言 / MiMo 的 <tool_call / 官方那套工具调用标记): 那种会让模型看见就跟着模仿,
    是纯噪声。**不认自家的 `<调用>`** —— 那在语料里是"我们自己的约定长什么样"的活例子, 留着反而教它守规矩。
    ★ 官方那套里也只认工具/role 标记(LEAKY_OFFICIAL_PATTERN), 不认 bos/eos/fim/视觉占位 ——
      讲 tokenizer 的正文里提一句那些, 是内容不是污染。
    """
    if DSML in text or "<tool_call" in text or "<dsml:" in text:
        return True
    return LEAKY_OFFICIAL_PATTERN.search(text) is not None


# 任何一家的标记头(还没长成的那种): 全角竖线 / <调用 / <tool_c… / <dsml / <|…
_悬头 = re.compile(r"\uff5c|<调用|</调用|<tool_c|<dsml|</dsml|<\|")
# 尾巴上可能是某个标记的头只吐了一半("<调" / "<tool_" / "<") —— 也扣住
_尾悬 = re.compile(r"<[A-Za-z_/\uff5c\u4e00-\u9fff]{0,12}$")
# 成块的几家: 与落语料同一套判据(native_marks 里那几条), 块连里头的参数一起跳过
_成块 = (
    OWN_CALL_PATTERN,
    MIMO_CALL_PATTERN,
    DSML_CALLS_PATTERN,
    OFFICIAL_CALLS_BLOCK_PATTERN,
    OFFICIAL_CALL_BLOCK_PATTERN,
)


def _块到哪(全: str, 起: int) -> int | None:
    """从 起 开始是个**完整块**的话, 返回块的末尾(开区间); 不是就 None.

    ★ 标记头可能比块头晚一个字(官方那族是 `<｜…`, 竖线前还有个尖括号) —— 两处都试。
    """
    for 试 in (起, 起 - 1):
        if 试 < 0:
            continue
        for 式 in _成块:
            m = 式.match(全, 试)
            if m:
                return m.end()
    return None


class StreamFilter:
    """边流边吐用的过滤器: 一片一片喂进来, 只吐"人话", 协议块整段扣住.

    为什么不能拿 strip_all_calls 一片一片直接过
        片段边界会把一个标记切在两半 —— "<调用>ls</调用>好" 拆成 "<调" + "用>ls" +
        "</调用" + ">好", 单看每一片都不成标记, strip 不掉, 就照原样吐到正文区了
        (2026-10-09 web 正文区露原始md, 病根就在这)。

    做法
        不是"清完再比对", 而是每次喂进片段就从开头扫一遍累积到当前的全量:
          ① 撞上**完整块** —— 整块跳过(块里装的是命令/参数, 那是给过程面板看的, 不吐正文区);
          ② 撞上**开了头还没闭合**的标记 —— 停在那儿(它随时会长成块);
          ③ 剩下的就是人话: 与"已经吐出去的"比, 只吐多出来的那截。

    用法
        滤 = StreamFilter()
        滤.feed("好")            # -> "好"
        滤.feed("<调用>ls")       # -> ""     (开了头没闭合, 停在这)
        滤.feed("</调用>完事")    # -> "完事"  (块补齐 -> 整块跳过, 块后的人话接上)
        滤.flush()               # -> ""
    """

    def __init__(self) -> None:
        self._全 = ""
        self._已吐 = ""

    def feed(self, 片段: str) -> str:
        """喂一片进来, 返回这一片该吐到正文区的那截(可能为空)."""
        self._全 += 片段
        return self._吐新()

    def flush(self) -> str:
        """流结束: 把还挂着的人话也放出来(块里的那些本来就跳过, 不会跟着出来)."""
        return self._吐新()

    def _净(self) -> str:
        """攒到现在的全量 -> 现在该往正文区吐的那部分."""
        位 = 0
        话: list[str] = []
        while True:
            头 = _悬头.search(self._全, 位)
            if 头 is None:
                话.append(self._全[位:])
                break
            起 = 头.start()
            # 标记头可能比"块头"晚一个字(官方/DSML 那族开头是 `<｜…`): 那个尖括号也算进被跳过的那截,
            # 不然它会滞留在上一段人话的尾巴上、等块补齐后就卡在句子中间了
            while 起 > 位 and self._全[起 - 1] in "<>":
                起 -= 1
            if 起 > 位:
                话.append(self._全[位:起])
            块尾 = _块到哪(self._全, 起)
            if 块尾 is None:
                break  # 开了头还没闭合 —— 停在这儿, 等后面的片段
            位 = 块尾
        return _尾悬.sub("", "".join(话))

    def _吐新(self) -> str:
        净 = self._净()
        if not 净.startswith(self._已吐):
            # 前面已输出的那截又变了(悬着的那块补齐后被整块跳过, 把前头一起吞掉了) ——
            # 就地重新对齐: 宁可丢一点, 也不能卡住不吐。
            self._已吐 = 净[: len(self._已吐)]
        if len(净) <= len(self._已吐):
            return ""
        出 = 净[len(self._已吐) :]
        self._已吐 = 净
        return 出

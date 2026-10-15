"""执行 agent: 给一个任务 + 一份 skill, 带着手跑, 拿回结果 —— 不往终端画任何东西.

与 main.py 同一个内核(同一个模型客户端、同一套流式处理), 区别有三点:
1. **过程回显靠回调, 自身不画 TUI**: 默认一个字都不打(当库用时干净); 传了 `on_event`
   才把"它在想什么、说了什么、要跑哪条命令、命令吐出什么"边发生边报出去 ——
   打不打、打什么样由调用方(main.py)决定, 文案在 config/agent.json 的 ui 段。
2. **入口是"跑一个任务"**, 不是人机对话循环 —— 因此能被其他程序直接调用。
3. **有手**: skill 里写"怎么调"的命令, 它真去跑 —— 命令写入正文（末行声明本趟是否执行），
   程序提取后真跑，输出贴回；提不到时退回调用标记与专用读回件（见 `提取命令`）。

换 skill 就换职责: 主 agent 只要改 skill 就能工作, 这里同理。

跑法:
    .venv/bin/python exec_agent.py "任务"                        # 用默认 skill
    .venv/bin/python exec_agent.py "任务" --skill skill/xxx/SKILL.md
    echo "任务" | .venv/bin/python exec_agent.py                 # 任务走 stdin
    .venv/bin/python exec_agent.py "任务" --json                 # 出结构化结果

当库用:
    from exec_agent import run_task
    result = run_task("任务", skill_path="skill/xxx/SKILL.md")
    # -> {"answer", "reasoning", "usage", "calls"}   calls 是它真跑过的命令
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from dotenv import load_dotenv
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

import sub_agent
import native_marks

HERE = Path(__file__).resolve().parent
DEFAULT_SKILL = sub_agent.DEFAULT_SKILL
# 每条命令的完整输出落这 —— 进库只带路径, 不把整段输出灌进热库
OUTPUT_DIR = HERE / "logs" / "exec"

# 过程回显的回调: (事件, 内容)。四种事件 ——
#   think   它正在想(增量)      reply  它正在说(增量)
#   command 马上要跑这条命令    output 这条命令吐出来的原文
ProgressFn = Callable[[str, str], None]

load_dotenv(HERE / ".env")

# 它的手: 模型输出 <调用>命令</调用>, 程序真跑, 输出贴回去
CALL_PATTERN = re.compile(r"<调用>(.*?)</调用>", re.DOTALL)
# 别家不认我们这个标记, 会输出它自己那套原生工具调用(小米 MiMo 的 XML / DeepSeek 的 DSML)——
# 几套的形状、半截变体、实测坑统一放在 native_marks.py 里认, 三个地方共用一份正则:
# exec 命令提取 / 产出落语料(sub_agent) / Hermes 会话导出(import_hermes_hist)。



def strip_calls(text: str) -> str:
    """把"手"的几种写法(含各自的半截变体)从正文里清干净 —— 剩下的才是它真要说的话."""
    return native_marks.strip_all_calls(text)


def extract_calls(answer: str) -> list[str]:
    """把模型"说的要跑的命令"提取出来 —— 几种写法都识别.

    ① 我们约定的 `<调用>命令</调用>`(含收尾被别家标记顶掉的半截写法)
    ② 别家原生的那两套(小米 MiMo 的 XML / DeepSeek 的 DSML)—— 形状在 native_marks.py 里。
    判据始终是"是否真提取出命令" —— 提取不出即为表演, 不入库。
    """
    calls = [item.strip() for item in CALL_PATTERN.findall(answer) if item.strip()]
    if not calls:
        # 半截 <调用>(收尾被别家的闭合标记顶掉了) —— 命令照收, 不当作未给
        calls.extend(native_marks.own_unclosed_calls(answer))
    calls.extend(native_marks.extract_native_calls(answer))
    return calls

# 退化检测: 同一句话翻来覆去说 —— 本地小模型在长提示下的经典毛病.
# 不掐的话它会一路吐到 max_tokens, 一轮就是好几分钟(实测单轮 3579 tokens 还在涨).
REPEAT_SHORTEST = 6     # 复读单位最短这么长(中文一句话)
REPEAT_LONGEST = 80     # 最长这么长(一段)
REPEAT_TIMES = 3        # 连着说这么多遍就认了


def looks_degenerate(text: str) -> bool:
    """同一句话(或同一段)是不是连着说了三遍以上.

    判"结尾这 3 份是不是同一个单位重复": 单位长度从短扫到长, 任一命中就算复读。
    正常作答里连着三遍一模一样的话基本不存在, 所以误伤极少; 而真复读时它两三秒内就撞上。
    """
    tail = text[-REPEAT_LONGEST * REPEAT_TIMES :]
    for period in range(REPEAT_SHORTEST, REPEAT_LONGEST + 1):
        if len(tail) < period * REPEAT_TIMES:
            break
        unit = tail[-period:]
        if tail.endswith(unit * REPEAT_TIMES):
            return True
    return False


def tool_hint(rounds: int) -> str:
    """手的提示词 —— 在 config/skills/exec.md 里, 不硬编码在代码里。"""
    return sub_agent.load_prompt("exec").format(rounds=rounds)


# 兜底交代的版面: 摊最后几条命令、每条留多少字 —— 全文都在 logs/exec/*.txt, 不缺信息
SALVAGE_TAIL = 3
SALVAGE_CHARS = 600


def salvage_from_calls(末轮原文: str, 收尾原文: str, calls: list[dict[str, str]]) -> str:
    """回合用尽、模型又不肯给结论时, 程序自己拼一份交代 —— 只摊事实, 一句都不编.

    ★ 为什么要有它: 原来这里只贴一行 `(来回次数用尽, 它还想调命令)`。可模型最后一轮
      常常**只吐一个 `<调用>` 块**, 清掉标记后正文就是空的 —— 于是屏幕上**只剩那一行标签**,
      它前面真跑出来的东西全丢了(老板 2026-10-09 抓到的就是这个: "它只显示了这个")。
    口径没变: 不许编结论。但"它还想跑什么 / 真跑过什么 / 拿到什么"都是事实, 原样摊出来
    比一句空标签有用得多, 而且它想跑的那条往往正是缺的那块拼图(用户能自己接着判断)。
    """
    段: list[str] = ["(来回次数用尽, 它还想调命令)"]
    还想跑 = extract_calls(末轮原文) or 规则层提取命令(末轮原文) or extract_calls(收尾原文)
    if 还想跑:
        段.append("还想跑: " + " ; ".join(还想跑))
    if not calls:
        段.append("这一趟一条命令都没跑成, 没有结果可以交代。")
        return "\n".join(段)

    段.append(f"已经跑到的(原样, 没加工; 共 {len(calls)} 条, 摊最后 {SALVAGE_TAIL} 条):")
    for 一条 in calls[-SALVAGE_TAIL:]:
        输出 = str(一条.get("output", "")).strip()
        if len(输出) > SALVAGE_CHARS:
            输出 = "(…前略…)\n" + 输出[-SALVAGE_CHARS:]
        段.append(f"$ {一条.get('command', '?')}")
        段.append(输出 if 输出 else "(这条没有输出)")
        if 一条.get("file"):
            段.append(f"  全文: {一条['file']}")
    return "\n".join(段)


def looks_like_preamble(text: str, markers: list[str], max_chars: int) -> bool:
    """这句像不像"预告"(我来查 / 正在看 / 接下来…) —— 像就说明它还没动手, 不是结论。

    实测(2026-10-06): 问"这台机器是什么配置", 它只回了一句
    "我来查这台机器的 CPU、内存和磁盘分区情况。" 一个 <调用> 都没给 ——
    提示词里明写了不许预告, 但模型仍会犯, 所以得在程序里认出来。
    判据故意宽松: 短 + 带意图词就算; 拿不准就当预告(多催一次只花一次调用)。
    """
    stripped = text.strip()
    if not stripped or len(stripped) > max_chars:
        return False
    return any(marker in stripped for marker in markers)


# ── 命令提取（2026-10-14 接线）──────────────────────────────────────────────
# 手提示（config/skills/exec.md）改为"命令写入正文 + 末行声明本趟是否执行"后，命令来源三条：
#   ① 调用标记：旧写法（config/skills/exec-mark.md）与别家原生标记（native_marks 统一识别）
#   ② 尾巴规则层：本文件内的纯字符串规则（低开销快路径）
#   ③ 专用读回件：config/skills/command-readback.md，本地模型，纯翻译，无云端开销
# 设计约束：是否执行的判定不属本层 —— 上游以尾巴句表达意图，本层仅做机械对账。
尾巴模式 = re.compile(r"这趟[^\n]{0,16}(?:跑|查|执行|看一眼|看看|试)")
反引号模式 = re.compile(r"`([^`\n]{1,400})`")
# 复述标记：命中即表明该行在陈述既往动作，不作为执行意图
复述标记 = (
    "跑了", "跑完", "执行了", "执行完", "跑过", "执行过", "刚才", "上一轮", "已经跑", "输出了",
    "显示", "不许", "不要", "建议", "如果", "假设", "模拟", "可以用", "可以这样", "无输出",
)
# 执行意图标记：无此标记的行不视为交班（资料块内亦为反引号短语，须以此区分）
执行意图标记 = (
    "要跑", "去跑", "得跑", "跑一下", "跑一条", "跑这条", "跑起来", "执行一下", "来一条",
    "查一下", "看一下", "看一眼", "先看看", "试试", "跑一遍", "执行一遍",
)


def 取尾巴句(answer: str) -> str:
    """取回答末行的正文句 —— 新写法中该句承担"本趟是否需执行"的声明。

    跳过列表项、引用、代码行等非正文行；但**以标题符号开头的行**若本身带尾巴特征
    （"这趟…跑" / "不用跑"）仍视为尾巴句 —— 实测模型会把它写成 `# 这趟不用跑，我说完就完。`。
    """
    for 行 in reversed([x.strip() for x in answer.strip().splitlines() if x.strip()]):
        if 行.startswith(("#", "-", "*", ">", "`")):
            if 尾巴模式.search(行) or "不用跑" in 行:
                return 行.lstrip("#-*> ").strip()
            continue
        return 行
    return ""


def 尾巴声明执行(answer: str) -> bool:
    """末行是否声明执行意图 —— 催促的判据之一。

    仅在"已声明执行、但未交出可执行命令"时催促（另一条判据为预告语，见 looks_like_preamble）。
    旧判据为"本轮未提取到命令即催促"，粒度不足：概念/资料类问题本无命令，逐轮催促只能换来
    致歉式空话（实测三遍均复现）。
    """
    尾 = 取尾巴句(answer)
    return bool(尾巴模式.search(尾)) and "不用跑" not in 尾


def 单句提取命令(一句: str) -> list[str]:
    """单句命令提取：优先取反引号内容，否则取"跑 / 执行 / 查"之后的片段。

    提取结果须具备命令形态（含空格 / 斜杠 / 横杠 / 竖线），否则"这趟我去查一下它的配置"
    会把"它的配置"当作命令提交执行。
    """
    命令: list[str] = []
    for 命中 in 反引号模式.finditer(一句):
        命令.append(命中.group(1).strip())
    if 命令:
        return [c for c in 命令 if c]
    尾巴形状 = re.search(r"(?:跑|执行|查|看|试)(?:一下|一眼|看|一遍)?\s*[:：]?\s*(.+)$", 一句)
    if 尾巴形状:
        候选 = re.sub(r"^(?:这条|那条|一下|一遍)\s*", "", 尾巴形状.group(1).strip()).strip("。，,；; ")
        # ★ 顿号是"几条命令并列"的中文写法, 不是 shell 分隔符 —— 整串交给 shell 会变成
        #   一个陌生命令名(2026-10-15 实测: "nproc、uptime、free -h" 只有 nproc 出结果,
        #   白烧两轮才自己发现)。这里先按顿号拆开, 每段各自过形态校验。
        顿号拆 = 候选.split("、")
        for 段 in 顿号拆:
            段 = 段.strip().strip("。，,；; ")
            if not 段 or 段.startswith(("完", "过", "到", "着", "了")):
                continue
            # 形态校验：含命令记号就算；★顿号并列出来的单个英文词也算 —— "nproc、uptime"
            #   这种列举本身就是"这是几条命令"的证据(单段时仍按老规矩要记号, 免得
            #   "我去跑它的配置"里的"它的配置"混进来)。
            if any(记号 in 段 for 记号 in (" ", "/", "-", "|", ".")) or re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_.-]*", 段
            ):
                命令.append(段)
    return 命令


def 规则层提取命令(answer: str) -> list[str]:
    """尾巴写法的规则层，三条约束：

    1. 存在尾巴句时以其为准：尾巴句声明不执行 → 全部不取（正文中命令一律不计）。
    2. 无尾巴句时回正文检索，且仅取带执行意图标记、不含复述标记的行；表格行（`|`）不取。
    3. `# 过程` 之后不取（该段反引号内容为既往动作的复述）。

    实测依据（取宽的两次代价）：
      · 过程段复述被当作交班 → 同一命令重复执行（6 题 4 中招，共 27 次）；
      · 资料块内文件名（pyrightconfig.json / include / .py 等）被连续提交执行 13 条。
    """
    尾 = 取尾巴句(answer)
    if 尾 and ("不用跑" in 尾 or any(词 in 尾 for 词 in 复述标记)):
        # 尾巴句声明不执行，或该句本身为复述 → 正文不计
        return []
    if 尾:
        命令 = 单句提取命令(尾)
        if 命令:
            return 命令
    正文 = answer.split("# 过程")[0]
    候选集: list[str] = []
    for 行 in 正文.splitlines():
        行 = 行.strip()
        if not 行 or 行.startswith(("#", "-", "*", ">", "|")) or "|" in 行:
            continue
        if any(词 in 行 for 词 in 复述标记):
            continue
        if not any(词 in 行 for 词 in 执行意图标记):
            continue
        候选集.extend(单句提取命令(行))
    去重: list[str] = []
    for 命令 in 候选集:
        if 命令 and 命令 not in 去重 and not 命令.startswith(("$", "#")):
            去重.append(命令)
    return 去重


def 解析读回文本(读回输出: str) -> list[str]:
    """读回件输出 → 命令列表（输出为 `无` 时为空）。"""
    命令: list[str] = []
    for 行 in 读回输出.splitlines():
        行 = 行.strip().strip("`").strip()
        if not 行 or 行 in ("无", "none", "None", "N/A"):
            continue
        if 行.startswith(("#", "-", "*", ">", "$")):
            行 = 行.lstrip("#-*>$ ").strip()
        if 行:
            命令.append(行)
    return 命令[:2]  # 读回件约定上限两条


_读回客户端: "tuple[OpenAI, str] | None" = None


def 选读回模型(手: "ChatAgent") -> tuple[OpenAI, str]:
    """读回层模型选择：配置为"本地"时取本机端点（无费用，约 1s），否则与手同源。"""
    global _读回客户端
    配置 = cast(dict[str, Any], sub_agent.load_agent_config()["exec"].get("命令提取") or {})
    if str(配置.get("读回模型", "本地")) != "本地":
        return 手.client, 手.model
    if _读回客户端 is None:
        基址 = os.getenv("OPENAI_BASE_URL") or "http://127.0.0.1:8790/v1"
        钥匙 = os.getenv("OPENAI_API_KEY") or "local"
        _读回客户端 = (OpenAI(base_url=基址, api_key=钥匙), os.getenv("OPENAI_MODEL") or 手.model)
    return _读回客户端


def 读回层提取命令(answer: str, 手: "ChatAgent") -> list[str]:
    """来源③：交由专用读回件（纯翻译）输出本趟待执行命令。

    执行与否的判定在上游尾巴句，读回件只做翻译。读回层无输出或异常 → 返回空（视为本趟不执行），
    不构造任何命令。
    """
    配置 = cast(dict[str, Any], sub_agent.load_agent_config()["exec"].get("命令提取") or {})
    上限 = int(配置.get("读回上限", 200))
    try:
        读回件 = sub_agent.load_prompt(str(配置.get("读回件", "命令读回")))
        client, model = 选读回模型(手)
        回复 = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": 读回件},
                {"role": "user", "content": answer[:6000]},
            ],
            max_tokens=上限,
            temperature=0,
        )
        文本 = 回复.choices[0].message.content or ""
    except Exception:
        return []
    return 解析读回文本(文本)


def 提取命令(answer: str, 手: "ChatAgent") -> list[str]:
    """命令提取总入口，按来源顺序：①调用标记 → ②尾巴规则层 → ③专用读回件。"""
    命令 = extract_calls(answer)
    if 命令:
        return 命令
    命令 = 规则层提取命令(answer)
    if 命令:
        return 命令
    return 读回层提取命令(answer, 手)


def collect_stream(stream_generator: Iterable[tuple[str, str]]) -> tuple[str, str]:
    """把流式增量收成完整文本，不做任何终端输出。

    生成器每次 yield (类型, 文本片段)，类型为 reasoning 或 answer。
    这是 render_stream 的无装饰版: 同样的分片协议，去掉颜色/标签/刷屏。
    """
    reasoning_text = ""
    answer_text = ""

    for content_type, chunk in stream_generator:
        if content_type not in ("reasoning", "answer"):
            raise ValueError(f"未知的流内容类型：{content_type}")
        if content_type == "reasoning":
            reasoning_text += chunk
        else:
            answer_text += chunk

    return reasoning_text, answer_text


def get_response_stats(
    usage: object | None,
    elapsed_seconds: float,
) -> dict[str, int | float | None]:
    """从 API 的 usage 数据中提取 token 用量，并计算生成速度。"""
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    total_tokens = getattr(usage, "total_tokens", None)

    tokens_per_second = None
    if isinstance(completion_tokens, int) and elapsed_seconds > 0:
        tokens_per_second = completion_tokens / elapsed_seconds

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "tokens_per_second": tokens_per_second,
    }


def recursive_force_remove(command: str) -> bool:
    """这条命令是不是 `rm` 带"递归 + 强制"的组合(-rf / -fr / -Rf / -f -r ...).

    这类一律不放行: 一个字打错就整棵树没了, 而"能真动手"并不需要它 ——
    删单个文件用 `rm <路径>`, 清目录用 `rm -r <确认过的目录>`。
    """
    for match in re.finditer(r"\brm\b([^;&|\n]*)", command, re.IGNORECASE):
        flags = [option.lstrip("-").lower() for option in re.findall(r"-{1,2}[a-zA-Z]+", match.group(1))]
        if any("r" in flag for flag in flags) and any("f" in flag for flag in flags):
            return True
    return False


def find_delete_wide(command: str) -> str | None:
    """`find ... -delete` 有没有"筛过再删".

    `find /tmp -delete` / `find / -delete` 这种一把梭的, 跟 `rm -rf` 是一码事,
    而且它不含 rm 字样 —— 不专门管就绕过去了. 要求带一个限定谓词
    (-name / -mtime / -size / -path / -regex / -newer) 才算点名清理.
    """
    if "-delete" not in command:
        return None
    narrowing = ("-name", "-iname", "-mtime", "-mmin", "-size", "-path", "-regex", "-newer", "-empty")
    if any(word in command for word in narrowing):
        return None
    return "find ... -delete 没带限定条件"


def wide_target_remove(command: str, wide: list[str]) -> str | None:
    """`rm` 的目标是不是"宽目标"(整个盘子/家目录/系统目录那一级).

    返回命中的那个目标; None = 没命中. 只看目标本身, 不管带不带 -rf ——
    `rm -r /tmp` 和 `rm -rf /tmp` 一样糟。知名目录(系统的 + 家目录那一层)一律拦截。
    """
    for match in re.finditer(r"\brm\b([^;&|\n]*)", command, re.IGNORECASE):
        for token in re.findall(r"[^\s]+", match.group(1)):
            if token.startswith("-"):
                continue
            if "*" in token or "?" in token:
                return token
            target = token.strip("\"'").rstrip("/") or token.strip("\"'")
            if target.lower() in wide:
                return target
            if re.fullmatch(r"/(etc|usr|boot|opt|srv|root|var|home)(/[^/]*)?", target):
                return target
    return None


def blocked_reason(command: str) -> str | None:
    """挡掉明显动系统/删数据的命令 —— 执行体只该跑 skill 里写的那种。

    返回拦下的理由; None = 放行。理由要说明白: 模型看得见, 便于换个写法重试。
    """
    exec_config = cast(dict[str, Any], sub_agent.load_agent_config()["exec"])
    lowered = command.lower()
    for word in cast(list[str], exec_config["blocked_fragments"]):
        if word in lowered:
            return f"命令里有 {word!r}"
    if recursive_force_remove(command):
        return "rm 带了递归+强制(-rf) —— 要删就删写明白的路径: rm <文件> 或 rm -r <目录>"
    wide = wide_target_remove(command, cast(list[str], exec_config["wide_remove_targets"]))
    if wide is not None:
        return f"rm 的目标 {wide!r} 太宽(整个盘/家目录/系统目录那一级) —— 只动写明白的路径"
    unscreened = find_delete_wide(command)
    if unscreened is not None:
        return f"{unscreened} —— 清东西要先筛出来看一遍: find <目录> -name '...' -delete, 或者点名 rm"
    if re.search(cast(str, exec_config["sudo_pattern"]), lowered):
        return "不用 sudo"
    return None


def save_output(stamp: str, order: int, command: str, output: str) -> str:
    """一条命令的完整输出落盘, 返回相对项目根的路径。

    模型只看到截断的那 4000 字; 完整输出留档, 进库时带上路径可追溯.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{stamp}-{order:02d}.txt"
    path.write_text(f"$ {command}\n\n{output}\n", encoding="utf-8")
    return str(path.relative_to(HERE))


def is_background(command: str) -> bool:
    """是不是"起个东西就走"的后台写法（末尾 `&`）."""
    return command.strip().rstrip(";").strip().endswith("&")


def start_background(command: str) -> str:
    """后台命令: 不等它, 立刻返回。

    不这么做就会被自己的管道挂住 —— 后台的孙子进程攥着 capture_output 的写端,
    subprocess.run 一直等 EOF, 于是"起个服务"会空等到超时(它其实早已起来)。
    输出另存一份, 事后可查; 新开一个会话, 我们退出了它也活着。
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OUTPUT_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-bg.out"
    with log_path.open("wb") as sink:
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=str(HERE),
            stdin=subprocess.DEVNULL,
            stdout=sink,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return (
        f"(已在后台起: pid {process.pid}; 输出写到 {log_path.relative_to(HERE)})\n"
        f"不在这里等它 —— 它到底起没起来, 用 ss -ltnp 之类再确认一次。"
    )


def run_command(command: str, timeout: int | None = None) -> str:
    """真跑一条命令, 返回输出文本 (stdout, 带 stderr)。"""
    reason = blocked_reason(command)
    if reason is not None:
        return f"(拦下了: {reason})"
    if is_background(command):
        return start_background(command)

    if timeout is None:
        timeout = int(sub_agent.load_agent_config()["exec"]["timeout_seconds"])

    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(HERE),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"(命令跑了超过 {timeout} 秒, 掐了)"

    output = completed.stdout or ""
    if completed.stderr.strip():
        output += f"\n[stderr]\n{completed.stderr}"
    return output.strip() or "(没有输出)"


class ChatAgent:
    """拿一份提示词跑任务，结果只返回、不打印。"""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        system_prompt: str,
        max_tokens: int | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens

    @classmethod
    def from_env(
        cls,
        model: str | None = None,
        system_prompt_path: str = DEFAULT_SKILL,
    ) -> "ChatAgent":
        """从 .env 和提示词文件中创建实例。"""
        prompt_path = Path(system_prompt_path)
        if not prompt_path.is_absolute():
            prompt_path = HERE / prompt_path
        if not prompt_path.is_file():
            raise FileNotFoundError(f"skill 文件不在: {prompt_path}")

        # exec 可以单独挂一支模型(比如云端 API): 有 EXEC_* 就用它, 没有就跟主 agent 共用一套
        client = OpenAI(
            api_key=os.getenv("EXEC_API_KEY") or os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("EXEC_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
        )
        resolved_model = (
            model
            or os.getenv("EXEC_MODEL")
            or os.getenv("OPENAI_MODEL")
            or "qwen3-vl-8b"
        )
        exec_config = cast(dict[str, Any], sub_agent.load_agent_config()["exec"])
        max_tokens = int(exec_config["max_tokens"]) if exec_config.get("max_tokens") else None
        return cls(
            client,
            resolved_model,
            prompt_path.read_text(encoding="utf-8"),
            max_tokens=max_tokens,
        )

    def ask(
        self,
        messages: list[ChatCompletionMessageParam],
        on_event: ProgressFn | None = None,
    ) -> tuple[str, str, dict[str, int | float | None]]:
        """一次流式请求，返回 (思考内容, 回答, 用量统计)。

        传了 on_event 就边生成边报: ("think", 增量) / ("reply", 增量)。
        """
        request_started_at = perf_counter()
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            max_tokens=self.max_tokens,
        )

        usage = None
        first_output_at = None
        degenerate = False
        answer_so_far = ""

        def response_chunks() -> Iterable[tuple[str, str]]:
            nonlocal usage, first_output_at, degenerate, answer_so_far

            for chunk in stream:
                # 流式 usage 通常出现在最后一个 chunk；该 chunk 可能没有 choices。
                if chunk.usage is not None:
                    usage = chunk.usage
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                # reasoning_content 是部分模型提供的扩展字段，并非 OpenAI 标准字段。
                reasoning_chunk = getattr(delta, "reasoning_content", None)
                if reasoning_chunk:
                    if first_output_at is None:
                        first_output_at = perf_counter()
                    if on_event is not None:
                        on_event("think", reasoning_chunk)
                    yield "reasoning", reasoning_chunk

                if delta.content:
                    if first_output_at is None:
                        first_output_at = perf_counter()
                    answer_so_far += delta.content
                    # 它开始重复同一段 —— 本轮到此为止, 不陪着烧几分钟
                    if looks_degenerate(answer_so_far):
                        degenerate = True
                        return
                    if on_event is not None:
                        on_event("reply", delta.content)
                    yield "answer", delta.content

        reasoning, answer = collect_stream(response_chunks())
        if degenerate:
            answer += "\n(它开始重复同一段话, 这轮掐了)"
        output_finished_at = perf_counter()
        elapsed_seconds = (
            output_finished_at - first_output_at
            if first_output_at is not None
            else output_finished_at - request_started_at
        )
        return reasoning, answer, get_response_stats(usage, elapsed_seconds)

    def chat(
        self, user_message: str, on_event: ProgressFn | None = None
    ) -> tuple[str, str, dict[str, int | float | None]]:
        """跑一次，返回 (思考内容, 回答, 用量统计)。"""
        return self.ask(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message},
            ],
            on_event,
        )

    def run(
        self,
        task: str,
        max_rounds: int | None = None,
        on_event: ProgressFn | None = None,
    ) -> tuple[str, str, dict[str, int | float | None], list[dict[str, str]]]:
        """带着手跑: 它要命令就真跑, 输出贴回去让它接着想, 直到它不再要命令.

        返回 (思考内容, 回答, 用量统计, 真跑过的命令)。来回用尽还在要命令,
        就在回答前头标一句, 不假装干完了。
        """
        if max_rounds is None:
            max_rounds = int(sub_agent.load_agent_config()["exec"]["max_rounds"])
        exec_cfg = cast(dict[str, Any], sub_agent.load_agent_config()["exec"])
        max_nudges = int(exec_cfg.get("max_nudges", 2))
        preamble_max = int(exec_cfg.get("preamble_max_chars", 120))
        raw_markers = exec_cfg.get("preamble_markers")
        markers = (
            [str(item) for item in cast(list[Any], raw_markers)]
            if isinstance(raw_markers, list)
            else []
        )
        nudge = sub_agent.load_prompt("nudge")
        wrapup = sub_agent.load_prompt("wrapup")
        messages: list[ChatCompletionMessageParam] = [
            {
                "role": "system",
                "content": self.system_prompt + tool_hint(max_rounds),
            },
            {"role": "user", "content": task},
        ]
        calls: list[dict[str, str]] = []
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        reasoning_all = ""
        answer = ""
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        last_speed: float | None = None
        exhausted = True
        nudges = 0

        # +max_nudges: 催促用掉的轮次不吃"调命令"的预算(不然它前面磨蹭两轮, 后面就没回合干活了)
        for _ in range(max_rounds + 1 + max_nudges):
            reasoning, answer, stats = self.ask(messages, on_event)
            reasoning_all += reasoning
            for key, target in (
                ("prompt_tokens", "prompt"),
                ("completion_tokens", "completion"),
                ("total_tokens", "total"),
            ):
                value = stats.get(key)
                if isinstance(value, int):
                    if target == "prompt":
                        prompt_tokens += value
                    elif target == "completion":
                        completion_tokens += value
                    else:
                        total_tokens += value
            speed = stats.get("tokens_per_second")
            if isinstance(speed, float):
                last_speed = speed

            commands = 提取命令(answer, self)
            if not commands:
                # 未提取到命令的两种情形，均属"尚未完成"，各催促一次（要求：交出命令，或给出结论）：
                #   ① 预告语（"我来查…"，见 looks_like_preamble）—— 无命令的空转
                #   ② 尾巴句声明执行但未交出命令 —— 提取层无从取得
                # ★ 概念/资料类问题不催：本无命令可交，催促仅产生致歉式空话（实测三遍均复现）。
                suspect = looks_like_preamble(answer, markers, preamble_max) or 尾巴声明执行(answer)
                if suspect and nudges < max_nudges:
                    nudges += 1
                    if on_event is not None:
                        on_event("note", f"(未提取到命令，催促第 {nudges} 次)")
                    messages.append({"role": "assistant", "content": answer})
                    messages.append({"role": "user", "content": nudge})
                    continue
                exhausted = False
                break

            # 一轮里它可能一次给好几条(尤其自带的 XML 格式) —— 都跑, 输出逐条贴回
            messages.append({"role": "assistant", "content": answer})
            for command in commands:
                if on_event is not None:
                    on_event("command", command)
                output = run_command(command)
                path = save_output(stamp, len(calls) + 1, command, output)
                if on_event is not None:
                    on_event("output", output)
                    on_event("output_file", path)
                calls.append({
                    "command": command,
                    "output": output[:2000],
                    "file": path,
                })
                messages.append({"role": "user", "content": f"[命令输出]\n{output[:4000]}"})

        # 收尾之前把原样留一份 —— 万一模型只输出标记不输出正文, 兜底要用它提取"它还想跑什么"
        末轮原文 = answer
        answer = strip_calls(answer)
        if exhausted:
            # ★ 回合用尽 = 它还想调命令, 但"还想查"不等于"没得答" —— 实测问"内存条什么型号"
            # (型号要 root, 查不到) 时它一路试到回合用尽, 最后交白卷: 前面真跑出来的
            # "槽位 1/2、16G 单条、型号要 root" 全丢了。所以补一次**收尾**:
            # 明说不能再调命令, 用已有结果作答, 查不到的直说。
            messages.append({"role": "user", "content": wrapup})
            closing_reasoning, closing, closing_stats = self.ask(messages, on_event)
            reasoning_all += closing_reasoning
            for key, target in (
                ("prompt_tokens", "prompt"),
                ("completion_tokens", "completion"),
                ("total_tokens", "total"),
            ):
                value = closing_stats.get(key)
                if isinstance(value, int):
                    if target == "prompt":
                        prompt_tokens += value
                    elif target == "completion":
                        completion_tokens += value
                    else:
                        total_tokens += value
            closing_speed = closing_stats.get("tokens_per_second")
            if isinstance(closing_speed, float):
                last_speed = closing_speed
            closing_text = strip_calls(closing)
            if closing_text:
                answer = closing_text
                if on_event is not None:
                    on_event("note", "(回合用尽, 补了一次收尾: 让它用已有结果作答)")
            else:
                # 收尾也没给结论 —— 不交白卷: 把"还想跑什么 / 真跑过什么"原样列出
                answer = salvage_from_calls(末轮原文, closing, calls)
        usage: dict[str, int | float | None] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "tokens_per_second": last_speed,
        }
        return reasoning_all, answer, usage, calls


def 执行翻查(模板: str, 任务: str, 超时: int) -> str:
    """按模板（含 `{问题}` 占位）执行一条只读翻查命令，返回其输出（失败或超时返回空）。"""
    if not 模板.strip():
        return ""
    命令 = 模板.replace("{问题}", 任务.replace('"', "'"))
    try:
        完成 = subprocess.run(
            命令, shell=True, cwd=HERE, capture_output=True, text=True, timeout=超时
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return (完成.stdout or "").strip() or (完成.stderr or "").strip()


def 预取资料(任务: str) -> str:
    """exec 前置的资料预取：手册（skill/ops）+ 记忆库（skill/rag）命中条目，格式化为【资料】块。

    判据按 config/agent.json 的 `exec.程序先翻.规程词` 判定问题类型：
      · 规程 / 道理类 → 预取并注入（实测：交由模型自行翻查的命中率为 0/10，且伴随虚构"手册无此项"；
        改为程序预取、模型仅据资料作答后，本系统类问题的编造与假否定即消失）
      · 实况类（余量 / 端口占用 / 任务清单）→ 不注入。记忆库内容为既往执行输出，注入实况类问题
        等同于以历史结论冒充当前状态（实测：问"定时任务都有啥"时，模型照抄资料内
        "跑了 timer/main.py list，输出 现在没挂着定时任务"）。实况须实跑取值。
    """
    配置 = cast(dict[str, Any], sub_agent.load_agent_config()["exec"].get("资料预取") or {})
    if not 配置.get("enabled"):
        return ""
    规程词 = [str(x) for x in cast(list[Any], 配置.get("规程词") or [])]
    if not any(词 in 任务 for 词 in 规程词):
        return ""
    超时 = int(配置.get("超时秒", 60))
    手册 = 执行翻查(str(配置.get("手册命令", "")), 任务, 超时)[: int(配置.get("手册上限", 3000))].strip()
    记忆 = 执行翻查(str(配置.get("记忆命令", "")), 任务, 超时)[: int(配置.get("记忆上限", 2000))].strip()
    if not 手册 and not 记忆:
        return ""
    return (
        "\n\n【资料 · 程序已经替你翻好】\n"
        "★ 这是**翻本子翻到的**, 不是机器跑出来的: 照它说, 别说成\"我跑了\"。\n\n"
        f"## 本系统手册里命中的条目\n{手册 or '(没翻到)'}\n\n"
        f"## 记忆库里命中的片段(★ 旧记录, 不是现在的实况)\n{记忆 or '(没翻到)'}\n"
    )


#: ── ★ 答案级引用核对(纯正则, 不调模型) ──
#: 治的是"编新数": 2026-10-15 实测本地 8B 跑着真命令(11 步), 答案却写"根 12.3G / 87%"
#: (本轮 df -h 真输出是 279G / 58%) —— 数字跟自己的输出都对不上。
#: 摘掉命令库旧快照只能治"照念旧数", 治不了这个, 这一层是兜底。
硬指标 = (
    re.compile(r"\d+(?:\.\d+)?\s*%"),                                            # 百分比
    re.compile(r"\d+(?:\.\d+)?\s*(?:Gi?B?|Mi?B?|Ti?B?|Ki?B?|GB|MB|KB|G|M|T)\b"),  # 容量
    re.compile(r"\d+\s*个?\s*(?:逻辑)?\s*(?:CPU)?\s*(?:核心|核|线程|路)"),              # 核数(含"8 个逻辑核心")
    re.compile(r"\d+(?:\.\d+)?\s*(?:度|℃|°C)"),                                   # 温度
)

#: 单位归一: G/Gi/GB/GiB 当同一个, 大小写与空格不算差异(模型常写 "11G" 而 free 给 "11Gi")
单位归一 = {"gi": "g", "gib": "g", "mi": "m", "mib": "m", "ti": "t", "tib": "t",
            "ki": "k", "kib": "k", "gb": "g", "mb": "m", "kb": "k", "tb": "t"}


def 归一数字(文本: str) -> set[str]:
    """把文本里的"数字+单位"抽成可比集合(去空格、单位归一)。"""
    出: set[str] = set()
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(%|Gi?B?|Mi?B?|Ti?B?|Ki?B?|G|M|T|K|核|线程|路|度|℃|°C)?", 文本):
        数 = m.group(1)
        单 = (m.group(2) or "").lower()
        单 = 单位归一.get(单, 单)
        出.add(f"{数}{单}")
    return 出


def 查没根据的数字(答案: str, 本轮输出: str) -> list[str]:
    """答案里的硬指标数字, 有没有在本轮命令的真输出里出现过 —— 返回对不上的清单。

    ★ 只查"原样引用型"数字(百分比/容量/核数/温度)。求和、换算出来的数(如把几块盘加起来的
      总量)天然不在单条输出里, 会被一并报出来当"待核" —— 所以这里只提示、绝不改答案。
    """
    if not 答案.strip() or not 本轮输出.strip():
        return []
    有 = 归一数字(本轮输出)
    没: list[str] = []
    for 模式 in 硬指标:
        for m in 模式.finditer(答案):
            原样 = m.group(0).strip()
            if 原样 in 没:
                continue
            if 归一数字(原样) - 有:          # 归一后一个都对不上才算"没根据"
                没.append(原样)
    return 没


def 读本轮输出(结果: dict[str, Any]) -> str:
    """把这一轮每条命令落盘的完整输出读回来拼一起(没落盘的就跳过)。"""
    段: list[str] = []
    for 条 in cast(list[Any], 结果.get("calls") or []):
        if not isinstance(条, dict):
            continue
        路 = str(cast(dict[str, Any], 条).get("file") or "")
        if not 路:
            continue
        文件 = Path(路)
        if not 文件.is_absolute():
            文件 = HERE / 文件
        try:
            if 文件.is_file():
                段.append(文件.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(段)


def run_task(
    task: str,
    skill_path: str = DEFAULT_SKILL,
    model: str | None = None,
    max_rounds: int | None = None,
    on_event: ProgressFn | None = None,
) -> dict[str, Any]:
    """跑一个任务, 返回 {"answer", "reasoning", "usage", "calls"}.

    供其他程序(比如子 agent 的"递交第三个 agent 执行")直接调用。
    `calls` 是它真跑过的命令 —— 可追溯, 也用来分辨这活是真干的还是演的。
    `on_event` 是过程回显(想/说/跑/输出), 不传就一个字都不打。
    """
    if not task.strip():
        raise ValueError("任务不能是空的")

    agent = ChatAgent.from_env(model=model, system_prompt_path=skill_path)
    资料 = 预取资料(task)
    if 资料:
        agent.system_prompt = agent.system_prompt + 资料
        if on_event is not None:
            on_event("note", "(资料预取完成：手册与记忆库命中条目已注入上下文)")
    reasoning, answer, usage, calls = agent.run(task, max_rounds=max_rounds, on_event=on_event)
    return {
        "answer": answer,
        "reasoning": reasoning,
        "usage": usage,
        "calls": calls,
        # 本趟是否注入【资料】（规程 / 道理类才注入）—— 审计用：区分"据资料作答"与"自行作答"
        "资料预取": bool(资料),
        # 每条命令的完整输出落在哪 —— 进库时带上, 可追溯
        "output_files": [call["file"] for call in calls],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="exec_agent",
        description="执行 agent: 给任务 + skill, 带着手跑一次拿回结果(无终端装饰)",
    )
    parser.add_argument("task", nargs="?", help="任务文本; 不给就从 stdin 读")
    parser.add_argument(
        "--skill", default=DEFAULT_SKILL, help=f"提示词文件 (默认 {DEFAULT_SKILL})"
    )
    parser.add_argument("--model", default=None, help="覆盖 .env 里的模型名")
    parser.add_argument("--rounds", type=int, default=4, help="命令来回上限 (默认 4)")
    parser.add_argument("--json", action="store_true", help="输出结构化结果")
    args = parser.parse_args()

    task = args.task if args.task is not None else sys.stdin.read()
    if not task.strip():
        print("用法: exec_agent.py \"任务\" [--skill 路径] [--rounds N] [--json]", file=sys.stderr)
        sys.exit(2)

    result = run_task(task, skill_path=args.skill, model=args.model, max_rounds=args.rounds)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for call in result["calls"]:
            print(f"[跑了] {call['command']}", file=sys.stderr)
        print(result["answer"])


if __name__ == "__main__":
    main()

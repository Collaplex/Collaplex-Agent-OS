"""通过 OpenAI 兼容接口进行流式聊天。"""

import atexit
import json
import os
import re
import shutil
import sys
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from dotenv import load_dotenv
from openai import OpenAI

import openai

import exec_agent
import outsource_hook
import sub_agent
import 定时
import 待注入
import 清单
import 解析器

# ★ 行编辑：不 import readline 时 input() 不具备行编辑能力 —— 方向键会被当作普通字符
# 打进输入行里(实测回显 'ab^[[C'), 退格也只由终端擦最后一个字符、跟光标脱节(看着就像"退格有 bug")。
# import 这个模块的副作用就是把 input() 接到 readline 上。Windows 之类没有就跳过, 不致命。
try:
    import readline
except ImportError:  # pragma: no cover - 非 POSIX 平台
    readline = None

# 以下都取自 config/agent.json
_AGENT_CONFIG = sub_agent.load_agent_config()
# 主 agent 的提示词 —— 换这个文件就换职责 (config/agent.json 的 default_skill)
MAIN_SKILL = str(_AGENT_CONFIG["default_skill"])
UI = cast(dict[str, Any], _AGENT_CONFIG["ui"])


# 长相像 Markdown 围栏的那一行(``` / ```json) —— 只有它需要先扣着, 见 render_stream
FENCE_LINE = re.compile(r"^`{1,3}[A-Za-z0-9_-]*$")

# 输入历史(上下键翻)存此处 —— 不放 logs/（该目录进 git），也不放 /tmp（会被清）
HISTORY_FILE = (
    Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    / "collaplex_agent"
    / "history"
)


def explain_model_error(error: Exception) -> str:
    """把模型侧的错误说成人话 —— 余额没了 / 连不上 / 被限流。

    ★ 不抛一屏 traceback：那些对用户没有信息量，且一崩就打断整个 REPL
    (余额用完是必然会发生的事, 实测报 openai.AuthenticationError / status 401 这类,
    额度耗尽则是同一族带 402 的)。
    """
    status = getattr(error, "status_code", None)
    text = str(error).lower()
    if status == 401 or isinstance(error, openai.AuthenticationError):
        return "API Key 不对或没配上（看 .env）"
    if status == 402 or any(word in text for word in ("insufficient", "balance", "quota", "余额")):
        return "账户余额/额度用光了（去平台充一点，或换回本机模型）"
    if status == 429 or isinstance(error, openai.RateLimitError):
        return "被限流了（等一会儿再问）"
    if isinstance(error, openai.APITimeoutError):
        return "模型超时（本地模型慢或正忙）"
    if isinstance(error, openai.APIConnectionError):
        return "连不上模型服务（本机模型没起 / 网络不通）"
    return f"{type(error).__name__}: {error}"


def fallback_prepare() -> dict[str, Any]:
    """子 agent 那步没跑成时的退路: 只带主 skill, 不检索记忆。

    （读取的是本地文件，不依赖模型 —— 因此该路径不会再失败。）
    """
    config = sub_agent.load_config()
    try:
        skill_text = sub_agent.load_main_skill(config)
    except Exception:  # skill 文件也没了 —— 空着也让它answer, 不崩
        skill_text = ""
    return {
        "skill": skill_text,
        "skills": [str(config["main_skill"])],
        "queries": [],
        "hits": 0,
        "notes": [],
        "wanted": "",
        # 子 agent 这步整体未跑成 = 判定无结论 -> 主流程以用户原话兜底（不得静默回落自行作答）
        "broken": True,
    }


def find_tail_json(text: str) -> int | None:
    """找末尾那段 json 的起点（字符下标）; 没有返回 None.

    skill 的约定是"先输出 md 回答, 最后再输出 json" —— 模型会给那段套个 ```json
    围栏, 直接认这个围栏就行。取最后一个: 正文里就算夹着同款, 末尾那个也只会更靠后。
    模型偶尔会在 ```json 前面多吐一个空围栏, 一起藏掉。
    """
    return 解析器.找尾部JSON起点(text)


def 围栏内容(text: str) -> str:
    """取出第一段 ``` 围栏内的内容（末尾那段 json 标记就长这样）。"""
    return 解析器.围栏内容(text)


def 从JSON里捞正文(块: str) -> str:
    """整段被围栏吃掉时，尝试从该 json 中提取答案（识别几个常见键）。"""
    return 解析器.从JSON里捞正文(块)


def 捞正文(text: str) -> tuple[str, str]:
    """正文 + 末尾 json 标记 → 给人看的正文。返回 (正文, 说明)。

    ★ 为什么要兜底（2026-10-11 老板撞上): 模型偶尔会把**整段回答**套进 ```json
      围栏里 —— 这时 find_tail_json 指到 0，正文本该是空串。而 web 收尾那句
      `if 正文.strip(): 记一轮(...)` 一不成立，这一轮就**答案不显示、也不记账**，
      界面上只剩一串过程行（老板原话："坏了又是 bug"）。
      所以"整段被围栏吃掉"须作为一种待交代的情形：先从 json 中提取，
      提取不到则将原文整段展示出来 —— 宁可难看，也不让这一轮凭空消失。
    说明非空 = 走了兜底，调用方该把这句话报给界面/终端。

    ★ 兜底逻辑与两层的分工都在 `解析器/`（① 一家一件的适配件 → ② 模型无关的外壳），
      此处只是同名薄壳转发 —— 老调用点与回归用例均无需改动。
    """
    return 解析器.捞正文(text)


def read_task_flag(answer: str) -> bool | None:
    """从回答末尾那段 json 里读出 `任务结束`。

    这是 seek skill 每轮都要给的键: 判的是**用户交办的这件事整个办完没有**,
    不是这轮回答写完没有。清洗管线的看守以其作为触发器(结束 + 静默 20 分钟才清二层)。

    读不出来即返回 None —— 不得臆测：误判为 true 会导致后台提前清二层。
    """
    start = find_tail_json(answer)
    if start is None:
        return None
    body = answer[start:]
    if body.startswith("```"):
        end = body.rfind("```")
        body = body[3:end] if end > 3 else body[3:]
    body = body.strip()
    if body[:4].lower() == "json":
        body = body[4:].strip()
    try:
        data: Any = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    flag = cast(dict[str, Any], data).get("任务结束")
    if isinstance(flag, bool):
        return flag
    if isinstance(flag, str):
        return flag.strip().lower() in ("true", "1", "是", "对")
    return None


def render_stream(stream_generator: Iterable[tuple[str, str]]) -> tuple[str, str]:
    """
    将思考和回答的增量文本直接写入终端，避免反复重绘完整内容。

    生成器每次 yield (类型, 文本片段)，类型为 reasoning 或 answer。
    为降低流式输出延迟，Markdown 标记会按原文输出，不在此处解析。

    回答里**末尾那段 json** 照收不照打: 模型该输出就输出(skill 要的那份),
    但那是给程序看的, 不往终端糊。
    """
    reasoning_text = ""
    answer_text = ""
    current_type = None
    printed = 0  # 回答已经打到终端的字符数
    hidden_from: int | None = None  # 末尾 json 的起点, 从这里起藏着不打
    pending = 0  # 从这个位置起的内容还没确认是不是围栏, 先扣着不打

    for content_type, chunk in stream_generator:
        if content_type not in ("reasoning", "answer"):
            raise ValueError(f"未知的流内容类型：{content_type}")

        if content_type != current_type:
            if current_type is not None:
                sys.stdout.write("\033[0m\n")
            label = UI["reasoning_label"] if content_type == "reasoning" else UI["answer_label"]
            sys.stdout.write(f"\033[2m{label}：\033[0m")
            current_type = content_type

        if content_type == "reasoning":
            reasoning_text += chunk
            sys.stdout.write(f"\033[2m{chunk}\033[0m")
        else:
            answer_text += chunk
            hidden_from = find_tail_json(answer_text)
            cutoff = len(answer_text) if hidden_from is None else hidden_from
            # 只有"当前这一行长成围栏样(```/```json)"才扣着 —— 它可能是末尾那段 json 的开头,
            # 提前打出去就收不回。★ 不得以"这行里有反引号"作判据: 回答是文件列表/行内代码时几乎
            # 每行都带反引号, 整段回答会被一路扣着不打, 表现就是"实时输出没了"、最后一次性糊出来。
            head = answer_text[:cutoff]
            line_start = head.rfind("\n") + 1
            line = head[line_start:]
            if FENCE_LINE.match(line.strip()):
                pending = min(pending, line_start) if pending else line_start
            elif pending and line.strip():
                # 扣着的那行后面接了"有内容、又不长围栏样"的新行 -> 它是正文(代码块/行内代码), 补打
                pending = 0
            safe = pending if pending else cutoff
            if safe > printed:
                sys.stdout.write(answer_text[printed:safe])
                printed = safe
        sys.stdout.flush()

    # 收尾: 把扣着的最后一行补上(除非它是那段 json 的一部分)
    hidden_from = find_tail_json(answer_text)
    tail = len(answer_text) if hidden_from is None else min(hidden_from, len(answer_text))
    if tail > printed:
        sys.stdout.write(answer_text[printed:tail])
        printed = tail

    # ★ 整段被围栏吃掉时不得留下空答案（模型把回答写进 json 块里）—— 补出来(2026-10-11)
    兜底正文, 说明 = 捞正文(answer_text)
    if 说明:
        sys.stdout.write(兜底正文 + ("\n" if not 兜底正文.endswith("\n") else ""))
        print(f"（{说明}）")

    if current_type is not None:
        sys.stdout.write("\033[0m\n")
        sys.stdout.flush()

    return reasoning_text, answer_text

def get_terminal_width() -> int:
    """获取当前终端宽度，单位为字符。"""
    return shutil.get_terminal_size().columns


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


class StreamingChatAssistant:
    """读取提示词并调用模型，将流式内容实时输出到终端。"""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        system_prompt: str,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.system_prompt = system_prompt
        # 思考参数(按 provider 方言拼, 见 sub_agent.thinking_params) —— 空 = 这轮不开思考
        self.extra_body: dict[str, Any] = extra_body or {}

    @classmethod
    def from_env(
        cls,
        model: str | None = None,
        system_prompt_path: str = MAIN_SKILL,
    ) -> "StreamingChatAssistant":
        """从 .env 和提示词文件中创建助手实例。"""
        load_dotenv(".env")

        with open(system_prompt_path, "r", encoding="utf-8") as prompt_file:
            system_prompt = prompt_file.read()

        client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )
        resolved_model = model or os.getenv("OPENAI_MODEL") or "qwen3-vl-8b"
        return cls(client, resolved_model, system_prompt)

    def chat(
        self, user_message: str
    ) -> tuple[str, str, dict[str, int | float | None]]:
        """发送用户消息，实时输出内容并返回思考内容、回答和用量统计。"""
        request_started_at = perf_counter()
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message},
            ],
            stream=True,
            stream_options={"include_usage": True},
            extra_body=self.extra_body or None,
        )

        usage = None
        first_output_at = None

        def response_chunks():
            nonlocal usage, first_output_at

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
                    yield "reasoning", reasoning_chunk

                if delta.content:
                    if first_output_at is None:
                        first_output_at = perf_counter()
                    yield "answer", delta.content

        reasoning, answer = render_stream(response_chunks())
        output_finished_at = perf_counter()
        elapsed_seconds = (
            output_finished_at - first_output_at
            if first_output_at is not None
            else output_finished_at - request_started_at
        )
        stats = get_response_stats(usage, elapsed_seconds)
        return reasoning, answer, stats


def read_skill_label(skill_path: str) -> str:
    """从 skill 文件头部读出一行说明：name · description；读不到就退回文件名。"""
    try:
        with open(skill_path, "r", encoding="utf-8") as skill_file:
            head = skill_file.read(800)
    except OSError:
        return skill_path

    name = ""
    description = ""
    lines = head.splitlines()
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            key, _, value = line.partition(":")
            key = key.strip()
            if key == "name" and not name:
                name = value.strip()
            elif key == "description" and not description:
                description = value.strip()

    name = name or Path(skill_path).stem
    return f"{name} · {description}" if description else name


def skill_banner(skill_paths: Iterable[str]) -> str:
    """这轮调用了哪些 skill —— 一个 skill 占一行，不往后面串。"""
    lines: list[str] = ["调用 skill："]
    lines.extend(read_skill_label(path) for path in skill_paths)
    return "\n".join(lines)


def describe_intercept(prepared: dict[str, Any]) -> str:
    """拦截层简报：子 agent 本轮做了什么。

    ★ 2026-10-09 老板点名: 以前先判 wanted 就 return，于是"缺 skill"那轮**永远看不到记忆判决**，
      看日志的人以为"它从来不查记忆"。改成两段拼起来 —— 缺不缺 skill 一段、记忆一段，都报。
    """
    queries = cast(list[str], prepared.get("queries") or [])
    # ★ 条数只认一个来源, 但**两条 return 都可能用**(2026-10-13 修): 走左链那条 return 带 "记忆"
    #   列表, 自答那条以前只带 "hits" 计数 —— 简报读不到列表就报 0, 界面天天假报"记忆 0 条"。
    #   现在优先数列表, 没有列表就退回 hits 计数(两边都是同一批命中的产物)。
    记忆列表 = prepared.get("记忆")
    条数 = (
        len(cast(list[object], 记忆列表))
        if isinstance(记忆列表, list)
        else int(prepared.get("hits") or 0)
    )
    段: list[str] = []
    if prepared.get("broken"):
        段.append("判定这步没给出结论（输出被截 / 解析失败）")
    if prepared.get("wanted"):
        段.append(f"缺 skill：{prepared['wanted']}")
    if not queries:
        段.append("记忆 0 条（这步没给查询、也没兜底）")
    elif prepared.get("记忆兜底"):
        段.append(f"模型说不用查 → 程序拿你的原话兜底 · 记忆 {条数} 条")
    else:
        段.append(f"查询 {len(queries)} 条 · 记忆 {条数} 条")
    尾 = f" · skill {len(str(prepared.get('skill') or ''))} 字符"
    if prepared.get("memory_budget"):
        尾 += f" · 记忆上限 {prepared['memory_budget']}"
    return f"[子agent] {' · '.join(段)}{尾}"


def retrieval_term(prepared: dict[str, Any], question: str) -> str:
    """这轮拿什么去检索 skill: 子 agent 说缺的能力; 判定那步没给出结论时拿用户原话兜。

    判定属模型行为，会失效（输出被截 / 解析失败未被接住）。**"要不要派活"不能因为一步坏了
    就变成"不需要"** —— 那等于回落自己答, 而机器状态/文件读写这类问题, 主 skill(seek)
    执行体不可用时，它只会答"我没有工具"，或把命令交给用户自行执行（实测已踩坑）。

    所以: 判定没结论 -> 拿用户原话当检索词, 交由检索 + 挑选决定派谁。
    明确说了"不需要"(need=false 且没坏) -> 返回空, 保持原行为(不乱派)。
    """
    wanted = str(prepared.get("wanted") or "").strip()
    if wanted:
        return wanted
    if bool(prepared.get("need")) or bool(prepared.get("broken")):
        return question
    return ""


def 归一技能名(名: str) -> str:
    """把模型可能写出来的各种形态归一成一个 skill 名：`skill/file` → `file`。

    ★ 实测模型会写 `skill/file`、`file.md`、带前后空格/全角空格的写法 —— 拿原串做相等比较
      会把"挑对了"判成"没抄准"。归一只做**路径 / 后缀 / 大小写**三件事，不做模糊猜测。
    """
    文 = 名.strip().replace("　", " ").replace("\\", "/").lower().strip().rstrip("/")
    for 尾 in ("/skill.md", "/skill", ".md"):
        if 文.endswith(尾):
            文 = 文[: -len(尾)]
            break
    文 = 文.strip("/")
    if 文.startswith(("skill/", "skills/")):
        文 = 文.split("/", 1)[1]
    return 文.split("/")[-1].strip()


def 读触发词(skill_file: str) -> list[str]:
    """读 SKILL.md 头部 frontmatter 里的 `trigger_keywords` —— 兜底派活时拿它比贴合度。

    ★ 为什么要它：纯余弦在"一句话两个任务"的问句上会被一半的意图带偏（实测把 kali 排在
      linux 前面），而触发词是 skill 作者手写的先验，比余弦稳。读不到就返回空表。
    """
    try:
        with open(skill_file, "r", encoding="utf-8") as 文件:
            头 = 文件.read(1200)
    except OSError:
        return []
    for 行 in 头.splitlines():
        if 行.strip().startswith("trigger_keywords"):
            _, _, 值 = 行.partition(":")
            return [词.strip().strip("\"'") for 词 in 值.strip().strip("[]").split(",") if 词.strip()]
    return []


def 最贴的候选(问题: str, 候选: list[dict[str, Any]]) -> dict[str, Any]:
    """兜底派活时挑一个候选：按**词面贴合**数比（名字命中 2 分，触发词每命中一个 1 分）。

    ★ 规矩：模型说"都不合适"时不许回落自己答，但也不能盲取检索第一名 —— 实测
      「统计 vllm 里 .py/.cu 文件数 + 查 8790 端口进程」纯余弦把 kali(安全扫描) 排在
      linux(本机操作) 前面（0.5996 vs 0.5600），而 linux 的触发词里正写着 端口 / 进程。
      打平就按检索原来的名次（保持稳定，不引入新的玄学系数）。
    """
    问 = 问题.casefold()
    最佳 = 候选[0]
    最佳分 = -1
    for 件 in 候选:
        名 = 归一技能名(str(件.get("name", "")))
        分 = 2 if 名 and 名 in 问 else 0
        分 += sum(1 for 词 in 读触发词(str(件.get("skill_file", ""))) if 词 and 词.casefold() in 问)
        if 分 > 最佳分:
            最佳, 最佳分 = 件, 分
    return 最佳


def pick_skill(
    client: OpenAI,
    model: str,
    question: str,
    candidates: list[dict[str, Any]],
    上下文: str = "",
) -> dict[str, Any] | None:
    """主 agent 的判断（图上"主agent"那格）：挑一个 skill，并声明要交办的活。

    挑不出来返回 None；挑出来返回那个候选 + 一个 `声明` 字段（递给执行体的活）。
    提示词在 config/sub_agent.json 的 prompts.pick（不硬编码在代码里）。
    """
    listing = "\n".join(
        f"{position + 1}. {candidate['name']} —— {candidate['description']}"
        for position, candidate in enumerate(candidates)
    )
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": sub_agent.load_prompt("pick")},
            {
                "role": "user",
                "content": (
                    f"任务：{question}\n"
                    + (
                        f"\n本次对话最近几轮（任务里的「刚才 / 那个数」指的就是这里）：\n{上下文}\n"
                        if 上下文
                        else ""
                    )
                    + f"\n候选 skill：\n{listing}"
                ),
            },
        ],
    )
    raw = completion.choices[0].message.content or ""
    payload = sub_agent.parse_json_object(raw)
    if not bool(payload.get("use")):
        return None

    declaration = str(payload.get("声明") or "").strip() or question
    wanted_name = str(payload.get("pick") or "").strip()
    要的 = 归一技能名(wanted_name)
    for candidate in candidates:
        if 要的 and 归一技能名(str(candidate["name"])) == 要的:
            return {**candidate, "声明": declaration}
    # ★ 名字对不上时**不许静默取第一名**（原来那句 `return candidates[0]`）—— 那会偷偷派错件：
    #   模型写 `skill/file`、`file.md` 都算"没抄准"，于是一律被换成检索第一名。名字归一对不上
    #   就退回 None，由上游按"模型说都不合适"那条路走：有日志、也仍走不可交办的过滤。
    print(f"[主agent] 模型挑的名字「{wanted_name or '空'}」对不上任何候选 → 不按名字派，走回落")
    return None


def preflight() -> None:
    """开工前体检：检索靠的是**嵌入服务**，它不在的时候检索必失败、而失败会被
    静默吞成"检索不出候选" -> 回落主 agent 自行作答 -> **开始编造**（2026-10-08 踩过：
    把本机说成"双路 Xeon 华为 KVM 虚拟机"，真因只是嵌入服务没起）。

    ★ 所以这里只做一件事：**在编答案之前，先把"我瞎了"说出来**。不通就警告，
      绝不阻塞（用户可能就是要用主模型硬答）。
    """
    import urllib.error
    import urllib.request

    要看 = [
        ("嵌入(检索/入库靠它)", str(os.getenv("EMBEDDING_BASE_URL", "http://127.0.0.1:8199/v1"))),
        ("主模型", str(os.getenv("OPENAI_BASE_URL", ""))),
    ]
    坏的: list[str] = []
    for 名, 地址 in 要看:
        if not 地址:
            continue
        根 = 地址.rstrip("/")
        if 根.endswith("/v1"):
            根 = 根[:-3]
        try:
            urllib.request.urlopen(f"{根}/health", timeout=3)
        except (urllib.error.URLError, TimeoutError, OSError):
            # 云端端点没有 /health —— 只对本地端点报（本地才有这个约定）
            if 根.startswith(("http://127.0.0.1", "http://localhost")):
                坏的.append(f"{名}（{地址}）")
    if 坏的:
        print("=" * 80)
        print("★ 开工前体检：这些服务没起 ——")
        for x in 坏的:
            print(f"    {x}")
        print("  嵌入服务不在时，**检索 skill 一定失败**，我可能会把答案编出来而不是去查。")
        print("  起法：./start_models.sh start   （或 ./本地兜底.sh 切到别的端点）")
        print("=" * 80)


def gather_evidence(
    question: str,
    wanted: str,
    client: OpenAI | None = None,
    model: str | None = None,
) -> dict[str, str] | None:
    """检索不出 skill 时走这条：把"想要什么"变成**一条真命令**，跑掉，拿回真实输出。

    为什么必须有这一环（2026-10-08 实测）：
      判断步判得对（need=true, wanted="查根分区剩余空间"），但 **skill 库里没有"查磁盘"
      这种件** ⇒ 检索不出候选 ⇒ 试外援 ⇒ 主 agent 自己答 ⇒ **开始编**
      （实测把 load average 编成"污垢累积速率"、把二层热库说成"-18℃冷冻库"）。
      A/B 实测：补上"取数 → 喂回"这一步，同一个模型『该动没动』从 14/14=100% 掉到 1/14=7%。

    ★ 两道闸：这里只放**读本机事实**的命令；exec_agent.blocked_reason 仍在后面兜底。
    """
    if client is None or model is None:
        client, model = sub_agent.build_client()

    prompt = (
        "把下面这个『要查的东西』变成**一条**能在本机直接跑的 shell 命令。\n"
        "只输出命令本身：不要解释、不要代码块、不要引号包裹、不要多行。\n"
        "只许读本机事实（df / free / lscpu / ss / ps / date / uptime / tail / head / ls / cat / find / wc）。\n"
        "★ 要读某个文件就用 cat / head，要数文件个数就用 find … | wc -l，不要把问题换成别的查询。\n"
        "★ 不许出现任何写操作（rm / mv / dd / mkfs / systemctl / kill / apt / pip / sed -i / 重定向）。\n\n"
        f"要查的东西：{wanted}\n问题背景：{question}"
    )
    # ★ max_tokens 必须留够：short_call 不走 client 的 extra_body，**关不掉思考**，
    #   而 mimo 思考默认开 —— 给 60 会被思考耗尽，content 直接返回空串（实测已踩坑）。
    原样 = sub_agent.short_call(client, model, prompt, question, 300)
    命令 = 原样.strip().splitlines()[0].strip().strip("`").strip() if 原样.strip() else ""
    if not 命令 or len(命令) > 200:
        return None
    # ★ 第二道闸：模型可能不听话，出现写操作就当没这回事（exec_agent 的闸还在后面）
    if re.search(r"(^|[;&|]\s*)(rm|mv|dd|mkfs|systemctl|kill|pkill|apt|pip|truncate)\b|>|sed\s+-i", 命令):
        print("[取数] 模型给的命令带写操作 → 作废")
        return None

    输出 = exec_agent.run_command(命令, timeout=25)
    return {"命令": 命令, "输出": 输出}


# ★ 不可交办的 skill —— 派给执行体等于白派(2026-10-10 实测):
#   ① `skill_search` 就是"挑 skill"这一步**自己**（元技能）。把它交给执行体, 它只能照
#      SKILL.md 再挑一遍, 交回一篇"该用 skill/search…理由…"的理由书 —— 用户的活一件没干。
#      （那一轮 exec 只跑了一条命令、且与 skill_search/SKILL.md 的「怎么跑」逐字一致;
#        答案正文 = 挑 skill 的结论, 用户问的"支不支持中文"一个字没有。）
#   ② `outsource`（摇人花钱）/ `mtp`（交叉验证）都不是"能真干活"的件 ——
#      普通事实问题被派去摇云端 = 花冤枉钱且答非所问。实测同一问题检索回来的**第一名就是
#      outsource** —— 挑选步说"都不合适"时的回落会直接把它派出去。
#   名单在 config/sub_agent.json 的 `skill_retrieval.不可交办`，不硬编码在代码里。
不可交办_默认: tuple[str, ...] = ("skill_search", "outsource", "mtp")

# 挑 skill 这一步的结论落一行盘 —— 出问题可复盘（web 侧原本不记录"挑中谁"，出问题只能靠
# 执行体跑了哪条命令反推)。
挑技能日志 = Path(__file__).resolve().parent / "logs" / "挑技能.jsonl"


def 不可交办名单() -> tuple[str, ...]:
    """从配置读"不许派给执行体"的 skill 名单；读不到就退回内置默认（不静默放行）。"""
    段 = sub_agent.load_config().get("skill_retrieval")
    if not isinstance(段, dict):
        return 不可交办_默认
    名单 = cast(dict[str, Any], 段).get("不可交办")
    if not isinstance(名单, list):
        return 不可交办_默认
    return tuple(str(x) for x in cast(list[Any], 名单))


def 能交办的(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把不可交办的件从候选里剔掉 —— 剩下的才可能被派给执行体。

    挑选步与回落都走这张剔完的清单（回落取第一名，也在这张清单上取）。
    """
    都不可派 = set(不可交办名单())
    留 = [c for c in candidates if str(c.get("name")) not in 都不可派]
    剔 = [str(c["name"]) for c in candidates if str(c.get("name")) in 都不可派]
    if 剔:
        print(f"[检索skill] 剔掉不可交办的: {' / '.join(剔)}")
    return 留


def 记_挑技能(
    question: str,
    wanted: str,
    候选: list[dict[str, Any]],
    可派: list[dict[str, Any]],
    模型挑中: dict[str, Any] | None,
    派出: dict[str, Any] | None,
    attempt: int,
) -> None:
    """挑 skill 的结论落一行 JSONL —— 出事能复盘。

    2026-10-10 之前 web 侧完全不记录（挑中谁、声明是什么都不落），出问题只能靠"exec 跑了哪条
    命令"反推。一行里要能看出：检索词、候选与分数、剔完剩谁、模型挑了谁（可能"都不合适"）、
    最后**派给谁** —— 光有"模型挑中"不够：捡回"都不合适"那条路时，看得出派给谁才知道对错。
    """
    行 = {
        "时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "问": question[:200],
        "检索词": wanted[:200],
        "第几次": attempt,
        "候选": [
            {"name": c.get("name"), "score": c.get("score")} for c in 候选
        ],
        "剔完可派": [str(c.get("name")) for c in 可派],
        "模型挑中": (模型挑中 or {}).get("name"),
        "派出": (派出 or {}).get("name"),
        "声明": str((派出 or 模型挑中 or {}).get("声明") or "")[:400],
    }
    try:
        挑技能日志.parent.mkdir(parents=True, exist_ok=True)
        with 挑技能日志.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(行, ensure_ascii=False) + "\n")
    except OSError as error:  # 日志写不进去不许影响这一轮
        print(f"[挑skill] 日志没写成：{error}")


def find_skill_for(
    question: str,
    wanted: str,
    client: OpenAI | None = None,
    model: str | None = None,
    上下文: str = "",
) -> dict[str, Any] | None:
    """左链前半（图上功能2）：检索skill -> 主agent 判断够不够。

    够了返回选中的候选（含 skill_file 和 声明）；候选一个都检索不出来就再检索一次
    （最多 max_retry 次），再不行返回 None。

    ★ 模型说"清单里都不合适"时**不许回落自己答** —— 那是死路：机器状态/文件读写这类
    问题，主 skill(seek) 手里没有执行体，只会答"我没有工具"或者是把现成的命令丢给用户
    自己跑。候选本来就是检索出来的，最相关的那个就是最好的兜底。

    ★ 但**不可交办的件必须在挑选之前就剔掉**（元技能 skill_search / 花钱的 outsource 与
    mtp）—— 交办"再挑一遍"或"摇云端"都不是干活, 见 `能交办的()` 上面那段实测。
    剔完一个都不剩, 才认"这活手头没件能干", 回落自己答（说人话, 不许编）。
    client / model 留出参数是为了测试注入假模型（默认自己建）。
    """
    config = sub_agent.load_config()
    skill_search = dict(config["skill_search"])
    retry_times = int(config["skill_retrieval"]["max_retry"])
    if client is None or model is None:
        client, model = sub_agent.build_client()

    candidates: list[dict[str, Any]] = []
    可派: list[dict[str, Any]] = []
    回合 = 0
    for attempt in range(retry_times + 1):
        回合 = attempt + 1
        candidates = sub_agent.search_skills(wanted, skill_search)
        if not candidates:
            print(f"[检索skill] 第 {回合} 次没找到候选")
            break

        可派 = 能交办的(candidates)
        if not 可派:
            print("[检索skill] 候选里只剩不可交办的件（元技能/花钱的）→ 不派, 回落自己答")
            break

        print(f"[检索skill] 第 {回合} 次拿到 {len(可派)} 个可派的候选：")
        for candidate in 可派:
            print(f"    {candidate['name']} · {candidate['description'][:60]}")

        picked = pick_skill(client, model, question, 可派, 上下文=上下文)
        if picked is not None:
            记_挑技能(question, wanted, candidates, 可派, picked, picked, 回合)
            return picked
        print("[主agent] 模型说清单里都不合适 → 按最相关的候选派（不回落自己答）")
        兜底候选 = 最贴的候选(question, 可派)
        兜底 = {**兜底候选, "声明": question}
        记_挑技能(question, wanted, candidates, 可派, None, 兜底, 回合)
        return 兜底

    print("[主agent] 检索不出能派的候选，回落自己答")
    记_挑技能(question, wanted, candidates, 可派, None, None, 回合)
    return None


class StreamPrinter:
    """过程回显 —— 把「它在干什么」边发生边输出，不让终端始终是黑盒。

    两类事件(两个 agent 都发同样的):
      增量式: think(想)/reply(说) —— 边生成边打, 不带换行, 靠 _break 收尾
      整行式: command(马上要跑的命令)/output(命令输出, 只打开头几行)/output_file(全文落哪)
    tag 由调用方从 config 的 ui 段取(exec 一个、子 agent 一个)。
    """

    HEAD_LINES = 10      # 命令输出只打开头这几行
    HEAD_CHARS = 800

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.current: str | None = None
        self.dim = False

    def __call__(self, kind: str, text: str) -> None:
        if kind == "think":
            self._delta("思考", text, dim=True)
        elif kind == "reply":
            self._delta("说", text, dim=False)
        elif kind == "command":
            self._break()
            print(f"[{self.tag}] 跑：{text}")
        elif kind == "output":
            self._break()
            print(f"[{self.tag}] 输出：{self._preview(text)}")
        elif kind == "output_file":
            print(f"[{self.tag}] 全文：{text}")
        elif kind == "note":
            self._break()
            print(f"[{self.tag}] {text}")

    def _delta(self, name: str, text: str, dim: bool) -> None:
        if self.current != name:
            self._break()
            sys.stdout.write(f"\033[2m[{self.tag}] {name}：\033[0m")
            self.current = name
            self.dim = False
        if dim != self.dim:
            # 只在"变暗/变亮"那一下写转义 —— 每块都包一对的话, 一段长回答能刷出上千个 \033
            sys.stdout.write("\033[2m" if dim else "\033[0m")
            self.dim = dim
        sys.stdout.write(text)
        sys.stdout.flush()

    def _break(self) -> None:
        """流式的行得自己收尾(它不像 print 那样自带换行)。"""
        if self.current is not None:
            sys.stdout.write("\033[0m\n")
            sys.stdout.flush()
            self.current = None
            self.dim = False

    def close(self) -> None:
        self._break()

    def _preview(self, text: str) -> str:
        lines = text.strip().splitlines() or ["(没有输出)"]
        head = lines[: self.HEAD_LINES]
        body = "\n".join(head)
        if len(lines) > self.HEAD_LINES:
            body += f"\n…(共 {len(lines)} 行)"
        if len(body) > self.HEAD_CHARS:
            body = body[: self.HEAD_CHARS] + "…"
        return body.replace("\n", "\n    ")   # 续行缩进, 免得跟别的行混作一团


def 打读秒(剩: float) -> None:
    """阻塞式定时等着的时候, 一行原地刷新(读秒)."""
    print(f"\r[定时] 还剩 {定时.剩余说法(剩)} …", end="", flush=True)


def setup_readline() -> None:
    """把行编辑的历史接上: 上下键能翻到上次会话问过的问题。

    （★ 连左右移光标也依赖它 —— 不 import readline 时 input() 会把方向键当普通字符打入行内。）
    """
    if readline is None:
        return
    readline.set_history_length(500)
    try:
        readline.read_history_file(str(HISTORY_FILE))
    except OSError:
        pass  # 头一次跑没有这个文件, 正常
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    atexit.register(readline.write_history_file, str(HISTORY_FILE))


def main() -> None:
    setup_readline()
    # 开工前先探模型端点：未启动 / 名字不符就把原因说清楚，不抛一堆 traceback
    try:
        probe_client, model = sub_agent.build_client()
    except Exception as error:  # .env 没配全 —— 说清是哪一项缺
        print(f"模型调用信息没配好：{error}（看 .env）")
        return
    reachable, note = sub_agent.check_endpoint(probe_client, model)
    if note:
        print(note)
    if not reachable:
        print("起好了再跑（地址/模型名看 .env 的 OPENAI_BASE_URL、OPENAI_MODEL）。")
        return
    # ★ 上面那条只探了**主模型** —— 检索要的是**嵌入服务**(:8199)，它不在这条检查里。
    #   嵌入没起时检索必失败、而失败会被吞成"检索不出候选" -> 回落硬答 -> **开始编**
    #   （2026-10-08 实测：把本机说成"双路 Xeon 华为 KVM 虚拟机"，真因只是嵌入没起）。
    preflight()

    # 定时任务: 本进程用自己的那张表(cli), 起来先重挂一次 —— 过期条目补一次, 有活就把线程起起来
    定时.进程("cli")
    # ★ 编排: 这一对话的键 —— 清单 / 注入箱 / 账都按它分行；并注入环境供 skill 子进程使用
    #   （skill 读 COLLAPLEX_CHAT_ID 决定写哪一行，不靠猜）
    对话键 = "cli"
    os.environ["COLLAPLEX_CHAT_ID"] = 对话键
    重挂果 = 定时.重挂()
    if 重挂果["挂着"] or 重挂果["刚响"]:
        print(f"[定时] 重挂: 挂着 {重挂果['挂着']} 条"
              + (f" · 补了 {重挂果['刚响']} 条（早就该响的）" if 重挂果["刚响"] else "")
              + f" · 表 {定时.表()}（{定时.行键()} 那一行）")

    # 本次会话最近几轮的问答原文 —— 指代性追问（"刚才那个数"）依赖它，不依赖检索。
    #   ★ 多轮上下文不自动清空(老板定的): 只有 /new 或重开进程才清。
    历史: list[dict[str, str]] = []

    while True:
        width = get_terminal_width()  # 获取终端宽度
        # ★ 外援判据要的「从用户提问到现在花了多少秒」—— 计时从用户开口那一刻起
        turn_started = perf_counter()

        print(UI["banner_char"] * width)
        # ★ 开场注入：到点的提醒先交回主 agent —— 以其作为本轮输入，不必等用户输入
        到点的提醒 = 定时.取待办()
        # ★ 编排也走这个口子(同一个注入箱): 定时没到点就问编排有没有话要说
        编排的话 = None if 到点的提醒 else 待注入.取(对话键)
        if 到点的提醒:
            print("[定时] 到点了（这一轮开场先办它）")
            # 作业结果自己带 [作业] 这张牌子(形如 "[作业] 喂猫（跑完·退出码 0，跑了 8 秒)\n  日志尾…"),
            # 再套一层 [定时器] 会变成 "[定时器] [作业] …" —— 谁的东西谁挂牌。
            user_message = 到点的提醒 if 到点的提醒.startswith("[作业]") else f"[定时器] {到点的提醒}"
        elif 编排的话:
            print("[编排] 上一件完了 —— 这一轮接着推清单")
            user_message = f"[编排] {编排的话}"
        else:
            try:
                user_message = input(str(UI["prompt"]))  # 等用户说话
            except (EOFError, KeyboardInterrupt):
                # 管道喂完一句话 / 手敲 Ctrl-D / Ctrl-C：干净退出，不抛一串 traceback
                print(f"\n{UI['exit_word']}")
                break
            if user_message == UI["exit_command"]:
                print(UI["exit_word"])
                break
        # 这一轮的记号(定时用: 认「哪条是这一轮登记的」—— 登记发生在 skill 子进程里,
        # 拿时刻比跨进程不可靠, 记号跟着环境走才对得上)
        轮记号 = 定时.开一轮()
        # 有新输入 —— 立即暂停计时，不让清洗看守在模型思考期间清二层
        # (任务结束 先写 false: 这一轮还在办; 答完再看模型怎么说)
        sub_agent.note_activity(False, user_message)

        print(UI["divider_char"] * width)
        print(skill_banner([MAIN_SKILL])) # 有了问题, 才说这轮用哪个 skill

        # 拦截: 问题先经子 agent —— 分析 / 检索记忆 / 按标准拼, 拼装成 skill 再交主模型思考
        # 本轮需多次调用模型（分析 + 判断）才能出结果，先输出一行提示，以免观感上像卡死
        print(UI["init_label"])
        # 子 agent 这两步也把输出实时报出来(本地模型偶尔复读时, 至少看得见它在吐什么)
        sub_stream = StreamPrinter(str(UI["subagent_tag"]))
        try:
            prepared = sub_agent.prepare_skill(
                user_message, on_event=sub_stream, 历史=历史
            )
        except Exception as error:  # 模型侧什么都可能 —— 一律说人话, 不崩
            print(f"{UI['error_label']}（子agent）：{explain_model_error(error)}")
            print(UI["error_hint"])
            prepared = fallback_prepare()
        finally:
            sub_stream.close()
        print(describe_intercept(prepared))

        # 左链: 子 agent 说缺 skill -> 检索skill -> 主agent 判断 -> 声明 -> 递交 exec agent
        term = retrieval_term(prepared, user_message)
        if term:
            if term == user_message:
                print("[主agent] 判定那步没给出结论 → 拿你的原话去检索 skill")
            # ★ 把"最近几轮"递给挑选步: 交办声明该把"刚才那个数"解成具体的值
            picked = find_skill_for(
                user_message, term, 上下文=sub_agent.recent_turns_text(历史)
            )
            if picked is not None:
                declaration = str(picked["声明"])
                print(f"[主agent] 声明：{declaration}")
                print(f"[主agent] 递交 exec agent（提示词 = {picked['name']}）")
                # 这个 skill 带命令库就先由程序查好 —— 检索是确定性的活, 不指望模型自发去查
                briefing = sub_agent.command_library_briefing(
                    str(picked["source"]), user_message
                )
                if briefing:
                    print("[命令库] 程序已先查好条目, 随任务贴给 exec")
                # ★ 左链也带上召回的上下文 —— exec 常要"接着上文算", 光有声明它不知道上文的数
                上下文 = sub_agent.memory_briefing(
                    cast(list[dict[str, Any]], prepared.get("记忆") or [])
                )
                if 上下文:
                    # ★ 放在命令库**前面**: 先读到"刚才发生了什么", 才不会被命令库里的示例数字带跑
                    briefing = 上下文 + briefing
                    print(f"[记忆] 随任务贴给 exec（{prepared['hits']} 条 / {len(上下文)} 字符）")
                # 本轮需一次模型调用 + 真实执行命令，也先输出一行提示
                print(UI["exec_label"])
                # 过程回显: 它在想什么、说了什么、要跑哪条命令、命令吐出什么 —— 边发生边打。
                # 不接的话"正在执行…"之后就是一整段黑盒(命令跑多久都看不见)。
                stream = StreamPrinter(str(UI["exec_tag"]))
                try:
                    result = exec_agent.run_task(
                        declaration + briefing,
                        skill_path=str(picked["skill_file"]),
                        on_event=stream,
                    )
                except Exception as error:
                    # 余额用完 / key 失效 / 云端抽风 —— 说清是哪一类, 这轮不动手, 但 REPL 接着活着
                    print(f"{UI['error_label']}（exec agent）：{explain_model_error(error)}")
                    print(UI["error_hint"])
                    continue
                finally:
                    stream.close()
                if result["calls"]:
                    config = sub_agent.load_config()
                    saved = sub_agent.save_to_tier2(
                        user_message,
                        str(result["answer"]),
                        dict(config["rag"]),
                        declaration=declaration,
                        output_files=cast(list[str], result.get("output_files") or []),
                    )
                    print(f"[入二层库] {saved}")
                else:
                    print("[入二层库] 它没真跑过命令, 产出不算话 —— 不入库")
                print(UI["divider_char"] * width)
                print(result["answer"])
                历史.append({"问": user_message, "答": str(result["answer"])})
                历史[:] = 历史[-4:]
                # ★ 阻塞式定时（「就在这等着」）: 框架**就在这一轮里等**, 每秒读秒。
                #   等到点时 等() 自己会把它标成「到点待注入」, 于是下一轮开场就把它交回主 agent。
                本轮的 = 定时.本轮的阻塞条目(轮记号)
                if 本轮的:
                    print(f"[定时] 阻塞式 {len(本轮的)} 条 —— 就在这一轮里等，每秒读秒")
                    for 条 in 本轮的:
                        if 定时.重新计时(条):
                            print("[定时] 倒计时从「开始等」这一刻重新起算")
                        到点话 = 定时.等阻塞(条, 打读秒)
                        print(f"\r[定时] {'到点了' if 到点话 else '这条被撤了'}"
                              + " " * 20)
                # ★ 编排（清单推进）: 这一件干完了 —— 清单里还有下一件就把主 agent 叫回来接着推。
                #   一轮只递一件：消息走「待注入」通道，下一轮开场拿到它，于是整张单一轮轮推完。
                #   ★ 判断归主 agent：这里只递消息 + 记数，不替它判「这件算不算好」。
                exec总数 = 清单.记一次exec(对话键)
                上限 = int(清单.配置().get("对话_exec上限") or 50)
                好了数, 总件 = 清单.进度(对话键)
                下件 = 清单.下一件(对话键)
                if 下件 is not None and exec总数 >= 上限:
                    print(f"[编排] 这一对话已经起了 {exec总数} 次 exec（上限 {上限}）—— 不再自动往下推")
                    清单.推进(对话键, int(下件["序号"]), "卡住", f"对话 exec 次数到顶（{上限}）")
                elif 下件 is not None:
                    说法 = f"清单（{好了数}/{总件}）下一件：{下件['说明']}"
                    if str(下件.get("做法") or ""):
                        说法 += f"｜做法：{下件['做法']}"
                    if str(下件.get("判据") or ""):
                        说法 += f"｜判据：{下件['判据']}"
                    说法 += "　—— 干完调 skill/orchestra 的 done <序号>；这件不对就 retry（上限 3 次）。"
                    print(f"[编排] {好了数}/{总件} 完了 —— 下一件：{下件['说明']}")
                    待注入.放(对话键, "编排", 说法)
                continue  # 这轮活由 exec agent 干完了, 不再让主 agent 自己答

            # ★★ 检索不出 skill ≠ 没法答（2026-10-08 实测的断点就在这儿）：
            #   判断步说 need=true/wanted="查根分区剩余空间"（判得对），但 skill 库里
            #   根本没有"查磁盘"这种件 ⇒ 检索不出 ⇒ 原来直接去试外援/自己答 ⇒ **开始编**。
            #   补上这一环：把 wanted 变成**一条真命令**跑掉，输出贴给主 agent 当事实。
            #   A/B 实测：同模型『该动没动』从 14/14=100% 掉到 1/14=7%。
            证据开关 = sub_agent.load_agent_config().get("evidence", {})
            if bool(证据开关.get("enabled", True)):
                证据 = gather_evidence(user_message, term)
                if 证据 is not None:
                    print(f"[取数] $ {证据['命令']}")
                    片段 = str(证据["输出"])[: int(证据开关.get("max_chars", 2000))]
                    prepared["skill"] = (
                        f"{prepared['skill']}\n\n"
                        f"## 本机实际数据（程序刚替你查的，**直接用这些答，别再自己推测**）\n"
                        f"$ {证据['命令']}\n{片段}"
                    )
                    prepared["取数"] = 证据["命令"]
                else:
                    print("[取数] 没拿到可用命令 → 保持原行为")

        # ★ 外援自动触发（程序判，不许模型自己说"拿不准"）—— 落点就在这一站：
        # 左链未接住、本应"回落自行作答"。外援取得的材料**注入主 agent 的 skill 中**，
        # 由主 agent 自己综合/呈现（这一件不替它下结论）。
        prepared["左链检索不到"] = bool(term)
        slow = round(perf_counter() - turn_started, 1)
        hook = outsource_hook.decide(user_message, prepared, slow)
        if hook["摇"]:
            print(f"[外援] 自动触发（{hook['因为']}）")
            try:
                hooked = outsource_hook.run(
                    user_message, prepared, slow, say=lambda text: print(f"[外援] {text}")
                )
            except Exception as error:  # 云端什么都可能 —— 说人话, 别把主链路带崩
                print(f"{UI['error_label']}（外援）：{explain_model_error(error)}")
                hooked = {"材料": "", "因为": "外援这趟出错了"}
            if hooked.get("材料"):
                material_text = str(hooked["材料"])
                prepared["skill"] = f"{prepared['skill']}\n\n{material_text}"
                print(
                    f"[外援] {hooked['级别']} 回来了"
                    f"（{hooked['家']} · {float(hooked['金额']):.5f} 元）"
                    f"→ 贴给主 agent 当参考（skill 长了 {len(material_text)} 字符）"
                )
            else:
                print(f"[外援] 没接上：{hooked.get('因为')}（维持原样，该说没有就说没有）")
        elif outsource_hook.load_trigger().get("开关"):
            print(f"[外援] 不摇：{hook['因为']}")

        """创建助手并发送示例消息。"""
        try:
            client, model = sub_agent.build_client()
            routing = sub_agent.load_routing()
            think_body, think_note = sub_agent.thinking_params(
                str(client.base_url),
                model,
                bool(prepared.get("think")),
                routing,
            )
            print(
                f"[思考] {'开' if prepared.get('think') else '关'}"
                f"（{prepared.get('think_source')}：{prepared.get('think_reason')}）"
                f"｜{think_note}"
            )
            assistant = StreamingChatAssistant(
                client, model, prepared["skill"], extra_body=think_body
            )
            _, answer_text, stats = assistant.chat(user_message)
        except Exception as error:
            print(f"{UI['error_label']}（主agent）：{explain_model_error(error)}")
            print(UI["error_hint"])
            continue
        # 这轮任务结束了没有 —— 留给清洗管线的看守
        sub_agent.note_activity(read_task_flag(answer_text), user_message)

        # ★ 普通问答也要入二层热库。以前只有 exec 真跑过命令才入库, 于是
        #   "记一下: xxx" 这种轮次只在嘴上记下了 —— 下一轮追问必然"我这边没有记录"。
        #   标清来源: 这是主 agent 自答, 没经过执行体验证, 清洗时能分辨。
        try:
            saved = sub_agent.save_to_tier2(
                user_message,
                answer_text,
                dict(sub_agent.load_config()["rag"]),
                来源="主agent 自答(未经执行体验证)",
            )
            print(f"[入二层库] {saved}")
        except Exception as error:  # 入库失手不该把这轮回答搅了
            print(f"[入二层库] 失败：{error}")
        历史.append({"问": user_message, "答": answer_text})
        历史[:] = 历史[-4:]

        if stats["tokens_per_second"] is not None:
            print(
                "Token 用量："
                f"输入 {stats['prompt_tokens']}，"
                f"输出 {stats['completion_tokens']}，"
                f"合计 {stats['total_tokens']}；"
                f"生成速度 {stats['tokens_per_second']:.2f} tokens/s"
            )
        else:
            print("Token 用量或生成速度不可用（接口未返回 usage 数据）。")


if __name__ == "__main__":
    main()

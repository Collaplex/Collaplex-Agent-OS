"""子 agent: 问题进来先分析要哪些记忆, 取回来按标准拼成 skill, 再触发主 agent 思考.

对应 diagrams/sub-agent.drawio, 两条链:

  右链(功能1, 主入口):
    等待触发 -> 问题 -> 分析 -> 判断 -> 检索需要的记忆 -> 按照标准拼接skill
             -> 载入主skill系统提示词 -> 触发agent开始思考 -> 回"等待触发"

  左链(功能2, 执行主 agent 的 skill 需求):
    判断 --no(手头缺 skill)--> 检索skill -> 返回skill需要列表 -> 主agent (main.py)
       -> 不够就再检索一次(max_retry) -> 够了就 递交第三个agent执行 -> 入二层库

- **判断**：问模型"本轮是否需要一项手头没有的 skill"；需要则走左链，不需要则走记忆链。
  开关 = config/sub_agent.json 的 skill_retrieval.enabled.
- **拼接标准**: 照 diagrams/design.md 的生成器 ——
  只读区(FRONT) / 检索结果(MIDDLE) / 当前问题(BACK), 配 ContextBudget 限 token.
- 组装出来的就是**一份 skill 文本**, 直接当主 agent 的 system prompt (跟 main.py 同一个形态).
- 左链两个落点: "递交执行" = exec_agent.run_task; "入二层库" = 产出落进 skill/rag/corpus/ 再 embed.

跑法:  .venv/bin/python sub_agent.py
前提:  向量服务起着, rag 索引已建
配置:  config/sub_agent.json
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from dotenv import load_dotenv
from openai import AuthenticationError, OpenAI

import native_marks
import tokenizer

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config" / "sub_agent.json"
ROUTING_PATH = HERE / "config" / "think_routing.json"
AGENT_CONFIG_PATH = HERE / "config" / "agent.json"
# 主 agent 每轮留下的活动痕迹 —— 清洗管线的看守以其作为触发依据
ACTIVITY_PATH = HERE / "state" / "activity.json"

# 执行产出落在这里, 再由 embed 嵌入二层热库 (用过的即被记住, 下次同类问题能被检索到)
TIER2_CORPUS = HERE / "skill" / "rag" / "corpus"

load_dotenv(HERE / ".env")

# ★ .env.example 里那几个占位串（"在这里填"）不是配置 —— 灌进环境后统一清成空。
#   不清的后果（2026-10-12 实测）：设置页以它拼接 https://.../models 会直接抛
#   `unknown url type: '%E5%9C%A8%E8%BF%99%E9%87%8C%E5%A1%AB/models'`，
#   整份 `/api/设置` 读不出来 ⇒ **接口页与开关页一起空白**。
占位串 = {"在这里填", "填这里", "todo", "TODO", "sk-xxx", "你的key"}
端点键 = (
    "OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_API_KEY",
    "EMBEDDING_BASE_URL", "EMBEDDING_MODEL", "EMBEDDING_API_KEY",
    "EXEC_BASE_URL", "EXEC_MODEL", "EXEC_API_KEY",
    "SUBAGENT_BASE_URL", "SUBAGENT_MODEL", "SUBAGENT_API_KEY",
)
for _键 in 端点键:
    _值 = os.environ.get(_键)
    if _值 is not None and _值.strip().strip("\"'") in 占位串:
        os.environ[_键] = ""


# 过程回显的回调: (事件, 内容)。子 agent 这边只有两类 ——
#   think 它正在想(增量)   reply 它正在说(增量)
# 不接就安安静静(当库用时干净), 接上就能看见"分析/判断"两步在干什么。
ProgressFn = Callable[[str, str], None]


def load_agent_config() -> dict[str, Any]:
    """读三个 agent 共用的配置 (config/agent.json).

    ★ 配置一律放 json, 不硬编码在代码里: 默认 skill 路径 / 执行超时与来回上限 /
      命令黑名单 / 界面文字, 都从这儿来。
    """
    if not AGENT_CONFIG_PATH.is_file():
        raise FileNotFoundError(f"配置不存在: {AGENT_CONFIG_PATH}")
    agent_config: dict[str, Any] = json.loads(AGENT_CONFIG_PATH.read_text(encoding="utf-8"))
    if not agent_config:
        raise ValueError(f"配置是空的: {AGENT_CONFIG_PATH}")
    return agent_config


# 以下常量都取自 config/agent.json
DEGRADE_CHARS = int(load_agent_config()["misc"]["degrade_chars"])
DEFAULT_SKILL = str(load_agent_config()["default_skill"])
def note_activity(ended: bool | None, question: str) -> None:
    """主 agent 每轮留个痕: 这轮任务结束了没有 (seek skill 的 `任务结束` 键)。

    清洗管线的看守以其作为触发器 —— "任务结束 = true 且静默足够久" 才去清二层、落三层。

    写两次:
      · 收到提问时写 false —— 有人来了, 计时按住(否则上一轮答完快满 20 分钟时,
        用户刚提问、模型还在想, 看守会趁这个缝把二层清掉)
      · 答完再写模型给的那个 —— true 才算这轮真的收工

    ended 为 None 表示模型这轮没给这个键: **不覆盖**上一次的判断(宁可不写),
    猜错成 true 会让后台提前动手。
    """
    if ended is None:
        return
    ACTIVITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACTIVITY_PATH.write_text(
        json.dumps(
            {
                "任务结束": ended,
                "时间": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "问题": question,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

PROBE_TIMEOUT = float(load_agent_config()["misc"]["probe_timeout_seconds"])
WINDOW_TIMEOUT = float(load_agent_config()["misc"]["window_timeout_seconds"])


def python_bin() -> str:
    """优先用项目 venv 的解释器, 没有就用当前解释器."""
    candidate = HERE / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def load_config() -> dict[str, Any]:
    """读配置 JSON."""
    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(f"配置不存在: {CONFIG_PATH}")
    text = CONFIG_PATH.read_text(encoding="utf-8")
    config: dict[str, Any] = json.loads(text)
    if not config:
        raise ValueError(f"配置是空的: {CONFIG_PATH}")
    return config


def build_client() -> tuple[OpenAI, str]:
    """按 .env 建客户端, 返回 (客户端, 模型名).

    优先 SUBAGENT_* —— 子agent(分析/判断) 与 主agent(回答) 共用这一台;
    没配才回落到 OPENAI_*(本机 llama-server, 免费但慢)。
    exec agent 有自己的 EXEC_*(见 exec_agent.py)。
    """
    api_key = os.getenv("SUBAGENT_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("SUBAGENT_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model = os.getenv("SUBAGENT_MODEL") or os.getenv("OPENAI_MODEL") or "qwen3-vl-8b"
    client = OpenAI(api_key=api_key, base_url=base_url)
    return client, model


def load_routing() -> dict[str, Any]:
    """读思考路由配置 (config/think_routing.json) —— 外部可调, 源码不硬编码。"""
    if not ROUTING_PATH.is_file():
        raise FileNotFoundError(f"配置不存在: {ROUTING_PATH}")
    text = ROUTING_PATH.read_text(encoding="utf-8")
    routing: dict[str, Any] = json.loads(text)
    if not routing:
        raise ValueError(f"配置是空的: {ROUTING_PATH}")
    return routing


def decide_by_keywords(
    question: str, routing: dict[str, Any]
) -> tuple[bool | None, str]:
    """关键词硬规则: 命中即定, 不花模型调用。没命中返回 (None, "")。"""
    rows = routing.get("关键词规则")
    if not isinstance(rows, list):
        return None, ""
    for row in cast(list[object], rows):
        if not isinstance(row, dict):
            continue
        table = cast(dict[str, Any], row)
        words = table.get("词")
        if not isinstance(words, list):
            continue
        for word in cast(list[object], words):
            text = str(word).strip()
            if text and text in question:
                kind = str(table.get("类型") or "")
                return bool(table.get("开关")), f"规则命中「{kind}」← {text}"
    return None, ""


def decide_think(
    question: str,
    model_think: bool | None,
    model_reason: str,
    routing: dict[str, Any],
) -> dict[str, Any]:
    """三层判定主 agent 本轮是否启用长链路思考。

    ①关键词硬规则(配置里, 命中即定) -> ②模型(子 agent 分析步给的 think)
    -> ③都没结论就用 默认开关(保守=关)。

    ★ 返回 {"开关": bool, "来源": "规则"/"模型"/"默认", "理由": str}。
    模型这步坏掉(被截/没给字段)时**不许静默当结论** —— 走默认档并把来源标成
    "默认", 理由写清是模型没给结论, 日志可追溯。
    """
    hit, why = decide_by_keywords(question, routing)
    if hit is not None:
        # 规则是硬判, 但模型有相反意见时要留痕 —— 不然规则误判了看不出来
        if model_think is not None and bool(model_think) != hit:
            why += f"（模型持相反意见：{'开' if model_think else '关'}，按规则）"
        return {"开关": hit, "来源": "规则", "理由": why}
    if model_think is not None:
        return {"开关": bool(model_think), "来源": "模型", "理由": model_reason or "分析步判定"}
    default = bool(routing.get("默认开关", False))
    tail = "模型这步没给结论" if not model_reason else "规则与模型都没结论"
    return {
        "开关": default,
        "来源": "默认",
        "理由": f"{tail} → 按默认档({'开' if default else '关'})",
    }


def thinking_params(
    base_url: str, model: str, enabled: bool, routing: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    """按 provider 方言拼思考参数, 返回 (给 API 的 extra_body, 说明)。

    说明里写清"已开 / 已关 / 该家或该模型不支持" —— 不得把"已发送但静默无效"记为"已开思考"。
    """
    rows = routing.get("方言")
    dialect: dict[str, Any] | None = None
    if isinstance(rows, list):
        for row in cast(list[object], rows):
            if not isinstance(row, dict):
                continue
            table = cast(dict[str, Any], row)
            keys = table.get("匹配_base_url含")
            if not isinstance(keys, list):
                continue
            if any(str(key) in base_url for key in cast(list[object], keys)):
                dialect = table
                break
    if dialect is None:
        return {}, f"认不出 {base_url} 是哪家, 不发思考参数"

    name = str(dialect.get("名称") or "?")
    if not bool(dialect.get("支持", True)):
        return {}, f"{name} 不支持思考"
    blocked = dialect.get("不支持的模型名含")
    if isinstance(blocked, list) and any(
        str(item).lower() in model.lower() for item in cast(list[object], blocked)
    ):
        return {}, f"{model} 本身没有思考模式 (跳过)"

    body = dialect.get("开" if enabled else "关")
    params = cast(dict[str, Any], body) if isinstance(body, dict) else {}
    if not params:
        state = "默认就是开" if enabled else "不发参数即关"
        return {}, f"{name}：{state}"
    return params, f"{name} 已{'开' if enabled else '关'}思考"


def parse_json_object(raw: str) -> dict[str, Any]:
    """从模型返回中提取第一个 JSON 对象；提取不到则返回空 dict。"""
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return cast(dict[str, Any], payload)


def render_stream(stream_generator: Iterable[tuple[str, str]]) -> tuple[str, str]:
    """
    将思考和回答的增量文本直接写入终端，避免反复重绘完整内容。

    生成器每次 yield (类型, 文本片段)，类型为 reasoning 或 answer。
    为降低流式输出延迟，Markdown 标记会按原文输出，不在此处解析。
    """
    reasoning_text = ""
    answer_text = ""
    current_type = None

    for content_type, chunk in stream_generator:
        if content_type not in ("reasoning", "answer"):
            raise ValueError(f"未知的流内容类型：{content_type}")

        if content_type != current_type:
            if current_type is not None:
                sys.stdout.write("\033[0m\n")
            label = "思考过程" if content_type == "reasoning" else "回答"
            sys.stdout.write(f"\033[2m{label}：\033[0m")
            current_type = content_type

        if content_type == "reasoning":
            reasoning_text += chunk
            sys.stdout.write(f"\033[2m{chunk}\033[0m")
        else:
            answer_text += chunk
            sys.stdout.write(chunk)
        sys.stdout.flush()

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
        # 思考参数(按 provider 方言拼, 见 thinking_params) —— 空 = 这轮不开思考
        self.extra_body: dict[str, Any] = extra_body or {}

    @classmethod
    def from_env(
        cls,
        model: str | None = None,
        system_prompt_path: str = DEFAULT_SKILL,
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


# ============================================================
# 拼接标准（照 design.md 的生成器）
# ============================================================

class Permission(Enum):
    """权限分级: 决定这段内容以什么身份进上下文."""

    READONLY = "readonly"      # 只读: 核心指令 / 冻结 skill
    WRITABLE = "writable"      # 可写: 状态 / 时间线
    INJECTED = "injected"      # 程序注入: 检索结果 / skill 全文
    SELECTABLE = "selectable"  # 模型可选: 从候选里挑


class Position(Enum):
    """位置: 决定拼在上下文的哪一头."""

    FRONT = "front"    # 最前: 只读区, KV 命中率最高
    MIDDLE = "middle"  # 中间: 状态 / 检索结果
    BACK = "back"      # 最后: 当前问题 / 输出格式


@dataclass
class ContextBlock:
    """一个待拼装的上下文块."""

    content: str
    permission: Permission
    position: Position
    priority: int
    token_estimate: int
    source: str
    cacheable: bool = False


@dataclass
class ContextBudget:
    """上下文预算.

    定调: **一整个 skill 的预算 = 模型总上下文 × skill_ratio(40%)**;
    再扣掉"除记忆外的 token"(输出预留 + 只读区预留), 剩下的就是记忆能用的空间。
    """

    total: int
    output_reserve: int
    readonly_reserve: int
    available: int = 0

    def __post_init__(self) -> None:
        # 窗口较小时扣完会是负数 —— 兜到 0, 不让负数往下传
        self.available = max(0, self.total - self.output_reserve - self.readonly_reserve)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "ContextBudget":
        """按配置算: total = 模型总上下文 × skill_ratio."""
        window = int(config["context_window"])
        ratio = float(config["skill_ratio"])
        return cls(
            total=int(window * ratio),
            output_reserve=int(config["output_reserve"]),
            readonly_reserve=int(config["readonly_reserve"]),
        )


# 模型总上下文窗口: 每次向 API 实时询问, 取到即缓存 (进程内), 取不到才用配置兜底
_WINDOW_CACHE: dict[str, int] = {}

# 直连, 不走本机 http_proxy —— 否则访问 127.0.0.1 会被代理拦截
_WINDOW_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def dig_context_window(payload: object, model: str) -> int | None:
    """从各家 /models (或 /props) 的返回里把"总上下文窗口"挖出来.

    字段名各家不一样, 都认: max_model_len / context_length / loaded_context_length /
    max_context_length / n_ctx.
    """
    names = (
        "max_model_len",
        "context_length",
        "loaded_context_length",
        "max_context_length",
        "n_ctx",
    )

    if not isinstance(payload, dict):
        return None
    table = cast(dict[str, Any], payload)

    rows = table.get("data")
    if isinstance(rows, list):
        for row in cast(list[object], rows):
            if not isinstance(row, dict):
                continue
            record = cast(dict[str, Any], row)
            record_id = str(record.get("id", ""))
            # llama.cpp 那种单模型后端, id 就是模型文件路径 —— 只认最后一段
            shape = record_id.rsplit("/", 1)[-1]
            if record_id and model and model not in (record_id, shape) and not shape.startswith(model):
                continue
            for name in names:
                value = record.get(name)
                if isinstance(value, int) and value > 0:
                    return value

    # llama.cpp /props: default_generation_settings.n_ctx
    settings = table.get("default_generation_settings")
    if isinstance(settings, dict):
        value = cast(dict[str, Any], settings).get("n_ctx")
        if isinstance(value, int) and value > 0:
            return value

    for name in names:
        value = table.get(name)
        if isinstance(value, int) and value > 0:
            return value
    return None


def _get_json(url: str, timeout: float = PROBE_TIMEOUT, token: str = "") -> object | None:
    """直连要一段 JSON (不走本机 http_proxy); 要不到返回 None.

    带 token 就加 Authorization —— 云端端点不带头只会 401, 会被误判成"端点没起"。
    """
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with _WINDOW_OPENER.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _alive(url: str, timeout: float = PROBE_TIMEOUT) -> bool:
    """打一下看活没活 (只认状态码, 不看返回体)."""
    try:
        with _WINDOW_OPENER.open(url, timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def fetch_context_window(base_url: str, model: str, timeout: float = WINDOW_TIMEOUT) -> int | None:
    """向 API 现要模型的总上下文窗口.

    先问 OpenAI 兼容的 /models, 再问 llama.cpp 的 /props; 都问不到返回 None.
    同一个 (端点, 模型) 只问一次, 记在进程内。
    """
    key = f"{base_url.rstrip('/')}|{model}"
    if key in _WINDOW_CACHE:
        return _WINDOW_CACHE[key]

    root = base_url.rstrip("/")
    home = root[:-3] if root.endswith("/v1") else root
    token = os.getenv("OPENAI_API_KEY") or ""
    for url in (f"{root}/models", f"{home}/props"):
        payload = _get_json(url, timeout, token)
        if payload is None:
            continue
        window = dig_context_window(payload, model)
        if window is not None:
            _WINDOW_CACHE[key] = window
            return window
    return None


def current_context_window() -> int | None:
    """按 .env 里的模型现问一次总上下文窗口; 问不到返回 None (调用方用配置兜底)."""
    try:
        client, model = build_client()
    except Exception:  # .env 缺凭据之类 —— 问不成就不问, 让配置兜底
        return None
    return fetch_context_window(str(client.base_url), model)


def check_endpoint(client: OpenAI, model: str = "") -> tuple[bool, str]:
    """开工前探模型端点: 通不通、要的那个模型在不在.

    返回 (能不能开工, 要提醒的话) —— **一切正常时第二项是空串**(不打扰);
    名字不符但后端不校验(本地 llama.cpp 那类)时放行 + 提醒; 连不上 / 鉴权未通过才拦截。
    先探这一步的目的就是不让调用方抛出一堆 traceback。
    """
    root = str(client.base_url).rstrip("/")
    home = root[:-3] if root.endswith("/v1") else root

    names: list[str] = []
    try:
        names = [str(item.id) for item in client.with_options(timeout=PROBE_TIMEOUT).models.list().data]
    except AuthenticationError:
        return False, f"{root} 的 key 没过（401）—— 看 .env 的 OPENAI_API_KEY"
    except Exception:  # 连不上 / 不认这个接口 —— 退一步只判"活没活"
        pass

    if not names:
        for url in (f"{home}/health", f"{home}/props", root):
            if _alive(url):
                return True, ""
        return False, f"连不上 {root}"

    # llama.cpp 的 /v1/models 报的是模型文件全路径 —— 比对和显示都只取最后一段
    shapes = [name.rsplit("/", 1)[-1] for name in names]
    if model and model not in names and model not in shapes:
        shown = "、".join(name[:40] for name in shapes[:5])
        if "127.0.0.1" in root or "localhost" in root:
            # 本地后端(llama.cpp 那种压根不校验模型名) —— 提醒一句就放行
            return True, f"注意：{root} 的模型列表里没有 {model}（它有的是：{shown}）"
        return False, f"{root} 上没有模型 {model}（它有的是：{shown}）"
    return True, ""


def estimate_tokens(text: str) -> int:
    """数 token 占用.

    有本地词表(tokenizer.py + config/tokenizer.json)就精确实数; 没词表才退回
    "一字符一 token" 的保守粗估 —— 中文粗估还算接近, 英文会高估到 4 倍左右。
    """
    精确 = tokenizer.count(text)
    if 精确 is not None:
        return max(1, 精确)
    return max(1, len(text))


def make_block(
    content: str,
    permission: Permission,
    position: Position,
    priority: int,
    source: str,
    cacheable: bool = False,
) -> ContextBlock:
    """造一个块, token 占用自动估."""
    return ContextBlock(
        content=content,
        permission=permission,
        position=position,
        priority=priority,
        token_estimate=estimate_tokens(content),
        source=source,
        cacheable=cacheable,
    )


def degrade(block: ContextBlock, budget: ContextBudget, used: int) -> ContextBlock | None:
    """放不下时的降级: 只留开头一段; 还放不下就放弃."""
    short = block.content[:DEGRADE_CHARS].strip()
    if not short:
        return None
    candidate = make_block(
        f"{short}\n...(截断)",
        block.permission,
        block.position,
        block.priority - 1,
        f"{block.source}#降级",
    )
    if used + candidate.token_estimate <= budget.available:
        return candidate
    return None


def assemble(blocks: list[ContextBlock], budget: ContextBudget) -> tuple[str, list[str]]:
    """按 position 分组 -> 中间区按 priority 分配预算 -> 拼起来.

    只读区(FRONT) 直接放最前; 中间区放不下先降级再丢.
    返回 (拼好的文本, 降级/丢弃的说明).
    """
    front = [block for block in blocks if block.position is Position.FRONT]
    middle = [block for block in blocks if block.position is Position.MIDDLE]
    back = [block for block in blocks if block.position is Position.BACK]

    notes: list[str] = []
    chosen: list[ContextBlock] = []
    used = 0

    for block in sorted(middle, key=lambda item: -item.priority):
        if used + block.token_estimate <= budget.available:
            chosen.append(block)
            used += block.token_estimate
            continue
        fallback = degrade(block, budget, used)
        if fallback is not None:
            chosen.append(fallback)
            used += fallback.token_estimate
            notes.append(
                f"降级 {block.source} ({block.token_estimate} -> {fallback.token_estimate})"
            )
        else:
            notes.append(f"放不下丢掉 {block.source} ({block.token_estimate})")

    parts: list[str] = []
    for group in (front, chosen, back):
        for block in group:
            parts.append(block.content)
    return "\n\n".join(parts), notes


# ============================================================
# 子 agent 的各个步骤
# ============================================================

def load_prompt(name: str, config: dict[str, Any] | None = None) -> str:
    """读一份提示词 —— 不硬编码在代码里, 从配置指向的文件读取。

    名字对的是 config/sub_agent.json 的 prompts 段; 文件是 skill 形态
    (frontmatter + 正文), 整份交给模型.
    """
    resolved = config if config is not None else load_config()
    prompts = resolved.get("prompts")
    if not isinstance(prompts, dict):
        raise KeyError("config/sub_agent.json 里没有 prompts 段")
    table = cast(dict[str, Any], prompts)
    entry = table.get(name)
    if not entry:
        raise KeyError(f"prompts 段里没有 {name}")
    return (HERE / str(entry)).read_text(encoding="utf-8")


def short_call(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int,
    on_event: ProgressFn | None = None,
) -> str:
    """分析/判断这类短调用: 流式拿回来, 顺带把它的输出实时报出去。

    ★ 必须给 max_tokens: 这两步要的只是一小段 JSON, 但**本地模型无边界的复读**
    能一路吐好几分钟 —— 而这两步原本既不流式、也没上界, 表现就是终端卡在
    "正在初始化…"一动不动(实测撞过 7 分钟)。流式 + 上界之后, 至少看得见、等得住。
    """
    stream = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        stream=True,
        max_tokens=max_tokens,
    )
    parts: list[str] = []
    finish: str = ""
    for chunk in stream:
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        if choice.finish_reason:
            finish = str(choice.finish_reason)
        delta = choice.delta
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning and on_event is not None:
            on_event("think", str(reasoning))
        text = delta.content
        if text:
            parts.append(text)
            if on_event is not None:
                on_event("reply", text)
    if finish == "length" and on_event is not None:
        # 不让它悄悄"判错": 被上界截了就直说 —— 这步的结论多半不作数
        on_event("note", f"这步的输出被 max_tokens={max_tokens} 截了 —— 下面的结论可能不准")
    return "".join(parts)


def plan_queries(
    client: OpenAI,
    model: str,
    question: str,
    max_queries: int,
    max_tokens: int = 400,
    on_event: ProgressFn | None = None,
    上文: str = "",
) -> dict[str, Any]:
    """分析: 要回答这个问题该去记忆库查哪些内容 + 本轮主 agent 是否启用长链路思考。

    `上文` = history_briefing() 拼的那块"最近几轮" —— 有了它, "那两个也处理了"这类
    接着上文说的追问才不是没头没尾的一句。

    返回 {"queries": [...], "think": bool | None, "reason": str}。
    think 为 None = 模型这步没给出结论(被截/没这个字段) -> 交给 decide_think 按默认档兜。
    """
    prompt = load_prompt("analyze").replace("{max_queries}", str(max_queries))
    raw = short_call(client, model, prompt, 上文 + question, max_tokens, on_event)
    payload = parse_json_object(raw)

    raw_queries = payload.get("queries")
    queries: list[str] = []
    if isinstance(raw_queries, list):
        items = cast(list[object], raw_queries)
        queries = [str(item).strip() for item in items if str(item).strip()][:max_queries]

    raw_think = payload.get("think")
    think = raw_think if isinstance(raw_think, bool) else None
    return {
        "queries": queries,
        "think": think,
        "reason": str(payload.get("reason") or "").strip(),
    }


def judge_skill(
    client: OpenAI,
    model: str,
    question: str,
    config: dict[str, Any],
    max_tokens: int = 200,
    on_event: ProgressFn | None = None,
    上文: str = "",
) -> dict[str, Any]:
    """判断(流程图上"判断"节点): 本轮是否需要一项手头没有的 skill。

    `上文` = history_briefing() 拼的那块"最近几轮" —— 判断的**对象**永远是【这一轮】那句,
    上文只是让它认出"它/那个/继续"指的是什么。

    返回 {"need": bool, "wanted": 缺的能力, "broken": 这步的结论可不可信}.
    need 为真 -> 走左链 (检索skill -> 返回skill需要列表 -> 交回主 agent, 落点在 main.py)。
    ★ broken 为真 = 模型没给出能用的结论(输出被截 / 解析失败 / 说了要却没说是什么)。
    这时**不能当"不需要"** —— 那会直接回落自己答, 遇到机器/文件类问题必然答不出来
    (实测: 「数 vllm 下 .py/.cu 个数 + 查 8790 端口进程」被截 -> 回落到 seek -> 答"我没有工具")。
    开关 skill_retrieval.enabled 关着就直接当"不需要", 不走左链.
    """
    if not bool(config.get("enabled")):
        return {"need": False, "wanted": "", "broken": False}

    # ★ 出口形态(2026-10-13 老板方案, 已实测): "json" = 要求模型直接吐结论(现状, 实测 100%);
    #   "读回" = **提示词不再要求 JSON**(换 judge_freeform), 让模型把判断说出来,
    #   再由读回件(config/skills/readback.md)读成结论 —— 上游不必背格式,
    #   "模型不吐我们要求的键"那类故障由读回件兜底(实测 96%, 且"读不出"从 2 条降到 0 条)。
    #   ★ 切换只改 config 的 skill_retrieval.judge_输出, 两个模式都留着。
    读回 = str(config.get("judge_输出") or "json") == "读回"
    读回上限 = int(config.get("读回上限") or 200)
    prompt = load_prompt("judge_freeform" if 读回 else "judge")
    问句 = 上文 + question

    def 跑一发() -> dict[str, Any]:
        原文 = short_call(client, model, prompt, 问句, max_tokens, on_event)
        if not 读回:
            return parse_json_object(原文)
        if not 原文.strip():
            return {}  # 上游一个字没吐 —— 当"没结论", 让它走重试/兜底那条老路
        return parse_json_object(
            short_call(client, model, load_prompt("readback"), 原文, 读回上限, on_event)
        )

    payload = 跑一发()
    if "need" not in payload:
        # 输出被截 / 解析不出 —— 先重试一次, 不急于判为"不需要"
        if on_event is not None:
            on_event("note", "判断这步的输出没解析出来（被截 / 解析失败）→ 重试一次")
        payload = 跑一发()
    if "need" not in payload:
        # 两次都无结论: 如实标 broken, 由主流程以用户原话兜底(不判为"不需要")
        return {"need": False, "wanted": "", "broken": True}
    need = bool(payload.get("need"))
    wanted = str(payload.get("wanted") or "").strip()
    if need and not wanted:
        # 说要, 但没说要什么 —— 也算没结论, 交给程序兜
        return {"need": True, "wanted": "", "broken": True}
    return {"need": need, "wanted": wanted if need else "", "broken": False}


def recent_turns_text(历史: list[dict[str, str]] | None, 上限: int = 4) -> str:
    """把最近几轮问答拼成"问: … / 答: …"的原文块(给 pick 解析指代、给 exec 当材料)。"""
    if not 历史:
        return ""
    return "\n\n".join(
        f"问: {row.get('问', '')}\n答: {row.get('答', '')}" for row in 历史[-上限:]
    ).strip()


# 上文块的标签: 子 agent 的分析/判断两步只看得到 user 那一句。加标签是因为
# "已经发生过的"和"这一轮要办的"必须分清楚, 否则模型会把上一轮的答案当成这一轮的事。
上文头 = (
    "【上文 · 刚刚发生过的对话】下面这些是**已经发生过**的, 只用来认指代"
    "(它/那个/继续/刚才的数…), 不是这一轮要办的事。"
)
上文尾 = "【这一轮】要分析/判断的就是下面这句:"


def history_briefing(
    历史: list[dict[str, str]] | None,
    轮数: int = 1,
    答上限: int = 400,
) -> str:
    """给子 agent 的两步(分析/判断)拼的"上文"块 —— 不加这块, 追问题在它们眼里没头没尾。

    ★ 为什么非有不可(2026-10-09 老板: "子agent给主agent拼记忆得加上上一次对话的输出,
      让子 agent 去识别, 否则容易断档"): recent_turn_hits 只喂给了**主 agent**(和 exec)
      当材料, 子 agent 自己那两步却只拿到**这一句** ——
      "那两个也处理了"在分析步眼里规划不出像样的检索问句(只能拿"那两个"去查),
      在判断步眼里也可能判成"不需要 skill"。补上"最近这一轮的问+答原文", 它才认得出指代。
    ★ 只给最近 1~2 轮、并把答案截断: 这两步是短调用(默认本地小模型),
      塞太长注意力会散, 走云上也白花钱。
    """
    if not 历史 or 轮数 <= 0:
        return ""
    行们: list[str] = []
    for row in 历史[-轮数:]:
        问 = str(row.get("问", "")).strip()
        答 = str(row.get("答", "")).strip()
        if 答上限 > 0 and len(答) > 答上限:
            答 = 答[:答上限] + "…(截断)"
        if not 问 and not 答:
            continue
        行们.append(f"问: {问}\n答: {答}")
    if not 行们:
        return ""
    return f"{上文头}\n\n" + "\n\n".join(行们) + f"\n\n{上文尾}\n"


def recent_turn_hits(
    历史: list[dict[str, str]] | None,
    上限: int = 4,
) -> list[dict[str, Any]]:
    """把本次会话最近几轮的问答原文做成一条"记忆" —— 直接进上下文, 不靠检索。

    ★ 指代性追问("刚才算的那个数再乘 2" 型)拿"刚才算的那个数"去做向量检索是召不回来的
    (实测: 那片原文就在索引里, 分数却排不进 top_k) —— 多轮指代靠的是"最近说过什么",
    只有把原文摆到眼前才稳。
    """
    if not 历史:
        return []
    正文 = recent_turns_text(历史, 上限)
    if not 正文:
        return []
    return [
        {
            "query": "本次对话(最近几轮)",
            "score": 1.0,
            "source": "本次对话(最近几轮, 原文)",
            "text": 正文,
        }
    ]


_检索告警: list[str] = []


def 清检索告警() -> None:
    """每轮开工前清空(告警按轮计, 不得把上一轮的带入)。"""
    _检索告警.clear()


def 记检索告警(说明: str) -> None:
    说明 = 说明.strip()
    if 说明 and 说明 not in _检索告警:
        _检索告警.append(说明)


def 取检索告警() -> list[str]:
    return list(_检索告警)


def 检索告警块() -> str:
    """检索这条路上出过状况时给主 agent 的硬话。

    ★ 2026-10-11 实测的坑: 嵌入服务被 OOM 杀了, 检索整条 0 命中, 主 agent 于是答
      "我没有之前对话的记忆——每次对话对我来说都是全新的"。把**环境故障**说成了
      **能力缺失**, 用户以为这机器不记事, 实际是服务没起。空 != 没事发生。
    """
    告警 = 取检索告警()
    if not 告警:
        return ""
    行 = "\n".join(f"- {x}" for x in 告警)
    return (
        "\n\n## ⚠ 这轮检索的实况(必须照实说)\n"
        f"{行}\n"
        "上面这些是**服务/环境的毛病**, 不是\"你没有记忆\"。所以:\n"
        "- 不许说\"我没有之前的记忆\"\"每次对话对我来说都是全新的\"这类话 —— 那是错的。\n"
        "- 要说清实况: 检索(向量/嵌入)服务这轮没接上, 所以没查回东西; 请把它起起来再问一次。\n"
        "- 也不许拿这句话当借口编造之前聊过什么。\n"
    )


def recall_memory(queries: list[str], rag: dict[str, Any]) -> list[dict[str, Any]]:
    """检索需要的记忆: 调 rag 的 recall, 拿回原文片段 (不带向量)."""
    entry = HERE / str(rag["entry"])
    if not entry.is_file():
        print(f"[记忆] rag 入口不在: {entry}")
        return []

    collected: list[dict[str, Any]] = []
    for query in queries:
        completed = subprocess.run(
            # ★ 不传 --tier: 让 recall 按默认顺序走"二层命中就回, 不命中落三层"。
            #   以前这里锁死 --tier 2, 而清洗又把对话产出都搬去了三层 ——
            #   于是"刚聊过的事"永远召不回来(2026-10-07 实测复现)。
            [
                python_bin(), str(entry), "recall", query,
                "-n", str(rag["top_k"]), "--json",
            ],
            capture_output=True, text=True, cwd=str(HERE), check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout).strip().replace("\n", " ")
            print(f"[记忆] 检索失败 ({query}): {message[:120]}")
            记检索告警(f"检索这条命令没跑成({query}): {message[:120]}")
            continue

        payload = parse_json_object(completed.stdout)
        说明清单 = payload.get("notes")
        for 说明 in [payload.get("note")] + (说明清单 if isinstance(说明清单, list) else []):
            if isinstance(说明, str):
                记检索告警(说明)
        raw_rows = payload.get("results")
        if not isinstance(raw_rows, list):
            continue
        for row in cast(list[object], raw_rows):
            if not isinstance(row, dict):
                continue
            record = cast(dict[str, Any], row)
            collected.append({
                "query": query,
                "score": record.get("score"),
                "source": record.get("source", ""),
                "text": str(record.get("text", "")),
            })

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for hit in collected:
        key = hit["text"][:120]
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def 关掉的技能() -> set[str]:
    """config/sub_agent.json 的 `skills` 段里被关掉的那些(值为 false).

    ★ 保守方向: 段不存在 / 读不出来 / 不是字典 → 返回空集合 = 全开.
      绝不能因为配置缺一段就把所有 skill 关掉 —— 那等于把 agent 变哑,
      比漏关一个严重得多.
    """
    try:
        skills = load_config().get("skills")
    except Exception:  # noqa: BLE001 - 配置读不出来时按"全开"走
        return set()
    if not isinstance(skills, dict):
        return set()
    return {str(k) for k, v in cast(dict[str, Any], skills).items() if v is False}


def search_skills(wanted: str, skill_search: dict[str, Any]) -> list[dict[str, Any]]:
    """检索skill(图上"检索skill"节点): 拿"缺什么能力"去 skill_search 找候选.

    返回 [{"name", "description", "source", "score"}].
    **source 就是那个 skill 的 SKILL.md 路径**, 可以直接喂给执行 agent 当提示词.

    ★ 设置页的开关就落在这儿: `config/sub_agent.json` 的 `skills` 段关掉谁,
      谁就不进候选(先剔再返回, 下游备料/执行都看不到它).
    """
    entry = HERE / str(skill_search["entry"])
    if not entry.is_file():
        print(f"[检索skill] 入口不在: {entry}")
        return []

    completed = subprocess.run(
        [python_bin(), str(entry), "find", wanted, "-n", str(skill_search["top_k"]), "--json"],
        capture_output=True, text=True, cwd=str(HERE), check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip().replace("\n", " ")
        print(f"[检索skill] 失败: {message[:120]}")
        return []

    payload = parse_json_object(completed.stdout)
    rows = payload.get("results")
    if not isinstance(rows, list):
        return []

    关掉 = 关掉的技能()
    candidates: list[dict[str, Any]] = []
    for row in cast(list[object], rows):
        if not isinstance(row, dict):
            continue
        record = cast(dict[str, Any], row)
        name = str(record.get("name", ""))
        if name in 关掉:
            print(f"[检索skill] {name} 已被开关关掉, 跳过")
            continue
        source = str(record.get("source", ""))
        candidates.append({
            "name": name,
            "description": str(record.get("description", "")),
            "source": source,
            "skill_file": resolve_skill_file(source),
            "score": record.get("score"),
        })
    return candidates


def resolve_skill_file(source: str) -> str:
    """候选给的 source 是 skill **目录**(如 skill/rag), 翻成里面的提示词文件.

    一律 SKILL.md; 同时识别小写的 Skill.md(早期遗留, 不让老目录失效)。
    翻不出来就把该目录下的 SKILL.md 报出去, 让报错指向真正缺的那个文件.
    """
    directory = Path(source.rstrip("/"))
    if not directory.is_absolute():
        directory = HERE / directory
    for name in ("SKILL.md", "Skill.md"):
        candidate = directory / name
        if candidate.is_file():
            return str(candidate)
    return str(directory / "SKILL.md")


def read_metadata(source: str) -> dict[str, Any]:
    """读 skill 目录里的 metadata.json —— 给**程序**读的那份（命令清单 / 检索约定）.

    没有、读不动、或不是对象，都返回空 dict：调用方按"这个 skill 没额外约定"处理。
    """
    directory = Path(source.rstrip("/"))
    if not directory.is_absolute():
        directory = HERE / directory
    path = directory / "metadata.json"
    if not path.is_file():
        return {}
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return cast(dict[str, Any], data) if isinstance(data, dict) else {}


#: ★ 命令库里的「本机易变快照」必须摘掉: 小模型会照备注念, 不看去新跑的实测输出。
#:   (2026-10-15 实测: df.md 备注写着 2026-10-06 的「根 36% / data 67%」, 模型答出
#:    「根剩 477G 69% / data 82G 67%」, 与本轮 df -h 真实输出 279G/58%、214G/11% 全不符。)
#:   只摘「易变状态」这类(磁盘/内存/负载/温度/核数/显存/百分比), 不碰用法示例 ——
#:   dig 里那种「实测 -> 8.136.202.225」是稳定示例, 摘了反而丢指导。
#: 判据用「数值形态」而不是汉语词: 早先按「剩/盘」这些词猜, 把 dig 里
#: 「能看出缓存还剩多久（实测 collaplex.me. 85 IN A 8.136.202.225）」这种**用法示例**也误伤了。
易变数值 = (
    re.compile(r"\d+(?:\.\d+)?\s*%"),                                   # 占用率
    re.compile(r"\d+(?:\.\d+)?\s*(?:Gi?B?|Mi?B?|Ti?B?|KB|MB|GB|TB)\b"),  # 容量/显存
    re.compile(r"\d+\s*(?:核|线程|路|个核心)"),                             # 核数
    re.compile(r"\d+(?:\.\d+)?\s*(?:度|℃|°C)"),                         # 温度
)
旧快照标记 = re.compile(r"（20\d\d-\d\d-\d\d ?实测）")                   # 明写日期的旧快照


def 摘掉易变快照(文本: str) -> tuple[str, list[str]]:
    """摘掉含易变状态的本机快照句(按句摘)。返回 (干净文本, 被摘的句子)。"""
    干净行: list[str] = []
    摘掉: list[str] = []
    for 行 in 文本.splitlines():
        留: list[str] = []
        for 句 in re.split(r"(?<=。)", 行):
            像快照 = "本机" in 句 or "实测" in 句 or bool(旧快照标记.search(句))
            if 像快照 and any(pat.search(句) for pat in 易变数值):
                摘掉.append(句.strip())
                continue
            留.append(句)
        干净行.append("".join(留))
    return "\n".join(干净行), 摘掉


def command_library_briefing(source: str, question: str) -> str:
    """带命令库的 skill：**由程序**先替 exec 查一次，把条目贴进任务里.

    为什么要程序来查：该查什么是确定的（就照这句话查），交给模型就成了"看它心情跳不跳步"。
    约定读 skill 的 metadata.json.briefing（哪条命令 / 取几条）；没这约定或查不动就返回空串，
    调用方照常递任务，不影响别的 skill。
    """
    metadata = read_metadata(source)
    briefing = metadata.get("briefing")
    commands = metadata.get("commands")
    if not isinstance(briefing, dict) or not isinstance(commands, list):
        return ""

    section = cast(dict[str, Any], briefing)
    name = str(section.get("command", "")).strip()
    top_k = int(section.get("top_k") or 3)
    known = any(
        isinstance(item, dict) and str(cast(dict[str, Any], item).get("name")) == name
        for item in cast(list[Any], commands)
    )
    if not name or not known:
        return ""

    directory = Path(source.rstrip("/"))
    if not directory.is_absolute():
        directory = HERE / directory
    entry = directory / str(metadata.get("entry") or "main.py")
    if not entry.is_file():
        return ""

    completed = subprocess.run(
        [python_bin(), str(entry), name, question, "-n", str(top_k)],
        capture_output=True, text=True, cwd=str(HERE), check=False,
    )
    body = completed.stdout.strip()
    if completed.returncode != 0 or not body:
        note = (completed.stderr or completed.stdout).strip().replace("\n", " ")
        print(f"[命令库] 预检索没成: {note[:120]}")
        return ""
    干净, 摘掉 = 摘掉易变快照(body)
    if 摘掉:
        print(f"[命令库] 摘掉 {len(摘掉)} 句本机易变快照(防照念旧数): {摘掉[0][:60]}")
    return (
        "\n\n## 命令库条目（程序已替你查好，照它写命令）\n"
        "★ 本机现状一律以**本轮命令的真实输出**为准：条目里原有的本机旧快照已由程序隐去，"
        "禁止引用任何没有出现在本轮命令输出里的数字；条目只用来决定「跑哪条、怎么跑」。\n\n"
        f"{干净}\n"
    )


def save_to_tier2(
    question: str,
    output: str,
    rag: dict[str, Any],
    declaration: str = "",
    output_files: list[str] | None = None,
    来源: str = "执行产出",
) -> str:
    """入二层库(图上"入二层库"节点): 产出落成语料文件, 再嵌进二层热库.

    存四样: 任务(用户原话) + 声明(主 agent 交办的活) + 产出(执行体的摘要)
    + 完整输出的路径 —— 完整输出本身在 logs/exec/, 只带路径, 不把整段输出灌进库.
    用过的即被记住 —— 下次同类问题可在二层检索到它。返回落盘路径。
    """
    TIER2_CORPUS.mkdir(parents=True, exist_ok=True)
    # ★ 落语料之前必过一道: 模型的原生工具调用标记(小米 MiMo 的 XML / DeepSeek 的 DSML)绝不能
    #   写入语料 —— 检索会把它取回上下文, 模型看见自己的标记就跟着模仿, 污染会自我扩散。
    #   2026-10-09 实测已踩坑: DeepSeek 一接手, 产出里就带着一串 DSML 闭合标记进了 corpus。
    question = native_marks.strip_all_calls(question)
    declaration = native_marks.strip_all_calls(declaration)
    output = native_marks.strip_all_calls(output)
    # 文件名按问题取哈希: 同一个问题重问 = 同一个 source = 覆盖, 不会反复灌爆二层库
    digest = hashlib.sha1(question.encode("utf-8")).hexdigest()[:8]
    # slug 只留 ASCII —— 文件名一律英文(中文问题就只剩哈希部分)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", question).strip("-").lower()[:24] or "q"
    path = TIER2_CORPUS / f"{slug}-{digest}.md"

    parts = [f"# 任务\n\n{question}\n"]
    if declaration.strip():
        parts.append(f"# 声明\n\n{declaration.strip()}\n")
    parts.append(f"# 产出\n\n{output}\n")
    if output_files:
        listing = "\n".join(f"- {item}" for item in output_files)
        parts.append(f"# 完整输出\n\n{listing}\n")
    parts.append(
        f"<!-- {来源}, {datetime.now().isoformat(timespec='seconds')} 入二层热库 -->\n"
    )
    path.write_text("\n".join(parts), encoding="utf-8")

    entry = HERE / str(rag["entry"])
    completed = subprocess.run(
        [python_bin(), str(entry), "embed", str(path), "--tier", "2"],
        capture_output=True, text=True, cwd=str(HERE), check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip().replace("\n", " ")
        print(f"[入二层库] 嵌入失败: {message[:160]}")
    return str(path)


def memory_briefing(hits: list[dict[str, Any]], 上限: int = 4000) -> str:
    """把召回的原文拼成一段材料 —— 左链(递给 exec)用。

    exec 经常要"接着上文算"(如"刚才那个数再乘 2"), 光有声明它不知道上文是什么。
    """
    if not hits:
        return ""
    # ★ 最近几轮的原文要**单独站出来**并写明"刚才=这里": 实测本地 8B 会把
    #   "刚才那个数"错认成检索回来的某条旧记录(挑了个含 1/3+1/6 的当答案)。
    近 = [h for h in hits if str(h.get("source", "")).startswith("本次对话")]
    远 = [h for h in hits if not str(h.get("source", "")).startswith("本次对话")]
    段: list[str] = []
    if 近:
        正文 = "\n\n".join(str(h.get("text", "")) for h in 近)
        段.append(
            "# 本次对话最近几轮(原文)\n\n"
            "★ 问题里说「刚才 / 上一条 / 那个数 / 它」时, **指的就是这里** —— 直接用它, 别猜。\n\n"
            + 正文
        )
    if 远:
        块 = [
            f"[记忆 {i + 1}] 出自 {h.get('source')}\n{h.get('text')}"
            for i, h in enumerate(远)
        ]
        段.append("# 检索到的旧资料(相关, 但不一定是「刚才」)\n\n" + "\n\n".join(块))
    全体 = "\n\n".join(段)
    if len(全体) > 上限:
        全体 = 全体[:上限] + "\n…(截断)"
    return "\n\n" + 全体 + "\n"


def load_main_skill(config: dict[str, Any]) -> str:
    """载入主 skill 系统提示词."""
    path = HERE / str(config["main_skill"])
    if not path.is_file():
        raise FileNotFoundError(f"主 skill 不在: {path}")
    return path.read_text(encoding="utf-8")


def build_skill_text(
    question: str,
    hits: list[dict[str, Any]],
    main_skill: str,
    budget_config: dict[str, Any],
) -> tuple[str, list[str], ContextBudget]:
    """按标准拼接 skill: 主 skill 提示词(只读, 最前) + 检索到的记忆(中间) + 当前问题(最后)."""
    # 总上下文现向 API 要; 要不到就用配置里的兜底数
    resolved = dict(budget_config)
    resolved["context_window"] = current_context_window() or int(
        resolved.get("fallback_context_window", 0)
    )
    # "除记忆外的 token" 现算: 主 skill(只读区) + 当前问题, 比配置里那个估的数准
    resolved["readonly_reserve"] = estimate_tokens(main_skill) + estimate_tokens(
        f"当前问题:\n{question}"
    )
    budget = ContextBudget.from_config(resolved)

    blocks: list[ContextBlock] = [
        make_block(
            main_skill,
            Permission.READONLY,
            Position.FRONT,
            100,
            "main_skill",
            cacheable=True,
        )
    ]

    for position, hit in enumerate(hits):
        blocks.append(make_block(
            f"[记忆 {position + 1}] 出自 {hit['source']}\n{hit['text']}",
            Permission.INJECTED,
            Position.MIDDLE,
            50 - position,
            f"memory:{hit['query']}",
        ))

    blocks.append(make_block(
        f"当前问题:\n{question}",
        Permission.SELECTABLE,
        Position.BACK,
        100,
        "question",
    ))

    text, notes = assemble(blocks, budget)
    return text, notes, budget


def prepare_skill(
    question: str,
    config: dict[str, Any] | None = None,
    on_event: ProgressFn | None = None,
    历史: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """问题 -> 分析 -> 判断 -> 检索记忆 -> 按标准拼成一份 skill 文本.

    这是供主 agent"拦截"用的一站式入口: 问题进来, 出去一份可直接充当
    system prompt 的 skill. 返回:
        {"skill": 文本, "skills": [这轮用到的 skill 文件],
         "queries": [检索问句], "hits": 取回条数, "notes": [拼接备注],
         "wanted": 缺的能力 (空 = 不需要, 主 agent 正常答),
         "think": 本轮是否启用长链路思考, "think_source": 判定来源(规则/模型/默认),
         "think_reason": 判定的理由 (给日志看)}

    `wanted` 非空 = 图上"判断"判出缺 skill —— 这时**不检索记忆**,
    `skill` 回主 skill 原文, 留给主 agent 放弃支链时回落自己答.
    """
    resolved = config if config is not None else load_config()
    client, model = build_client()
    main_skill = load_main_skill(resolved)
    # 分析 / 判断两步的输出上界 —— 本地模型复读时依赖它兜底(否则会一路输出数分钟)
    raw_limits = resolved.get("limits")
    limits: dict[str, Any] = (
        cast(dict[str, Any], raw_limits) if isinstance(raw_limits, dict) else {}
    )
    analyze_max = int(limits.get("analyze_max_tokens") or 400)
    judge_max = int(limits.get("judge_max_tokens") or 200)

    # ★ 子 agent 这两步也得看见"上一轮说了什么"(2026-10-09 老板: 不加容易断档)——
    #   "那两个也处理了 / 刚才那个数再乘 2"这类追问, 只拿到这一句时分析步规划不出问句、
    #   判断步可能判成"不需要 skill"。这块只喂分析/判断两步; 主 agent 与 exec 那边
    #   走的是 recent_turn_hits 的原文注入(各管一段, 不重复塞)。
    raw_hist_ctx = resolved.get("history_context")
    hist_ctx: dict[str, Any] = (
        cast(dict[str, Any], raw_hist_ctx) if isinstance(raw_hist_ctx, dict) else {}
    )
    上文 = ""
    if bool(hist_ctx.get("enabled", True)):
        上文 = history_briefing(
            历史,
            int(hist_ctx.get("turns") or 1),
            int(hist_ctx.get("answer_chars") or 400),
        )

    plan = plan_queries(
        client,
        model,
        question,
        int(resolved["analyze"]["max_queries"]),
        max_tokens=analyze_max,
        on_event=on_event,
        上文=上文,
    )
    queries = cast(list[str], plan["queries"])
    # ★ 每轮都要查一次记忆（2026-10-09 定）: 分析那步说"不用查"时, 以用户原话兜底查一遍。
    #   记忆是这一层的地基 —— 漏查的代价（答得像没见过、追问接不上）远大于多查一次（本地嵌入, 几乎无成本）。
    #   语义变化: 以前"不需要记忆"是**模型**的判决, 现在是程序的**默认动作**, 模型只能影响"拿什么去查"。
    清检索告警()  # 告警按轮算: 上一轮的检索毛病不许带进这一轮
    记忆兜底 = not queries
    if 记忆兜底:
        queries = [question]
    routing = load_routing()
    thinking = decide_think(
        question,
        cast(bool | None, plan["think"]),
        str(plan["reason"]),
        routing,
    )
    if on_event is not None:
        on_event(
            "note",
            f"思考判定：{'开' if thinking['开关'] else '关'}"
            f"（{thinking['来源']}：{thinking['理由']}）",
        )

    verdict = judge_skill(
        client,
        model,
        question,
        dict(resolved["skill_retrieval"]),
        max_tokens=judge_max,
        on_event=on_event,
        上文=上文,
    )
    if verdict["need"]:
        # 图上"判断 --no--> 检索skill": 手头缺这个能力, 走左链
        # ★ 缺 skill 也要检索记忆: "刚才算的那个数再乘 2" 这类追问**既缺 math 又缺上文** ——
        #   不检索的话 exec 拿到的是"算刚才那个数", 它不知道那数是多少, 只能臆测
        #   (2026-10-07 实测: 它连跑两条算不了的命令, 最后从命令库例子里抓了个 1/3+1/6 出来答)。
        hits = recent_turn_hits(历史) + recall_memory(queries, dict(resolved["rag"]))
        return {
            "skill": main_skill + 检索告警块(),
            "skills": [str(resolved["main_skill"])],
            "queries": queries,
        "记忆兜底": 记忆兜底,
            "hits": len(hits),
            "记忆": hits,
            "notes": 取检索告警(),
            "wanted": verdict["wanted"],
            "broken": bool(verdict["broken"]),
            "think": bool(thinking["开关"]),
            "think_source": str(thinking["来源"]),
            "think_reason": str(thinking["理由"]),
        }

    hits = recent_turn_hits(历史) + recall_memory(queries, dict(resolved["rag"]))
    skill_text, notes, budget = build_skill_text(
        question, hits, main_skill, dict(resolved["budget"])
    )
    return {
        "skill": skill_text + 检索告警块(),
        "skills": [str(resolved["main_skill"])],
        "queries": queries,
        "记忆兜底": 记忆兜底,
        "hits": len(hits),
        # ★ 自答这条也得把**召回的原文**交出去(2026-10-13 修): 以前只有走左链那条 return 带 "记忆",
        #   于是 ① 拦截简报读 `prepared["记忆"]` 恒得 0 —— 界面每轮都报"记忆 0 条", 而同一轮的 skill
        #   文本里明明塞着 [记忆 N] 块(老板看到的"又是老毛病: 它不记得"就是它);
        #   ② 判定那步坏掉、回落走左链时, main/bridge 也从这儿取记忆贴给 exec, 取不到就空贴。
        "记忆": hits,
        "notes": notes + 取检索告警(),
        "wanted": "",
        "broken": bool(verdict["broken"]),
        "memory_budget": budget.available,
        "think": bool(thinking["开关"]),
        "think_source": str(thinking["来源"]),
        "think_reason": str(thinking["理由"]),
    }


def run_once(
    client: OpenAI,
    model: str,
    config: dict[str, Any],
    main_skill: str,
    question: str,
) -> None:
    """走一遍: 分析 -> 判断 -> 检索 -> 拼接 -> 载入主skill提示词 -> 触发思考."""
    plan = plan_queries(
        client, model, question, int(config["analyze"]["max_queries"])
    )
    queries = cast(list[str], plan["queries"])
    print(f"[分析] 要查的记忆: {queries if queries else '不需要'}")
    thinking = decide_think(
        question,
        cast(bool | None, plan["think"]),
        str(plan["reason"]),
        load_routing(),
    )
    print(f"[思考] {'开' if thinking['开关'] else '关'}（{thinking['来源']}：{thinking['理由']}）")

    verdict = judge_skill(client, model, question, dict(config["skill_retrieval"]))
    if verdict["need"]:
        print(f"[判断] 手头缺一个 skill: {verdict['wanted']}")
        print("[判断] 左链靠主 agent 接 (main.py: 检索skill -> 判断 -> 递交执行 -> 入二层库)")
        print("[判断] 独立跑到这里先停; 完整形态跑 main.py")
        return

    hits = recall_memory(queries, dict(config["rag"]))
    print(f"[记忆] 取回 {len(hits)} 条" + (f" (最高 {hits[0]['score']})" if hits else ""))

    skill_text, notes, budget = build_skill_text(
        question, hits, main_skill, dict(config["budget"])
    )
    for note in notes:
        print(f"[拼接] {note}")
    print(f"[拼接] skill 文本 {len(skill_text)} 字符, 动态预算 {budget.available}")

    think_body, think_note = thinking_params(
        str(client.base_url), model, bool(thinking["开关"]), load_routing()
    )
    print(f"[思考参数] {think_note}")
    assistant = StreamingChatAssistant(client, model, skill_text, extra_body=think_body)
    _, _, stats = assistant.chat(question)

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


def main() -> None:
    """等待触发 -> 问题 -> 走一遍 -> 回"等待触发"."""
    config = load_config()
    client, model = build_client()
    main_skill = load_main_skill(config)

    print(f"子 agent 就绪   模型 {model}   主 skill {config['main_skill']}")
    print(f"记忆库 {config['rag']['entry']} (tier {config['rag']['tier']})   /exit 退出")

    while True:
        width = get_terminal_width()
        print("=" * width)
        try:
            question = input(">").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出")
            break
        if question in ("/exit", "/quit"):
            print("已退出")
            break
        if not question:
            continue
        print("-" * width)
        run_once(client, model, config, main_skill, question)


if __name__ == "__main__":
    main()

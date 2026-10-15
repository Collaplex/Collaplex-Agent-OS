#!/usr/bin/env python3
"""collaplex_agent 自检 —— 从图标到配置到模型端点, 一项一行.

跑法:
    ./selfcheck.py            # 就这一句 —— 全过了就直接进 main.py
    ./selfcheck.py --只查      # 只想看自检结果, 不进 main.py
    .venv/bin/python selfcheck.py

全过就**把进程换成 main.py**(execv, 不另起一层); 有报错就停在这儿。
从其他脚本调用时(stdin 不是终端)也只查不拉 —— 以免守门变成干扰。

输出五列: 时间 | 信息 | 等级 | 事件 | 结果
    时间 = 这一项什么时候查的
    信息 = 哪一块 (配置 / 模型 / 依赖 / 库 / 代码 / 结构)
    等级 = 信息 / 警告 / 错误
    事件 = 查的是什么 (带上是错的细节)
    结果 = 正确 / 报错

有报错时退出码 1, 全部正常时 0 —— 便于挂到别处当守门用。
"""

import ast
import json
import os
import py_compile
import shutil
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent

import path_locator as 件定位   # 常见于: 件可能以源码/字节码/编译件三种形态存在

for _p in (HERE, HERE / "skill" / "rag" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import store  # noqa: E402  (同项目模块, 得先补 sys.path)
import sub_agent  # noqa: E402  - 端点通不通只有一处判据: 它那个 check_endpoint

# 探测不走代理 —— 本机 Clash 会把 127.0.0.1 拦成 502
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 五列的表头
HEADER = ("时间", "信息", "等级", "事件", "结果")


@dataclass
class Item:
    """一行自检记录。"""

    when: str    # 时间: 这一项什么时候查的
    where: str   # 信息: 哪一块
    level: str   # 等级: 信息 / 警告 / 错误
    what: str    # 事件: 查的是什么
    result: str  # 结果: 正确 / 报错


def stamp() -> str:
    """这一项的时刻 (每项各记各的, 不是打印时统一取)。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def pass_it(items: list[Item], where: str, what: str) -> None:
    """记一条通过。"""
    items.append(Item(stamp(), where, "信息", what, "正确"))


def fail(items: list[Item], where: str, what: str, why: str) -> None:
    """记一条报错。"""
    items.append(Item(stamp(), where, "错误", f"{what} — {why}", "报错"))


def warn(items: list[Item], where: str, what: str, why: str) -> None:
    """记一条警告 (能用, 但不对劲)。"""
    items.append(Item(stamp(), where, "警告", f"{what} — {why}", "正确"))


def display_width(text: str) -> int:
    """算显示宽度 —— 中文字符占两格。"""
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def pad(text: str, width: int) -> str:
    """按显示宽度右侧补齐。"""
    return text + " " * max(0, width - display_width(text))


def python_bin() -> str:
    """项目 venv 的解释器, 没有就用当前这个。"""
    candidate = HERE / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def origin(base_url: str) -> str:
    """把 http://host:port/v1 削成 http://host:port —— 打 /health、/props 用。"""
    parts = urllib.parse.urlsplit(base_url)
    return f"{parts.scheme}://{parts.netloc}"


def get_json(url: str, headers: dict[str, str] | None = None, timeout: float = 5.0) -> object | None:
    """打一个 GET, 拿回 JSON; 出任何问题都返回 None。"""
    try:
        request = urllib.request.Request(url, headers=headers or {})
        with OPENER.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> object | None:
    """打一个 POST JSON, 拿回 JSON; 出任何问题都返回 None。"""
    body = json.dumps(payload).encode("utf-8")
    merged = {"Content-Type": "application/json", **(headers or {})}
    try:
        request = urllib.request.Request(url, data=body, headers=merged, method="POST")
        with OPENER.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


# ★ .env.example 里的占位串不是配置 —— 读 .env 时统一折成空值。
#   不折的话会拿着"在这里填"去发 HTTP / 建 client，报一串假错（2026-10-12 实测）。
占位串 = {"在这里填", "填这里", "todo", "TODO", "sk-xxx", "你的key"}


def read_env() -> dict[str, str]:
    """读 .env (不走 python-dotenv, 以免引入依赖)。"""
    env: dict[str, str] = {}
    path = HERE / ".env"
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        净 = value.strip().strip("\"'")
        env[key.strip()] = "" if 净 in 占位串 else 净
    return env


def check_config(items: list[Item]) -> dict[str, Any]:
    """查配置: agent / sub_agent / 思考路由 / 外援触发 四份 json + 提示词 + .env 的键。"""
    agent: dict[str, Any] = {}
    defaults: dict[str, Any] = {}

    path = HERE / "config" / "agent.json"
    try:
        loaded = cast(object, json.loads(path.read_text(encoding="utf-8")))
        if not isinstance(loaded, dict) or not loaded:
            raise ValueError("是空的")
        agent = cast(dict[str, Any], loaded)
        missing = [
            key
            for key in ("default_skill", "exec", "ui", "misc")
            if key not in agent
        ]
        if missing:
            fail(items, "配置", "config/agent.json 能读", f"缺 {', '.join(missing)}")
        else:
            pass_it(items, "配置", "config/agent.json 能读 且字段齐")
    except (OSError, ValueError) as error:
        fail(items, "配置", "config/agent.json 能读", str(error))

    path = HERE / "config" / "sub_agent.json"
    try:
        loaded = cast(object, json.loads(path.read_text(encoding="utf-8")))
        if not isinstance(loaded, dict) or not loaded:
            raise ValueError("是空的")
        defaults = cast(dict[str, Any], loaded)
        pass_it(items, "配置", "config/sub_agent.json 能读")
    except (OSError, ValueError) as error:
        fail(items, "配置", "config/sub_agent.json 能读", str(error))

    prompts = defaults.get("prompts")
    if isinstance(prompts, dict):
        wanted = cast(dict[str, str], prompts)
        gone = [name for name, entry in wanted.items() if 件定位.件路径(HERE, entry) is None]
        if gone:
            fail(items, "配置", f"{len(wanted)} 份提示词都在", f"少了 {', '.join(gone)}")
        else:
            pass_it(items, "配置", f"{len(wanted)} 份提示词都在")
    else:
        fail(items, "配置", "提示词登记在 config/sub_agent.json 的 prompts", "读不到 prompts")

    refine = agent.get("refine")
    if not isinstance(refine, dict):
        fail(items, "配置", "config/agent.json 的 refine 段", "没有这一段")
    else:
        block = cast(dict[str, Any], refine)
        prompts = block.get("prompts")
        idle = block.get("idle_seconds")
        hard = block.get("hard_idle_seconds")
        if not isinstance(prompts, dict) or not prompts or not idle or not hard:
            fail(items, "配置", "清洗管线的配置齐", "缺 idle_seconds / hard_idle_seconds / prompts")
        else:
            names = [str(v) for v in cast(dict[str, Any], prompts).values()]
            gone_names = [
                n for n in names if not (HERE / "config" / "skills" / f"{n}.md").is_file()
            ]
            if gone_names:
                fail(items, "配置", f"清洗提示词 {len(names)} 份都在", f"少了 {', '.join(gone_names)}")
            else:
                pass_it(items, "配置",
                        f"清洗提示词 {len(names)} 份都在, 静默 {idle} / 硬 {hard} 秒")

    # 后加的两份配置: 思考路由 (sub_agent 读, 缺了直接 FileNotFoundError) / 外援触发 (outsource_hook 读)
    broken: list[str] = []
    for name in ("think_routing.json", "outsource_trigger.json"):
        path = HERE / "config" / name
        try:
            loaded = cast(object, json.loads(path.read_text(encoding="utf-8")))
            if not isinstance(loaded, dict) or not loaded:
                broken.append(f"{name} 是空的")
        except (OSError, json.JSONDecodeError) as error:
            broken.append(f"{name}: {error}")
    if broken:
        fail(items, "配置", "思考路由 / 外援触发 两份配置能读", "; ".join(broken))
    else:
        pass_it(items, "配置", "思考路由 / 外援触发 两份配置能读")

    env = read_env()
    need = ("OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_API_KEY", "EMBEDDING_BASE_URL")
    gone = [key for key in need if not env.get(key)]
    if gone:
        # ★ 模型端点空着不是"配置坏了"：Windows 包自带空白库 + 本地向量，不接云端就不必填。
        #   空着只提示，不报错（2026-10-12 定）。
        warn(items, "配置", ".env 的键齐（模型端点可选）",
             f"少了 {', '.join(gone)} —— 不接云端就不用填，要用云模型时补齐")
    else:
        pass_it(items, "配置", ".env 的键齐")

    return {**agent, "_env": env, "_defaults": defaults}


# 要逐个 GET 一遍的模型 API 组: (显示名, base 键, key 键, model 键)
# 执行体 / 子 agent 没配就是回落主模型那一套(.env 里只写三行=全切云端, 删三行=全回归本机)
API_GROUPS: tuple[tuple[str, str, str, str], ...] = (
    ("主模型", "OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"),
    ("向量模型", "EMBEDDING_BASE_URL", "EMBEDDING_API_KEY", "EMBEDDING_MODEL"),
    ("执行体", "EXEC_BASE_URL", "EXEC_API_KEY", "EXEC_MODEL"),
    ("子 agent", "SUBAGENT_BASE_URL", "SUBAGENT_API_KEY", "SUBAGENT_MODEL"),
)


def http_reason(code: int) -> str:
    """把状态码说成人话 (模型 API 那几种最常见的)。"""
    if code == 401:
        return "Key 不对(401)"
    if code == 403:
        return "被拒(403) —— Key 或权限"
    if code == 404:
        return "没有 /models 这个端点(404)"
    if code >= 500:
        return f"服务端出错({code})"
    return f"HTTP {code}"


def api_get_models(base: str, key: str, timeout: float) -> tuple[int, list[str]]:
    """GET <base>/models 拿模型名清单, 返回 (状态码, 名字); 状态码 0 = 连不上。

    这条是**通用**活体检查 —— 云端 API 没有 llama.cpp 那种 /health, /models 才是
    OpenAI 兼容端点人人都有的一发 GET。
    """
    url = f"{base.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        request = urllib.request.Request(url, headers=headers)
        with OPENER.open(request, timeout=timeout) as response:
            code = response.status
            body = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        return error.code, []
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return 0, []

    names: list[str] = []
    if isinstance(body, dict):
        rows = cast(dict[str, Any], body).get("data")
        if isinstance(rows, list):
            for row in cast(list[Any], rows):
                if isinstance(row, dict):
                    name = str(cast(dict[str, Any], row).get("id", ""))
                    if name:
                        names.append(name)
    return code, names


def check_apis(items: list[Item], config: dict[str, Any]) -> None:
    """四组模型 API 各 GET 一次 /models: 通不通 / Key 对不对 / 名字在不在。"""
    env = cast(dict[str, str], config.get("_env", {}))
    probe = float(cast(dict[str, Any], config.get("misc", {})).get("probe_timeout_seconds", 3.0))
    for label, base_key, key_key, model_key in API_GROUPS:
        base = env.get(base_key, "").strip()
        if not base:
            if label in ("主模型", "向量模型"):
                continue  # 这两个没配, check_models 已经报过了, 别重复
            pass_it(items, "模型", f"{label} API 没配 —— 回落主模型(读 {base_key.split('_')[0]}_* 那一套)")
            continue
        key = env.get(key_key, "") or env.get("OPENAI_API_KEY", "")
        code, names = api_get_models(base, key, probe)
        target = f"{label} API GET {base}/models"
        if code == 0:
            fail(items, "模型", target, "连不上 —— 服务起了吗 / 地址对不对")
            continue
        if code != 200:
            fail(items, "模型", target, http_reason(code))
            continue
        pass_it(items, "模型", f"{target} 通 ({len(names)} 个模型)")

        model = env.get(model_key, "").strip()
        if model and names:
            shapes = [name.rsplit("/", 1)[-1] for name in names]
            # llama.cpp 报的是 GGUF 文件名, 我们配的是别名(如 qwen3-embedding-0.6b ↔ Qwen3-Embedding-0.6B-Q8_0.gguf)
            # —— 忽略大小写的包含关系即视为对得上, 不当作"名字错了"
            low = model.lower()
            if not any(low in shape.lower() or shape.lower() in low for shape in [*shapes, *names]):
                warn(items, "模型", f"{label}的模型名对得上 ({model})", f"它有的是: {', '.join(shapes[:3])}")


def check_models(items: list[Item], config: dict[str, Any]) -> None:
    """查两个模型端点: 通不通 / 上下文窗口 / 向量维度。"""
    env = cast(dict[str, str], config.get("_env", {}))
    probe = float(cast(dict[str, Any], config.get("misc", {})).get("probe_timeout_seconds", 3.0))
    base = env.get("OPENAI_BASE_URL", "")
    embed_base = env.get("EMBEDDING_BASE_URL", "")
    # ★ .env.example 里的占位串（"在这里填"）不是配置 —— 当空值处理，
    #   否则会拿着"在这里填"去真连、报"主模型端点 在这里填 通 连不上"（2026-10-12 实测）。
    占位 = {"在这里填", "填这里", "todo", "TODO", "sk-xxx"}
    if base.strip().strip("\"'") in 占位:
        base = ""
    if embed_base.strip().strip("\"'") in 占位:
        embed_base = ""

    # ★ 没有本地模型栈（vendor/llama.cpp 不在，比如 Windows 包）时，"模型端点没配"
    #   不是配置漏了，是这台机器本就不打算跑本地模型 —— 报成信息、不报错（2026-10-12 定）。
    有本地模型 = (HERE / "vendor" / "llama.cpp" / "build" / "bin" / "llama-server").is_file()
    if not base:
        if 有本地模型:
            fail(items, "模型", "主模型端点", "OPENAI_BASE_URL 没配 —— 照 .env.example 建一份 .env")
        else:
            pass_it(items, "模型", "主模型端点没配 —— 这台机器没有本地模型栈，跳过（要接云端 API 时填 .env）")
    else:
        # ★ 不要在这里自行探测 {base}/health 就作数: 本地 llama.cpp 有这个路径, 而云端
        #   OpenAI 兼容端点没有(拿 /health 去问是 404) —— 那样这条会永远红着,
        #   可端点其实好好的(.env 走的就是云)。判据只留一处: sub_agent.check_endpoint,
        #   网页顶部那盏"端点通"的灯用的也是它。
        model = ""   # 下面 except 分支不走 build_client, 先给个底
        try:
            client, model = sub_agent.build_client()
            通, 说明 = sub_agent.check_endpoint(client, model)
        except Exception as 错:  # noqa: BLE001  - 配不出来也算不通, 别把自检带崩
            通, 说明 = False, str(错)
        if 通:
            pass_it(items, "模型", f"主模型端点 {base} 通 ({model})")
        else:
            fail(items, "模型", f"主模型端点 {base} 通",
                 f"{说明} —— 本机的模型没起就跑 ./start_models.sh start")

    if not base and not 有本地模型:
        return  # 没端点也没本地栈，后面这些（窗口/向量）不用再查
    props = get_json(f"{origin(base)}/props", timeout=probe) if base else None
    window = None
    if isinstance(props, dict):
        settings = cast(dict[str, Any], props).get("default_generation_settings")
        if isinstance(settings, dict):
            window = cast(dict[str, Any], settings).get("n_ctx")
    if isinstance(window, int) and window > 0:
        pass_it(items, "模型", f"主模型上下文窗口 {window}")
    else:
        warn(items, "模型", "主模型上下文窗口", "端点没报 n_ctx")

    if not embed_base:
        if 有本地模型:
            fail(items, "模型", "向量端点", "EMBEDDING_BASE_URL 没配")
        else:
            pass_it(items, "模型", "向量端点没配 —— 同理跳过（这台机器没有本地模型栈）")
        return
    if get_json(f"{origin(embed_base)}/health", timeout=probe) is None:
        fail(items, "模型", f"向量端点 {embed_base} 通", "连不上 —— 起模型了吗 (./start_models.sh start)")
        return
    pass_it(items, "模型", f"向量端点 {embed_base} 通")

    answer = post_json(
        f"{embed_base.rstrip('/')}/embeddings",
        {"input": "自检", "model": "embedding"},
        timeout=30.0,
    )
    vector: object = None
    if isinstance(answer, dict):
        rows = cast(dict[str, Any], answer).get("data")
        if isinstance(rows, list) and rows:
            head = cast(list[Any], rows)[0]
            if isinstance(head, dict):
                vector = cast(dict[str, Any], head).get("embedding")
    if isinstance(vector, list) and vector:
        dim = len(cast(list[Any], vector))
        expected = index_dim()
        if expected is None or dim == expected:
            pass_it(items, "模型", f"向量维度 {dim} (跟二层库一致)")
        else:
            fail(items, "模型", f"向量维度跟二层库一致", f"端点给 {dim}, 库是 {expected}")
    else:
        fail(items, "模型", "向量能算出来", "端点没回 embedding")


def rag配置() -> dict[str, Any]:
    """读 rag 的 resources/embed.json(判断走 JSON 还是 PG)。"""
    path = HERE / "skill" / "rag" / "resources" / "embed.json"
    try:
        loaded = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}
    return cast(dict[str, Any], loaded) if isinstance(loaded, dict) else {}


def 读层(tier: str) -> list[dict[str, Any]] | None:
    """读某一层的条目: PG 后端查库, JSON 后端读文件. 读不到返回 None."""
    名字 = {"2": "vector-index.json", "3": "memory-index.json"}.get(tier, "")
    path = HERE / "skill" / "rag" / "scripts" / 名字
    配置 = rag配置()
    if store.is_pg(配置):
        try:
            with store.connect(配置) as conn:
                return store.load_existing(conn, 配置, tier)
        except Exception:
            return None
    if not path.is_file():
        return None
    try:
        loaded = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None
    if not isinstance(loaded, dict):
        return None
    rows = cast(dict[str, Any], loaded).get("items")
    return cast(list[dict[str, Any]], rows) if isinstance(rows, list) else None


def load_index() -> dict[str, Any] | None:
    """读二层热库 (PG 后端查库, JSON 后端读文件)。"""
    rows = 读层("2")
    if rows is None:
        return None
    return {"meta": {"count": len(rows)}, "items": rows}


def index_dim() -> int | None:
    """二层库里一条记录的向量维度。"""
    data = load_index()
    if data is None:
        return None
    rows = data.get("items")
    if not isinstance(rows, list) or not rows:
        return None
    head = cast(list[Any], rows)[0]
    if not isinstance(head, dict):
        return None
    vector = cast(dict[str, Any], head).get("vector")
    if isinstance(vector, list) and vector:
        return len(cast(list[Any], vector))
    return None


def check_store(items: list[Item]) -> None:
    """查二层热库 / 语料目录。"""
    data = load_index()
    if data is None:
        fail(items, "库", "二层热库 (vector-index.json) 能读", "文件不在或读不了")
    else:
        rows = data.get("items")
        count = len(cast(list[Any], rows)) if isinstance(rows, list) else 0
        if count:
            pass_it(items, "库", f"二层热库 {count} 条")
        else:
            # ★ 空白库是"自带空白表"的正常态，不是错 —— 用起来就有内容（2026-10-12）。
            warn(items, "库", "二层热库还是空的", "空表 —— 用起来（对话/检索）就有内容了")

    corpus = HERE / "skill" / "rag" / "corpus"
    if corpus.is_dir():
        files = len(list(corpus.glob("*.md")))
        pass_it(items, "库", f"语料目录在 ({files} 个文件待清洗)")
    else:
        fail(items, "库", "语料目录在 (skill/rag/corpus)", "不在")

    # 三层冷库 = 清洗的落地处 (PG 后端就在同一个库里, 换了个 tier)
    scripts = HERE / "skill" / "rag" / "scripts"
    rows3 = 读层("3")
    if rows3 is None:
        fail(items, "库", "三层冷库能读 (memory-index.json 或 PG tier=3)", "读不到")
    else:
        kinds = sorted({str(row.get("kind", "?")) for row in rows3})
        pass_it(items, "库", f"三层冷库 {len(rows3)} 条 (类型: {' / '.join(kinds) or '无'})")

    alias = scripts / "alias.json"
    if not alias.is_file():
        warn(items, "库", "别名表还没建", "跑一次 refine.py 就有了")
    else:
        try:
            pack_a = cast(object, json.loads(alias.read_text(encoding="utf-8")))
            rows_a: list[Any] = []
            if isinstance(pack_a, dict):
                got_a = cast(dict[str, Any], pack_a).get("items", [])
                if isinstance(got_a, list):
                    rows_a = cast(list[Any], got_a)
            pass_it(items, "库", f"别名表在 ({len(rows_a)} 行)")
        except (OSError, json.JSONDecodeError) as error:
            fail(items, "库", "别名表能读", str(error)[:50])


    # 清洗的心跳与待重洗账 —— 没活时日志不出声, 靠这两个看它在不在跑、有没有欠账
    state = HERE / "state"
    pending_path = state / "refine-待重洗.json"
    pending_count = 0
    if pending_path.is_file():
        try:
            raw_pending: Any = json.loads(pending_path.read_text(encoding="utf-8"))
            pending_count = (
                len(cast(dict[str, Any], raw_pending)) if isinstance(raw_pending, dict) else 0
            )
        except (OSError, json.JSONDecodeError):
            pending_count = 0
    heartbeat_path = state / "refine-心跳.json"
    if not heartbeat_path.is_file():
        warn(items, "库", "清洗心跳还没落过", "跑一次 refine.py 就有了")
    else:
        last = ""
        try:
            beat: Any = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            if isinstance(beat, dict):
                last = str(cast(dict[str, Any], beat).get("上次检查", ""))
        except (OSError, json.JSONDecodeError):
            last = ""
        if last:
            pass_it(items, "库", f"清洗心跳 {last} · 待重洗 {pending_count} 个")
        else:
            warn(items, "库", "清洗心跳读不出时间", heartbeat_path.name)


# 现在的入口与常驻件 —— 谁真能起来, 谁就得先能编译 (cli 是总入口, web 是另一条壳)
# ★ Windows 上子进程默认按本地码页(cp936)编/解 —— 带中文的 JSON 会解废
#   （实测：定时自检里 arm 回来的 刚响=None、表=['','']，2026-10-12）。
#   这里定死 UTF-8，子进程继承、自己读子进程输出也按 UTF-8。
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


ENTRY_FILES: tuple[str, ...] = (
    "main.py",
    "sub_agent.py",
    "exec_agent.py",
    "cli.py",
    "count_tokens.py",
    "watchdog.py",
    "outsource_hook.py",
    "skill/rag/scripts/refine.py",
    "parser/selftest.py",
    "web/server.py",
    "web/bridge.py",
    "web/start.py",
)


def check_code(items: list[Item]) -> None:
    """查现在这些入口能不能编译, 加上 skill 目录。"""
    broken: list[str] = []
    for name in ENTRY_FILES:
        path = 件定位.件路径(HERE, name)          # 源码 .py / 字节码 .pyc / 编译件 .so 三形态都认
        if path is None:
            broken.append(f"{name} 不在")
            continue
        if path.suffix == ".py":
            try:
                py_compile.compile(str(path), doraise=True, cfile=None)
            except py_compile.PyCompileError as error:
                broken.append(f"{name}: {str(error).splitlines()[-1][:60]}")
        elif path.suffix == ".pyc":
            # ★ 字节码包: 没有 .py 可编, 改核对魔数 —— 这份包是不是当前这个 Python 小版本编的
            import importlib.util

            if path.read_bytes()[:4] != importlib.util.MAGIC_NUMBER:
                broken.append(f"{name}: 字节码魔数对不上 (这份包是别的 Python 小版本编的)")
    if broken:
        fail(items, "代码", "入口都在", "; ".join(broken))
    else:
        pass_it(items, "代码",
                f"{len(ENTRY_FILES)} 个入口都在"
                " (main / sub_agent / exec_agent / cli / count_tokens / watchdog / outsource_hook / refine / parser 自测 / web)")

    wanted = ("seek", "rag", "skill_search", "linux", "file", "math", "outsource", "mtp", "ops", "search", "vision")
    gone = [name for name in wanted if not (HERE / "skill" / name).is_dir()]
    if gone:
        fail(items, "结构", "skill 目录齐", f"少了 {', '.join(gone)}")
    else:
        pass_it(items, "结构", f"skill 目录齐 ({' / '.join(wanted)})")

    config_skills = HERE / "config" / "skills"
    count = len(list(config_skills.glob("*.md"))) if config_skills.is_dir() else 0
    if count >= 4:
        pass_it(items, "结构", f"提示词目录 {count} 份")
    else:
        fail(items, "结构", "提示词目录 (config/skills)", f"只有 {count} 份, 该至少 4 份")


def norm_source(src: str) -> str:
    """索引里的 source 归一成"相对项目根"—— 有的写绝对路径, 有的写相对。"""
    text = src.strip().replace("\\", "/")
    path = Path(text)
    if path.is_absolute():
        try:
            return str(path.relative_to(HERE))
        except ValueError:
            return text
    return text


def index_sources(path: Path) -> set[str] | None:
    """读一个索引件的 source 集合; 读不动 / 没 source 返回 None。"""
    try:
        loaded = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    rows = cast(dict[str, Any], loaded).get("items")
    if isinstance(rows, dict):
        rows = list(cast(dict[str, Any], rows).values())
    if not isinstance(rows, list):
        return None
    out: set[str] = set()
    for row in cast(list[object], rows):
        if not isinstance(row, dict):
            continue
        src = cast(dict[str, Any], row).get("source")
        if isinstance(src, str) and src.strip():
            out.add(norm_source(src))
    return out


def check_indexes(items: list[Item]) -> None:
    """索引跟目录对不对得上 —— 加了 skill / 命令忘了重扫, 检索是静默失效 (不报错, 只是找不到)。"""
    hint_skill = "./.venv/bin/python skill/skill_search/main.py index"

    # ① skill 索引: 一条 = 一个 skill 目录 (存的是目录, 不是 SKILL.md 路径)
    index = HERE / "skill" / "skill_search" / "scripts" / "skill-index.json"
    on_disk = {str(p.parent.relative_to(HERE)) for p in sorted((HERE / "skill").glob("*/SKILL.md"))}
    have = index_sources(index)
    if have is None:
        fail(items, "结构", "skill 索引能读",
             f"{index.relative_to(HERE)} 读不动 —— 重扫: {hint_skill}")
    else:
        on_disk = {归一来源(x) for x in on_disk}
        have = {归一来源(x) for x in have}
        miss = sorted(on_disk - have)
        extra = sorted(have - on_disk)
        if miss or extra:
            detail: list[str] = []
            if miss:
                detail.append(f"没进索引 {', '.join(miss)}")
            if extra:
                detail.append(f"索引里有但盘上没有 {', '.join(extra)}")
            fail(items, "结构", f"skill 索引跟目录对得上 ({len(on_disk)} 个)",
                 "; ".join(detail) + f" —— 重扫: {hint_skill}")
        else:
            pass_it(items, "结构", f"skill 索引跟目录对得上 ({len(on_disk)} 个 skill)")

    # ② 命令库索引: 带 commands/ 的 skill 各一份, source 去重后该等于那些 .md (一份命令可以切多片)
    bad: list[str] = []
    libs = 0
    total = 0
    for cdir in sorted((HERE / "skill").glob("*/commands")):
        if not cdir.is_dir():
            continue
        files = {str(p.relative_to(HERE)) for p in sorted(cdir.glob("*.md"))}
        if not files:
            continue
        libs += 1
        total += len(files)
        name = cdir.parent.name
        lib = cdir.parent / "commands-index.json"
        if not lib.is_file():
            bad.append(f"{name}: 没有 commands-index.json —— 建索引: ./.venv/bin/python "
                       f"skill/{name}/main.py index")
            continue
        have = index_sources(lib)
        if have is None:
            bad.append(f"{name}: 索引读不动 —— 重扫: ./.venv/bin/python skill/{name}/main.py index")
            continue
        files = {归一来源(x) for x in files}
        have = {归一来源(x) for x in have}
        miss = sorted(files - have)
        extra = sorted(have - files)
        if miss or extra:
            bits = [f"{name}:"]
            if miss:
                bits.append("没进索引 " + ", ".join(Path(m).name for m in miss))
            if extra:
                bits.append("索引里有但盘上没有 " + ", ".join(Path(e).name for e in extra))
            bad.append(" ".join(bits))
    if bad:
        fail(items, "结构", "命令库索引跟目录对得上", "; ".join(bad))
    else:
        pass_it(items, "结构", f"命令库索引跟目录对得上 ({libs} 个库 / {total} 条命令)")


def 归一来源(来源: str) -> str:
    """把索引/盘上扫出来的来源路径归一化：反斜杠换正斜杠、掐掉首尾斜杠。

    ★ Windows 上 Path 出来是 skill\\file，索引里存的是 skill/file —— 不归一化就会
      同一批文件既被报"没进索引"又被报"索引里有但盘上没有"（2026-10-12 实测）。
    """
    return str(来源).replace("\\", "/").strip("/")


def collect_imports(source: str) -> set[str]:
    """从一份 .py 源码里挑出 import 的顶层模块名(是否第三方交给调用方判定)。"""
    names: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def skill_python_files() -> list[Path]:
    """skill 底下要扫的 .py (跳过缓存 / 归档件 / 上游源码)。"""
    skip = {"cache", "_deprecated", "__pycache__", "upstream", "examples"}
    return [
        path
        for path in sorted((HERE / "skill").rglob("*.py"))
        if not any(part in skip for part in path.relative_to(HERE).parts)
    ]


def find_missing_modules(modules: set[str], python: str) -> list[str]:
    """用**项目那个解释器**查这些模块能不能 import 到 —— 跨解释器, 所以走子进程。"""
    if not modules:
        return []
    code = (
        "import importlib.util, json, sys\n"
        "missing = []\n"
        "for name in sys.argv[1:]:\n"
        "    try:\n"
        "        if importlib.util.find_spec(name) is None:\n"
        "            missing.append(name)\n"
        "    except Exception:\n"
        "        missing.append(name)\n"
        "print(json.dumps(missing))\n"
    )
    try:
        done = subprocess.run(
            [python, "-c", code, *sorted(modules)],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if done.returncode != 0:
        return []
    try:
        loaded = cast(object, json.loads(done.stdout.strip() or "[]"))
    except ValueError:
        return []
    return [str(name) for name in cast(list[Any], loaded)] if isinstance(loaded, list) else []


def skill_metadata() -> dict[str, dict[str, Any]]:
    """各 skill 的 metadata.json (按 skill 名)。"""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted((HERE / "skill").glob("*/metadata.json")):
        try:
            loaded = cast(object, json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        if isinstance(loaded, dict) and loaded:
            out[path.parent.name] = cast(dict[str, Any], loaded)
    return out


def 定时命令(入口: Path, 参数: list[str], 环境: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """跑定时 skill 的一条子命令（带 --json），偶发空输出/非零就再来一发。

    ★ 为什么要 -u + PYTHONUNBUFFERED: 面板里跑启动链时，这两条拿到过
      「退出码=0 · 尾巴=(空)」—— 典型的**进程走了、缓冲没刷出来**（stdout 是管道时
      Python 用块缓冲；小 JSON 不足 4KB，进程若不是正常 return 就一个字节都不落）。
      不带缓冲 + 空输出时再从 stderr 捡一次 JSON，两种成因都堵上（2026-10-12 实测）。
    ★ 为什么要重试 + 带诊断: 老代码只报 None，看不出真因；重试一发 + 把退出码与
      stderr 尾巴拼进失败信息，下次红就知道该查子进程还是查环境。
    """
    跑环境 = dict(环境)
    跑环境["PYTHONUNBUFFERED"] = "1"
    命令 = [python_bin(), "-u", str(入口), *参数]
    一 = subprocess.run(命令, cwd=str(HERE), capture_output=True,
                        text=True, timeout=60, env=跑环境, encoding="utf-8", errors="replace")
    if 一.returncode == 0 and (一.stdout or "").strip():
        return 一
    二 = subprocess.run(命令, cwd=str(HERE), capture_output=True,
                        text=True, timeout=60, env=跑环境, encoding="utf-8", errors="replace")
    if (二.stdout or "").strip():
        return 二
    return 二 if (二.stderr or "").strip() else 一


def 取JSON(过程: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """从子进程输出里提取 JSON —— stdout 为空则退到 stderr（缓冲未刷时会落到那边）。"""
    for 文本 in (过程.stdout, 过程.stderr):
        净 = (文本 or "").strip()
        if not 净:
            continue
        行 = 净.splitlines()
        for i, 一 in enumerate(行):          # 从后往前找第一段像 JSON 的
            if 一.lstrip().startswith("{"):
                try:
                    return cast(dict[str, Any], json.loads("\n".join(行[i:])))
                except json.JSONDecodeError:
                    continue
    return {}


def 子进程尾巴(过程: subprocess.CompletedProcess[str] | None) -> str:
    """子进程的退出码 + 最后几行输出 —— 报错时一并带上，不只报一个 None。"""
    if 过程 is None:
        return "没跑到（没有子进程）"
    文本 = (过程.stderr or "").strip() or (过程.stdout or "").strip()
    行 = [x.strip() for x in 文本.splitlines() if x.strip()][-3:]
    return f"退出码={过程.returncode} · 尾巴={' / '.join(行)[:200] if 行 else '(空)'}"


def check_timer(items: list[Item]) -> None:
    """定时任务那一套 —— 老板点名的「闹钟跨重启自检里加上它」。

    全在沙盒里跑(冷库表名带 COLLAPLEX_DB_PREFIX 前缀, 跑完把沙盒表删掉), 不碰生产表。
    """
    入口 = 件定位.件路径(HERE / "skill" / "timer", "main.py")
    if 入口 is None:
        fail(items, "定时", "定时 skill 在", "skill/timer 下没有 main.py / main.pyc")
        return

    # ① 引擎自检(配置能读 / 表能读写 / 时长与时刻解析对)
    try:
        跑 = subprocess.run([python_bin(), str(入口), "selfcheck"],
                            cwd=str(HERE), capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as 错:
        fail(items, "定时", "定时引擎自检跑得起来", str(错))
        return
    if 跑.returncode != 0:
        fail(items, "定时", "定时引擎自检过(配置/表/解析)",
             (跑.stdout + 跑.stderr).strip().splitlines()[-1][:200] if (跑.stdout + 跑.stderr).strip() else "退出码非 0")
        return
    pass_it(items, "定时", "定时引擎自检过(配置能读 / 表能读写 / 时长时刻解析)")

    # ② 跨重启重挂: 手塞一条过期的 -> arm 起来要认出它(并标成待注入 = 补一次)
    环境键 = "自检测_"
    环境 = dict(os.environ)
    环境["COLLAPLEX_DB_PREFIX"] = 环境键        # 冷库沙盒: 表名带前缀(自检测_timers)
    环境["COLLAPLEX_TIMER_PROCESS"] = "自检"
    种子 = ("import json,sys; sys.path.insert(0,'.'); import 库; "
            "库.写文档('timers', '自检', json.loads(sys.argv[1]))")
    subprocess.run([python_bin(), "-c", 种子, json.dumps([{
        "id": "abcd1234", "类型": "倒计时", "到点": 0.0, "时长": 60.0,
        "提醒": "自检用", "阻塞": False, "谁声明": "自检", "登记时刻": 0.0,
        "状态": "挂着", "补的": False,
    }], ensure_ascii=False)], cwd=str(HERE), capture_output=True, text=True,
        timeout=60, check=False, env=环境, encoding="utf-8", errors="replace")
    try:
        甲 = 定时命令(入口, ["arm", "--json"], 环境)
        甲数据 = 取JSON(甲)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as 错:
        fail(items, "定时", "跨重启重挂认得出过期条目", str(错))
        return
    if int(甲数据.get("刚响") or 0) != 1:
        fail(items, "定时", "跨重启重挂认得出过期条目",
             f"arm 回来的 刚响={甲数据.get('刚响')} 挂着={甲数据.get('挂着')} · {子进程尾巴(甲)}")
    else:
        pass_it(items, "定时", "跨重启重挂: 过期条目起来就被认出来(补一次)")

    # ③ 落冷库: web 与 CLI 同一张表、各占一行(两个进程同时开着不能互相覆盖)
    表名们: list[str] = []
    行键们: list[str] = []
    for 名字 in ("web", "cli"):
        环境["COLLAPLEX_TIMER_PROCESS"] = 名字
        跑2 = 定时命令(入口, ["status", "--json"], 环境)
        果2 = 取JSON(跑2)
        表名们.append(str(果2.get("表") or ""))
        行键们.append(str(果2.get("进程键") or ""))
        末次 = 跑2
    if len(set(表名们)) == 1 and all(表名们) and 行键们 == ["web", "cli"]:
        pass_it(items, "定时", f"落冷库、按进程键分行({表名们[0]} · web/cli 各一行)")
    else:
        fail(items, "定时", "web 与 CLI 同一张表各占一行",
             f"表={表名们} 行键={行键们} · {子进程尾巴(末次)}")

    # 收尾: 只删沙盒那张表。★★ 前缀必须设回来 —— 删表跑在**自检自己的进程**里,
    # 这个进程没带前缀, 不设就是用真名去删, 会把生产表 timers 删掉(2026-10-09 实测已踩坑)。
    老前缀 = os.environ.get("COLLAPLEX_DB_PREFIX", "")
    try:
        import memory_store as 库  # noqa: PLC0415  - 仓根就在 sys.path 上

        os.environ["COLLAPLEX_DB_PREFIX"] = 环境键
        库.删表("timers")
    except Exception:                            # noqa: BLE001 - 删不掉不算自检失败
        pass
    finally:
        os.environ["COLLAPLEX_DB_PREFIX"] = 老前缀


def check_skill_deps(items: list[Item], config: dict[str, Any]) -> None:
    """扫 skill 底下每个包: python 包 / 声明的环境变量 / 外部工具 都在不在。"""
    env = cast(dict[str, str], config.get("_env", {}))

    # ① python 包: 扫 import, 拿项目解释器逐个 find_spec
    used: dict[str, str] = {}
    for path in skill_python_files():
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for name in collect_imports(source):
            used.setdefault(name, str(path.relative_to(HERE)))
    stdlib = set(sys.stdlib_module_names)
    internal = {path.stem for path in (HERE / "skill").rglob("*.py")}
    internal |= {path.stem for path in HERE.glob("*.py")}  # 项目根的件: main / sub_agent / exec_agent …
    third = {name: where for name, where in used.items() if name not in stdlib and name not in internal}
    missing = find_missing_modules(set(third), python_bin())
    if missing:
        detail = "; ".join(f"{name} ({third.get(name, '?')} 用)" for name in missing)
        fail(items, "依赖", "skill 用到的 python 包都在", f"缺 {detail} —— 补 requirements.txt 再装")
    else:
        listed = " / ".join(sorted(third)) or "无"
        pass_it(items, "依赖", f"skill 用到的第三方包都在 ({listed})")

    # ② 声明的环境变量 (metadata.json 的 needs.env)
    declared: dict[str, list[str]] = {}
    for name, meta in skill_metadata().items():
        needs = meta.get("needs")
        if not isinstance(needs, dict):
            continue
        keys = cast(dict[str, Any], needs).get("env")
        if isinstance(keys, list):
            for key in cast(list[Any], keys):
                declared.setdefault(str(key), []).append(name)
    gone = [f"{key} ({'/'.join(sorted(who))} 要)" for key, who in declared.items() if not env.get(key)]
    if gone:
        # ★ 缺云 API 的 Key 只是"那几个 skill 用不了"，不是坏 —— 装了本地面（向量/主模型）
        #   照样能跑检索与本地推理。报成提示，不报错（2026-10-12 定）。
        warn(items, "依赖", "skill 声明的环境变量（缺的只有对应 skill 用不了）",
             f"缺 {', '.join(gone)}")
    else:
        pass_it(items, "依赖", f"skill 声明的环境变量都在 ({len(declared)} 个: {', '.join(sorted(declared))})")

    # ③ 声明的外部工具 (metadata.json 的 tool, 如 file skill 要 carve)
    tools: dict[str, list[str]] = {}
    for name, meta in skill_metadata().items():
        tool = meta.get("tool")
        if isinstance(tool, dict):
            binary = str(cast(dict[str, Any], tool).get("name", "")).strip()
            if binary:
                tools.setdefault(binary, []).append(name)
    absent = [name for name in tools if shutil.which(name) is None]
    if absent:
        detail = "; ".join(f"{name} ({'/'.join(sorted(tools[name]))} 要用)" for name in absent)
        warn(items, "依赖", "skill 声明的外部工具在 PATH 上", f"没找到 {detail} —— 缺它只有对应命令跑不了")
    else:
        pass_it(items, "依赖", f"skill 声明的外部工具都在 ({', '.join(sorted(tools)) or '无'})")


def print_icon(items: list[Item]) -> None:
    """把icon.txt 打在自检最上面。"""
    path = HERE / "icon.txt"
    if not path.is_file():
        fail(items, "结构", "icon.txt 在", "不在, 自检头部没图")
        return
    text = path.read_text(encoding="utf-8").rstrip("\n")
    if not text.strip():
        fail(items, "结构", "icon.txt 有内容", "是空的")
        return
    print(text)
    print()


def print_table(items: list[Item]) -> int:
    """五列打出来, 返回那几行宽度。"""
    rows: list[tuple[str, str, str, str, str]] = [
        (item.when, item.where, item.level, item.what, item.result) for item in items
    ]

    widths = [
        max(display_width(HEADER[col]), max(display_width(row[col]) for row in rows))
        for col in range(5)
    ]
    print(" | ".join(pad(HEADER[col], widths[col]) for col in range(5)))
    print("-" * (sum(widths) + 3 * 4))
    for row in rows:
        print(" | ".join(pad(row[col], widths[col]) for col in range(5)))
    return sum(widths) + 3 * 4


def main() -> int:
    """运行一次自检, 返回退出码。"""
    items: list[Item] = []

    print_icon(items)
    config = check_config(items)
    check_apis(items, config)
    check_models(items, config)
    check_skill_deps(items, config)
    check_store(items)
    check_code(items)
    check_indexes(items)
    check_timer(items)

    width = print_table(items)

    right = sum(1 for item in items if item.result == "正确")
    wrong = len(items) - right
    print("-" * width)
    print(f"共 {len(items)} 项")
    print(f"正确 {right}")
    print(f"报错 {wrong}")

    if wrong:
        print()
        print("有报错 —— 没拉起 main.py")
        return 1

    # 全过了。不是人在终端上(管道/重定向/--只查)就到此为止 —— 那种场合要的只是自检结果。
    if "--只查" in sys.argv or not sys.stdin.isatty():
        return 0

    print()
    print("自检通过 —— 拉起 main.py")
    print()
    os.execv(python_bin(), [python_bin(), str(HERE / "main.py")])
    raise SystemExit(0)  # execv 成功就到不了这儿


if __name__ == "__main__":
    sys.exit(main())
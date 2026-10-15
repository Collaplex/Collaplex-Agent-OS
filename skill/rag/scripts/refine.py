#!/usr/bin/env python3
"""清洗管线: 二层(热) -> 三层(冷).

老板定的流程 (2026-10-05), 顺序不能变:
  ① 先复制 —— 二层全部切片**原样**搬进**历史对话层**(tier=1), 标 kind="对话",
              带 对话id/对话时间 (= 时间线); 向量直接复用
              (一字不改, 连向量都直接复用 —— 出问题三层还有得取)
  ② 再清洗 —— 按 source 读回 corpus 原文, 跑三遍小模型:
              概述 / 知识 / 别名 -> 三层 (别名进 alias.json, 不嵌向量)
              ★ 文件没了就先拿历史对话层(tier=1)的原文回填着洗(① 是一字不改搬的);
                两边都空才记进 state/refine-待重洗.json, 不当"洗过了"
  ③ 清空二层 —— 二层(tier=2)的那批对话产出清掉 + corpus/ 删(项目语料不动)
              (到这一步才敢清, 因为原文已经在三层躺好了)

触发: 主 agent 判定"任务结束"= true 之后, 静默 20 分钟无人操作,
      由 --看守 拉起来跑。这就是 seek skill 里那个 `任务结束` 键的用途。

★ 提示词一律从 config/skills/refine-*.md 读, 代码里不写裸提示词。
★ 每轮开头打一个时间戳(日志是 cron 追的, 没时间戳对不上账), 收尾带耗时;
  每次还落一次心跳 state/refine-心跳.json —— 没活时不出声, 靠它判断进程是否还在跑。

跑法:
  .venv/bin/python skill/rag/scripts/refine.py             # 立刻清一次
  .venv/bin/python skill/rag/scripts/refine.py --看守       # 常驻看守, 到点自己清
  .venv/bin/python skill/rag/scripts/refine.py --干跑       # 只看要清什么, 不动库
  .venv/bin/python skill/rag/scripts/refine.py --待重洗     # 只看洗不了的账
  .venv/bin/python skill/rag/scripts/refine.py --回填       # 把三层里的半成品补洗一遍
  .venv/bin/python skill/rag/scripts/refine.py --安静       # 没活干不出声

★ 想把它打到别处/开并发(超算实例、平台 API):
  .venv/bin/python skill/rag/scripts/refine.py --端点 https://<实例ID>.zzai.scnet.cn:58043/v1 \
      --模型 qwen3-vl-8b --并发 16 --强制
  说明: --端点 要带 /v1; --并发 N = 同时在飞的请求数(默认 1 = 老行为)。
        ★ 清洗是**预填主导**的活(输入 1970 万 token / 输出 16 万), 单流吃不满卡, 并发才是收益来源。
"""

import argparse
import hashlib
import json
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent      # skill/rag/scripts
SKILL_DIR = HERE.parent                      # skill/rag

sys.path.insert(0, str(HERE))
import store  # noqa: E402  (同目录模块, 得先补 sys.path)
ROOT = SKILL_DIR.parent.parent               # 项目根 (跟 embed.py / search.py 一个算法)
CONFIG_DIR = ROOT / "config"
STATE_DIR = ROOT / "state"
ENV_PATH = ROOT / ".env"

TIER1_PATH = SKILL_DIR / "scripts" / "history-index.json"      # ★ 历史对话层(走 PG, 路径只是层标记)
TIER2_PATH = SKILL_DIR / "scripts" / "vector-index.json"
TIER3_PATH = SKILL_DIR / "scripts" / "memory-index.json"
ALIAS_PATH = SKILL_DIR / "scripts" / "alias.json"
CORPUS_DIR = SKILL_DIR / "corpus"

ACTIVITY_PATH = STATE_DIR / "activity.json"
REFINE_STATE_PATH = STATE_DIR / "refine-state.json"
# 待重洗账本: 语料文件没了、三层也没这一批原文的 —— 不许静默当"洗过了"
PENDING_PATH = STATE_DIR / "refine-待重洗.json"
# 心跳: cron 每分钟一次, 没活时不出声, 靠它证明"还活着、什么时候看的"
HEARTBEAT_PATH = STATE_DIR / "refine-心跳.json"

# 别名表要单独立一份: 它不嵌向量, 是给字符串包含匹配用的, 跟知识条目不同质
KIND_RAW = "原文"        # 老写法留下的 kind, 现只用于识别历史遗留
KIND_DIALOG = "对话"     # ★ 历史对话层(tier=1)的 kind
KIND_SUMMARY = "概述"
KIND_KNOWLEDGE = "知识"

CONFIG_PATH = CONFIG_DIR / "agent.json"


def prompt_name(key: str, fallback: str) -> str:
    """清洗用哪份提示词 —— 走配置(config/agent.json 的 refine.prompts), 不硬编码在代码里。

    提示词本体一律在 config/skills/<名>.md, 跟规划/判断/挑选/执行 一个待遇。
    """
    section = refine_config().get("prompts")
    if isinstance(section, dict):
        value = cast(dict[str, Any], section).get(key)
        if isinstance(value, str) and value:
            return value
    return fallback



# ---------------- 配置 / 环境 ----------------


# --本地: 钉死本机模型(127.0.0.1:8790), 一分钱不花。
# ★ 为什么非要这个开关: read_env() 是直接解析 .env 文件的, 环境变量盖不过它;
#   而 .env 的 OPENAI_BASE_URL 是给**主 agent** 用的(可能是云 API), 去改它会把
#   agent 一起带偏。清洗是长跑批处理(几百次调用), 走云就是在烧钱 —— 所以给它
#   一个独立开关, 跟主 agent 的模型配置解耦。
本地模式: bool = False

# --端点 / --并发: 把清洗的模型调用打到别处(超算实例的 vLLM、平台 token API 都行),
#   并允许同时发多个请求。
# ★ 为什么要并发: 清洗是**预填(prefill)主导**的活 —— 全量 3504 次调用里
#   输入约 1970 万 token、输出才 16 万; 单流无论如何跑不满一张卡
#   (实测本机 8B 单流预填 ~1300~2500 token/s)。并发才是这里的收益来源。
# ★ 并发度=1 时**与原行为逐字一致**(还是串行, 顺序也一样), 老跑法不受影响。
远端端点: str = ""
远端密钥: str = ""
远端模型: str = ""
并发度: int = 1
# ★ 文件并发度: 同时在飞的**文件**数。
#   为什么光有 --并发 不够: 清洗是"一个文件一个文件走"的, 每个文件只发 3×段数(多数文件
#   只有 1 段 → 就 3 条)请求, 池子开 16 也填不满 —— 实测在飞一直只有 2~3 条, 而 8B 在
#   A800 上是 batch 越小越亏(batch 1 = 48ms/步 = 21 tok/s, batch 16 = 105ms/步 = 153 tok/s),
#   于是 520 个文件要跑 9 小时。**多开几个文件同时在飞**才是把 batch 填起来的办法。
文件并发度: int = 1
# ★ 三层/别名表都是"读全部-改-写全部", 跨文件并发时后写的会把先写的覆盖(直接丢概述/知识)。
#   模型调用(慢)必须在锁外, 只有读-改-写这一段进锁。
索引锁 = threading.Lock()
# 让一个文件的打印块不跟别的文件交错(否则日志读不了), 不参与正确性。
输出锁 = threading.Lock()

# ★ 模型调用失败: **退避重试到成功**; 试满上限还不行就**全线停**(绝不当作"洗成空")。
#   老行为是"记一条警告、该项当空" —— 模型掉线时会把概述/知识洗成空账, 而且旧概述在写之前
#   就被删掉了, 越洗越少。无人值守下(每分钟 cron)这种静默掏空最危险: 跑完还会执行 ③
#   清二层、删语料原文, 原文一没就再也补不回来。
#   退避: 3/6/12/24/48/60/60 → 一条请求最多承受约 3.5 分钟(够模型重启一次), 之后全线停。
重试上限: int = 8
重试基隔: float = 3.0


class 全线停(Exception):
    """模型一直问不出来 —— 停整轮: ② 当场停手, ③ 绝不执行(二层/三层/语料原样留着)。"""


def read_env() -> dict[str, str]:
    """读项目根 .env —— 模型调用信息统一从那来, 这里不硬编码端点。

    ★ 注意: 这是**直接解析文件**, 不是 dotenv —— 环境变量覆盖不了它。
      所以想让清洗单独走本地, 需依赖 --本地 开关(见 本地模式), 不要去改这份 .env
      (主 agent 也在读它, 改了会把 agent 一起指到本地)。
    """
    values: dict[str, str] = {}
    if not ENV_PATH.is_file():
        return values
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def refine_config() -> dict[str, Any]:
    """清洗相关的开关 (config/agent.json 的 refine 段)。"""
    defaults: dict[str, Any] = {
        "idle_seconds": 1200,
        "watch_interval": 60,
        "max_tokens": 1536,
        "knowledge_limit": 8,
    }
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    section = data.get("refine")
    if not isinstance(section, dict):
        return defaults
    merged = dict(defaults)
    for key, value in cast(dict[str, Any], section).items():
        merged[key] = value
    return merged


def read_skill(name: str) -> str:
    """提示词从 config/skills/<名>.md 读, 剥掉 frontmatter, 正文就是系统提示。"""
    path = CONFIG_DIR / "skills" / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            text = text[end + 4 :]
    return text.strip()


# 清洗用哪几份提示词 —— 这里才读配置: 上面 prompt_name/refine_config 得先定义好
PROMPT_SUMMARY = prompt_name("summary", "refine-summary")
PROMPT_KNOWLEDGE = prompt_name("knowledge", "refine-knowledge")
PROMPT_ALIAS = prompt_name("alias", "refine-alias")


# ---------------- 模型 / 嵌入 ----------------


def post_json(url: str, payload: dict[str, Any], timeout: float = 300.0, key: str = "") -> Any:
    headers = {"Content-Type": "application/json"}
    # ★ 端点可能是云端(要鉴权)也可能是本机(不要). 早先只发 Content-Type ——
    #   默认路由指向本机模型时没事, 一改成云端就整齐 401(2026-10-08 实测踩到).
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    # 本机 Clash 会拦 127.0.0.1, 直连
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def embed(text: str) -> list[float]:
    env = read_env()
    base = env.get("EMBEDDING_BASE_URL", "http://127.0.0.1:8199/v1").rstrip("/")
    model = env.get("EMBEDDING_MODEL", "qwen3-embedding-0.6b")
    pack = post_json(
        f"{base}/embeddings",
        {"model": model, "input": [text]},
        key=env.get("EMBEDDING_API_KEY", ""),
    )
    return [float(v) for v in cast(list[Any], cast(list[Any], pack["data"])[0]["embedding"])]


def ask_model(system_prompt: str, content: str) -> Any:
    """问一次模型, 返回剥好的 JSON (对象或数组)。"""
    env = read_env()
    if 远端端点:
        # --端点: 打到别处(超算实例 vLLM / 平台 token API)。★ base 要带 /v1。
        base = 远端端点.rstrip("/")
        model = 远端模型 or env.get("OPENAI_MODEL", "qwen3-vl-8b")
        key = 远端密钥
    elif 本地模式:
        base = "http://127.0.0.1:8790/v1"
        model = "qwen3-vl-8b"
        key = ""
    else:
        base = env.get("OPENAI_BASE_URL", "http://127.0.0.1:8790/v1").rstrip("/")
        model = env.get("OPENAI_MODEL", "qwen3-vl-8b")
        key = env.get("OPENAI_API_KEY", "")
    config = refine_config()
    pack = post_json(
        f"{base}/chat/completions",
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "temperature": 0,
            "max_tokens": int(config["max_tokens"]),
            "stream": False,
            # ★ 思考模式默认开: 思考 token 算进 max_tokens, 正文会被挤空(实测 content=""),
            #   而这里要的正是 JSON 正文。两家(MiMo/DeepSeek)都认这个开关, 不认的会忽略。
            "thinking": {"type": "disabled"},
        },
        key=key,
    )
    text = str(cast(list[Any], pack["choices"])[0]["message"]["content"])
    return strip_json(text)


def 问稳(system_prompt: str, content: str) -> Any:
    """问一次模型, 失败**退避重试**; 试满上限还不行就抛 全线停。

    ★ 为什么不吞掉: 一旦吞掉, 这次清洗就"没有概述/没有知识", 而三层里那条旧概述已经在
      写新的时候被删掉了 —— 一次掉线就永久少一块。无人值守时宁可当场停住等下轮。
    """
    上次错: Exception | None = None
    for 第几次 in range(1, 重试上限 + 1):
        try:
            return ask_model(system_prompt, content)
        except Exception as error:  # noqa: BLE001 —— 网络/HTTP/JSON 什么错都值得再试一次
            上次错 = error
            if 第几次 < 重试上限:
                等 = min(重试基隔 * (2 ** (第几次 - 1)), 60.0)
                print(
                    f"    [重试 {第几次}/{重试上限}] 模型没答上来({error}), 等 {等:.0f} 秒再来",
                    file=sys.stderr,
                )
                time.sleep(等)
    raise 全线停(f"模型连续 {重试上限} 次没答上来, 最后一个错: {上次错}")


def strip_json(text: str) -> Any:
    """剥出模型输出里的 JSON. **对象和数组都认。**

    旧项目已踩坑记录: 只认 dict 时, 模型明明给了顶层数组, 程序说"0 组"。
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        newline = cleaned.find("\n")
        cleaned = cleaned[newline + 1 :] if newline >= 0 else cleaned
        fence = cleaned.rfind("```")
        if fence >= 0:
            cleaned = cleaned[:fence]
        cleaned = cleaned.strip()
    left = min((i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0), default=-1)
    right = max(cleaned.rfind("}"), cleaned.rfind("]"))
    candidates = [cleaned, cleaned[left : right + 1]] if left >= 0 and right > left else [cleaned]
    for candidate in candidates:
        try:
            parsed: Any = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, (dict, list)):
            return cast(dict[str, Any] | list[Any], parsed)
    return None


def as_list(pack: Any, key: str) -> list[Any]:
    """模型可能给顶层数组, 也可能给 {键: [...]}, 两种都认。"""
    if isinstance(pack, list):
        return cast(list[Any], pack)
    if isinstance(pack, dict):
        return cast(list[Any], cast(dict[str, Any], pack).get(key) or [])
    return []


# ---------------- 索引读写 ----------------
# 二层/三层可能落在 PG(store 后端) 或 JSON 文件; 别名表永远是 JSON(它不嵌向量, 另立一份)


_RAG_CONFIG: dict[str, Any] = {}


def rag_config() -> dict[str, Any]:
    """读 rag 的配置(判断走 JSON 还是 PG). 结果缓存."""
    if not _RAG_CONFIG:
        path = SKILL_DIR / "resources" / "embed.json"
        if path.is_file():
            data: Any = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _RAG_CONFIG.update(cast(dict[str, Any], data))
    return _RAG_CONFIG


def tier_of(path: Path) -> str | None:
    """这个路径对应哪一层(该走 store 后端); 不是二层/三层就返回 None."""
    if path == TIER1_PATH:
        return "1"
    if path == TIER2_PATH:
        return "2"
    if path == TIER3_PATH:
        return "3"
    return None


def load_index(path: Path) -> dict[str, Any]:
    """读索引包. 二层/三层走 store 后端(按配置 PG 或 JSON); 别的(别名表)永远是 JSON."""
    tier = tier_of(path)
    if tier is not None and store.is_pg(rag_config()):
        with store.connect(rag_config()) as conn:
            items = store.load_existing(conn, rag_config(), tier)
        return {"meta": {"count": len(items), "dimension": 1024}, "items": items}

    if not path.is_file():
        return {"meta": {}, "items": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"meta": {}, "items": []}
    if not isinstance(data, dict):
        return {"meta": {}, "items": []}
    pack = cast(dict[str, Any], data)
    if not isinstance(pack.get("items"), list):
        pack["items"] = []
    return pack


def save_index(path: Path, pack: dict[str, Any]) -> None:
    """写索引包. 二层/三层走 store 后端; 别的走 JSON. 落盘前 index 重排一遍."""
    items = cast(list[Any], pack.get("items") or [])
    for position, item in enumerate(items):
        if isinstance(item, dict):
            cast(dict[str, Any], item)["index"] = position
    meta = cast(dict[str, Any], pack.setdefault("meta", {}))
    meta["count"] = len(items)
    meta["dimension"] = 1024

    tier = tier_of(path)
    if tier is not None and store.is_pg(rag_config()):
        rows = [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]
        with store.connect(rag_config()) as conn:
            store.ensure_schema(conn, rag_config(), 1024)
            store.upsert(conn, rag_config(), tier, rows)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def make_item(text: str, source: str, kind: str, vector: list[float] | None) -> dict[str, Any]:
    return {
        "index": 0,
        "vector": vector if vector is not None else embed(text),
        "text": text,
        "hash": digest(text),
        "source": source,
        "kind": kind,
    }


# ---------------- 二层的"一次问答" ----------------


def is_corpus_source(source: str) -> bool:
    """source 是不是"对话产出"。

    ★ 二层里除了对话产出, 还躺着建库时索进去的项目源码/文档 —— 那些是静态语料,
      建一次就定住了, 不会越积越多, 不归清洗管。只认 corpus/ 底下的。

    ★ 用 is_relative_to 而不是 parent == corpus: 导出的会话落在 corpus/hermes-history/
      子目录里(import_hermes_hist.py 就是这么写的), 只比一层父目录会把它们全判假 ——
      症状是 refine 报"二层是空的"而 tier=2 明明有数据。
    """
    try:
        path = Path(source)
        if not path.is_absolute():
            path = ROOT / path
        return path.resolve().is_relative_to(CORPUS_DIR.resolve())
    except (OSError, ValueError):
        return False


def tier2_groups() -> dict[str, list[dict[str, Any]]]:
    """把二层的**对话产出**按 source 分组 —— 一个 source = 一次问答 = 一个清洗单位。"""
    pack = load_index(TIER2_PATH)
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in cast(list[Any], pack.get("items") or []):
        if not isinstance(item, dict):
            continue
        entry = cast(dict[str, Any], item)
        source = str(entry.get("source", ""))
        if not source or not is_corpus_source(source):
            continue
        groups.setdefault(source, []).append(entry)
    return groups


def corpus_files() -> list[Path]:
    """corpus/ 下所有语料文件(含子目录)。

    ★ 必须 rglob: 导出的会话在 corpus/hermes-history/ 子目录里, 只 glob 顶层
      会一个都列不出来 —— 后果是 run_once 清理环节永远匹配不到目标, 语料洗完不删,
      下一轮又把同一批重新切一遍/嵌一遍。
    """
    if not CORPUS_DIR.is_dir():
        return []
    return sorted(path for path in CORPUS_DIR.rglob("*.md") if path.is_file())


def source_time(source: str) -> str | None:
    """语料文件的 mtime —— 二层行没带时间戳时的兜底时间。

    ★ 为什么用文件时间: 热层的行是 embed.py 从语料文件切出来的, 那时候还没带时间戳
      (embed.py 只管切和嵌)。而语料文件的 mtime 就是"导出这个会话"的那一刻,
      用它当会话时间比写 NULL 强 —— 历史对话层的本职就是时间线, 不能有没时间的行。
    """
    path = Path(source)
    if not path.is_absolute():
        path = ROOT / path
    try:
        秒 = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(秒, tz=timezone(timedelta(hours=8))).isoformat()


def session_name(source: str) -> str:
    """source 的短名, 当"这次问答"的标签 —— 三层里靠它做先删后插。"""
    return Path(source).stem or source


def history_raw(source: str) -> str:
    """把**历史对话层**(tier=1)里这一批的切片拼回来。

    ★ 为什么能这么干: ① 搬运是"一字不改"的, tier=1 那些切片就是原文(按块)。
      所以 corpus 文件被上一轮③删掉、这一轮又被挑出来时, ② 还有得洗 ——
      实测已踩坑 6 轮"读不到语料原文, 跳过清洗", 那些批的原文躺进了库里、
      却一条概述/知识/别名都没洗出来, 等于永久半成品。
    """
    pack = load_index(TIER1_PATH)
    texts: list[str] = []
    for item in cast(list[Any], pack.get("items") or []):
        if not isinstance(item, dict):
            continue
        entry = cast(dict[str, Any], item)
        if str(entry.get("kind", "")) not in (KIND_DIALOG, KIND_RAW) or str(entry.get("source", "")) != source:
            continue
        text = str(entry.get("text", ""))
        if text.strip():
            texts.append(text)
    return "\n\n".join(texts)


def read_material(source: str) -> tuple[str, str]:
    """② 的原文从哪来 —— 返回 (原文, 出处)。

    先读 corpus 文件; 文件没了就从三层回填。两边都空才交回调用方记待重洗。
    """
    for candidate in (CORPUS_DIR / Path(source).name, ROOT / source):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8"), "语料文件"
    return history_raw(source), "历史对话回填"


def stale_sources() -> dict[str, int]:
    """**历史对话层(tier=1)有、经验层(tier=3)却没概述**的 source —— ② 没洗完留下的半成品。

    ★ 实测: 旧代码读不到语料文件就放过(原文进库就算完), 留下 5 批 22 片
      只有原文、没有概述/知识/别名。这里的判据就是拿这个事实定的。
    """
    raw: dict[str, int] = {}
    for item in cast(list[Any], load_index(TIER1_PATH).get("items") or []):
        if not isinstance(item, dict):
            continue
        source = str(cast(dict[str, Any], item).get("source", ""))
        if source:
            raw[source] = raw.get(source, 0) + 1
    summarized: set[str] = set()
    for item in cast(list[Any], load_index(TIER3_PATH).get("items") or []):
        if not isinstance(item, dict):
            continue
        entry = cast(dict[str, Any], item)
        if entry.get("kind") == KIND_SUMMARY:
            summarized.add(str(entry.get("source", "")))
    return {source: pieces for source, pieces in raw.items() if source not in summarized}


def load_pending() -> dict[str, dict[str, Any]]:
    """读待重洗账本 —— 洗不了的要留账, 不能静默放过。"""
    if not PENDING_PATH.is_file():
        return {}
    try:
        data = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): cast(dict[str, Any], value)
        for key, value in cast(dict[str, Any], data).items()
        if isinstance(value, dict)
    }


def save_pending(pending: dict[str, dict[str, Any]]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(
        json.dumps(pending, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_heartbeat(batches: int, pending: int = 0) -> None:
    """落一次心跳 —— 日志只在有活时才有行, 平时靠这个文件看它到底还在不在跑。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(
        json.dumps(
            {
                "上次检查": time.strftime("%Y-%m-%d %H:%M:%S"),
                "二层对话产出": batches,
                "待重洗": pending,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


# ---------------- 三步 ----------------


def copy_to_history(groups: dict[str, list[dict[str, Any]]]) -> int:
    """① 先复制: 二层切片原样搬进**历史对话层**(tier=1), 标 kind='对话', 带时间线。

    ★ 这一步是"底档"——永久留、只增不减, 所以走 store.append_history(按 source 先删后插),
      而不是 save_index(那是整层覆盖, 会把其他场次一起清除)。
    ★ 对话时间: 二层行里带就用(热层写入时该带); 没有就退回入库时间 created_at,
      宁可时间粗一点, 也不能让这一层出现没有时间的行(时间线是它的本职)。
    """
    items: list[dict[str, Any]] = []
    for source, entries in groups.items():
        session = session_name(source)
        # ★ 时间兜底顺位: 行里带的时间 > 语料文件 mtime(导出那一刻) > 写入时的现在
        文件时间 = source_time(source)
        for 序, entry in enumerate(entries):
            vector = entry.get("vector")
            if not isinstance(vector, list):
                continue
            item = make_item(str(entry.get("text", "")), source, KIND_DIALOG, cast(list[float], vector))
            item["index"] = 序  # ★ make_item 里恒为 0, 不编号的话 ORDER BY idx 排序全废
            item["对话id"] = session
            # ★ 时间戳拿不到就写 None -> PG 的 NULL。写成 "" 会被 timestamptz 拒收
            #   (invalid input syntax for type timestamp: ""), 整批搬运直接崩。
            时间 = entry.get("对话时间") or entry.get("created_at") or 文件时间
            item["对话时间"] = str(时间) if 时间 else None
            item["角色"] = str(entry.get("角色") or "")
            items.append(item)
    if not items:
        return 0
    配置 = rag_config()
    with store.connect(配置) as conn:
        store.ensure_schema(conn, 配置, 1024)
        return store.append_history(conn, 配置, items)


# ★ 单次喂给模型的正文上限 / 最多段数
#   模型(qwen3-vl-8b)窗口 32768 token, 中文实测 1 字 ≈ 1 token; 再扣掉 prompt 与
#   输出(1536)的份, 12000 字符/段留了足够余量。
CLEAN_SEG_CHARS = 12000
CLEAN_MAX_SEG = 12


def segments(material: str) -> list[str]:
    """把整份会话切成模型喂得下的段。

    ★ 为什么必须切: material 是整个会话文件, 最大的有 3.6MB —— 直接喂必然超窗口。
      实测(2026-10-08): 最大的会话 material 有 543403 字符, 而窗口只有 32768,
      原样送第一次调用就会失败, 那条会话的经验层永远洗不出来。

    段数封顶 CLEAN_MAX_SEG: 再长也只取前 N 段。大会话尾部多是同质内容,
    为它多花十几倍的模型调用不划算(清洗走本地模型, 但一次调用仍要几十秒)。
    """
    text = material.strip()
    if not text:
        return []
    if len(text) <= CLEAN_SEG_CHARS:
        return [text]
    段: list[str] = []
    for 起 in range(0, len(text), CLEAN_SEG_CHARS):
        段.append(text[起:起 + CLEAN_SEG_CHARS])
        if len(段) >= CLEAN_MAX_SEG:
            break
    return 段


def 三遍并跑(段们: list[str], 标签: str = "") -> tuple[list[Any], list[Any], list[Any]]:
    """把「每段三遍(概述/知识/别名)」一起发出去, 返回按段序对齐的三组结果。

    ★ 为什么能并发: 每段的三遍喂的是**同一份 material**(只有 system prompt 不同),
      段与段之间也互不依赖 —— 天然就有 3×段数 的并行度。而清洗是预填主导的活,
      串行发请求等于让卡一直饿着。
    ★ 并发度 <= 1 时走的就是原来的串行路径, 顺序与结果与老版本一致。
    ★ 模型问不出来不再是"当空"就完事: 走 问稳(), 它会退避重试; 试到上限就抛 全线停
      —— 这里把它原样往上抛, 由 run_once 停住整轮(不写空账、不进 ③)。
    ★ 每答完一条打一行进度(标签 = 来源名): 大文件(多段×3遍)要跑好几分钟, 只在文件
      收尾时只打一行的话, 日志看着就像"卡死了" —— 2026-10-11 就是这么问的。
    """
    任务: list[tuple[str, int, str, str]] = []
    for 序号, 段 in enumerate(段们):
        任务.append(("概述", 序号, read_skill(PROMPT_SUMMARY), 段))
        任务.append(("知识", 序号, read_skill(PROMPT_KNOWLEDGE), 段))
        任务.append(("别名", 序号, read_skill(PROMPT_ALIAS), 段))

    结果: dict[tuple[str, int], Any] = {}
    总数 = len(任务)
    完成 = 0
    if 并发度 <= 1:
        for 类, 序号, prompt, 段 in 任务:
            结果[(类, 序号)] = 问稳(prompt, 段)
    else:
        with ThreadPoolExecutor(max_workers=并发度) as 池:
            在飞 = {池.submit(问稳, prompt, 段): (类, 序号) for 类, 序号, prompt, 段 in 任务}
            for 期货 in as_completed(在飞):
                类, 序号 = 在飞[期货]
                完成 += 1
                try:
                    结果[(类, 序号)] = 期货.result()
                    with 输出锁:
                        print(f"      [进度] {标签} 第 {序号 + 1}/{len(段们)} 段 {类} 好了 ({完成}/{总数})")
                except 全线停:
                    for 剩下 in 在飞:      # 模型已经不答了, 别让剩下的白跑
                        剩下.cancel()
                    raise
                except Exception as error:  # noqa: BLE001 —— 兜住非模型类意外, 不静默
                    print(f"    [并发] 第 {序号 + 1} 段 · {类} 调用失败: {error}", file=sys.stderr)
                    结果[(类, 序号)] = None

    return (
        [结果.get(("概述", i)) for i in range(len(段们))],
        [结果.get(("知识", i)) for i in range(len(段们))],
        [结果.get(("别名", i)) for i in range(len(段们))],
    )


def clean_one(source: str, material: str) -> dict[str, int]:
    """② 再清洗: 一次问答 -> 概述 / 知识 / 别名。

    ★ 按段洗: material 可能是整个大会话(最大 3.6MB), 一次喂不进去 ——
      切成 segments() 逐段调模型, 再把结果合并(概述拼接 / 知识去重 / 别名合并)。
      小会话只有一段, 退化成原来的"一次调用", 开销不变。
    """
    session = session_name(source)
    段们 = segments(material)

    # ★ 慢活(模型调用)先做完, 再进锁做三层的"读-改-写"。
    #   原来是**一进来就读三层、末尾才写**, 中间隔着一堆模型调用 —— 跨文件并发时别的文件
    #   也在这个窗口里读改写, 后写的会把先写的整个覆盖(直接丢概述/知识)。
    概述包们, 知识包们, 别名包们 = 三遍并跑(段们, 标签=session)

    概述们: list[str] = []
    for summary_pack in 概述包们:
        if isinstance(summary_pack, dict):
            每段 = str(cast(dict[str, Any], summary_pack).get("概述") or "").strip()
            if 每段:
                概述们.append(每段)
    summary = " ".join(概述们)

    # 知识: N 条, 按 session 先删后插; 多段则合并去重, 再截到上限
    knowledge: list[str] = []
    limit = int(refine_config()["knowledge_limit"])
    for knowledge_pack in 知识包们:
        for 条 in as_list(knowledge_pack, "知识"):
            正文 = str(条).strip()
            if 正文 and 正文 not in knowledge:
                knowledge.append(正文)
    knowledge = knowledge[:limit]

    # ★ 挂指针: 经验层每条记它出处 tier=1 的行 id —— 顺着能回原文(查库放锁外)
    with store.connect(rag_config()) as conn:
        指针 = store.ids_by_source(conn, rag_config()).get(source) or store.ids_by_source(conn, rag_config()).get(Path(source).name, "")

    # ★ 读-改-写整段进锁(见 索引锁 的注释): 概述"按 session 先删后插"这条语义也依赖
    #   这一次读到的旧集合, 所以必须在锁里现读。
    with 索引锁:
        pack = load_index(TIER3_PATH)
        kept: list[dict[str, Any]] = []
        for item in cast(list[Any], pack.get("items") or []):
            if not isinstance(item, dict):
                continue
            entry = cast(dict[str, Any], item)
            if entry.get("kind") == KIND_SUMMARY and str(entry.get("session", "")) == session:
                continue
            kept.append(entry)
        if summary:
            item = make_item(summary, source, KIND_SUMMARY, None)
            item["session"] = session
            kept.append(item)
        for text in knowledge:
            item = make_item(text, source, KIND_KNOWLEDGE, None)
            item["session"] = session
            kept.append(item)
        for item in kept:
            if item.get("source") == source and not item.get("来源id"):
                item["来源id"] = 指针
        pack["items"] = kept
        save_index(TIER3_PATH, pack)

    # 别名: 一个别名一行, (概念, 别名词) 去重; 上位词反向也建一条
    #   多段则各段出的概念合并, write_aliases 内部会去重
    groups: list[dict[str, Any]] = []
    for alias_pack in 别名包们:
        groups.extend(
            cast(dict[str, Any], x) for x in as_list(alias_pack, "概念") if isinstance(x, dict)
        )
    alias_count = write_aliases(groups)

    return {
        "概述": 1 if summary else 0,
        "知识": len(knowledge),
        "别名": alias_count,
    }


def alias_acceptable(concept: str, alias: str) -> bool:
    """这条别名能否进表 —— 模型不按规矩时, 由代码兜底。

    ★ 实测已踩坑: 模型会产**单字别名**(`库` / `冷`)和**互相包含**的说法(`库` ⊂ `二层热库`),
      还会把语义相反的当别名(`冷` -> `二层热库`)。

      单字问题最严重: 检索是"字符串包含"匹配, 任何含这个字的查询都会被多检索一次,
      等于给检索灌噪声 —— 别名路本来是用来提召回的, 这么做反而降精度。

      提示词里明明写了自检法("把概念换成别名, 意思不能变"), 模型照样不照做 ——
      跟旧项目"上位词写进规矩里不管用"是同一个下场。所以**不能靠模型自觉**。
    """
    if len(concept) < 2 or len(alias) < 2:
        return False  # 单字: 会误伤一切含这个字的查询
    if concept == alias:
        return False  # 同一个词不算别称
    if concept in alias or alias in concept:
        return False  # 一个包着另一个 = 包含关系, 不是别称
    return True


def write_aliases(groups: list[dict[str, Any]]) -> int:
    """别名表的对外入口 —— 整段「读全部-改-写全部」进 索引锁。

    ★ 别名表也是同一套读改写, 跨文件并发不加锁同样会互相覆盖(丢别名)。
    """
    with 索引锁:
        return _写别名表(groups)


def _写别名表(groups: list[dict[str, Any]]) -> int:
    """别名表: 唯一键 (概念, 别名词) —— 一个别名一行, 重复清洗不会使表膨胀。"""
    table = load_index(ALIAS_PATH)
    rows = [
        cast(dict[str, Any], x) for x in cast(list[Any], table.get("items") or []) if isinstance(x, dict)
    ]
    known = {(str(r.get("概念", "")), str(r.get("别名词", ""))) for r in rows}
    written = 0
    refused: list[str] = []

    def put(concept: str, alias: str, scene: str) -> None:
        nonlocal written
        key = (concept, alias)
        if not concept or not alias or key in known:
            return
        if not alias_acceptable(concept, alias):
            refused.append(f"{concept} -> {alias}")
            return
        rows.append({"概念": concept, "别名词": alias, "场合": scene})
        known.add(key)
        written += 1

    for group in groups:
        concept = str(group.get("概念") or "").strip()
        scene = str(group.get("语境") or "").strip()
        if not concept:
            continue
        for alias in (str(x).strip() for x in cast(list[Any], group.get("别名") or [])):
            put(concept, alias, scene)
        # 上位词反过来也建一条: 用户问"网络设备", 该召回"路由器/软路由/交换机"
        for upper in (str(x).strip() for x in cast(list[Any], group.get("上位") or [])):
            put(upper, concept, scene)

    if refused:
        print(f"        挡掉 {len(refused)} 条不成立的: {', '.join(refused[:6])}"
              + (" ..." if len(refused) > 6 else ""), flush=True)

    table["items"] = rows
    save_index(ALIAS_PATH, table)
    return written


def clear_tier2(cleaned: set[str]) -> tuple[int, int]:
    """③ 清空二层 —— **只清刚清过的那批对话产出**, 项目语料留着。

    到这一步原文已经在三层躺好了(①先复制), 所以删了不丢东西。
    """
    pack = load_index(TIER2_PATH)
    kept: list[Any] = [
        item
        for item in cast(list[Any], pack.get("items") or [])
        if not (isinstance(item, dict) and str(cast(dict[str, Any], item).get("source", "")) in cleaned)
    ]
    dropped = len(cast(list[Any], pack.get("items") or [])) - len(kept)
    pack["items"] = kept
    save_index(TIER2_PATH, pack)

    removed = 0
    # ★ 只删**这一批清过的**语料文件. 早先是无差别删 corpus/ 下所有 md ——
    #   那么"刚写进 corpus 但还没嵌进二层""这轮没进清洗清单"的文件会被一起删掉,
    #   而它们的内容从没进三层 = 真丢内容(2026-10-08 实测踩到).
    targets: set[Path] = set()
    for source in cleaned:
        raw = Path(source)
        targets.add((raw if raw.is_absolute() else ROOT / raw).resolve())
    for path in corpus_files():
        if path.resolve() not in targets:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError as error:
            print(f"    语料删不掉 {path.name}: {error}", file=sys.stderr)
    return dropped, removed


def backfill(quiet: bool = False) -> dict[str, int]:
    """把三层里的半成品补洗一遍 —— 原文就在三层, 用它洗。

    ★ 跟 run_once 里那条回填是同一套料, 分工不同: 那条面向**新批次**
      (文件没了还能洗), 这条面向**旧账**(已经躺在三层的半成品)。
      历史遗留 5 批 22 片就是靠它收尾的。
    """
    stale = stale_sources()
    if not stale:
        if not quiet:
            print("没有半成品(历史对话层有的都有概述)")
        return {"对话": 0, "概述": 0, "知识": 0, "别名": 0}

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 回填 {len(stale)} 个半成品:")
    total = {"对话": 0, "概述": 0, "知识": 0, "别名": 0}
    for source, pieces in stale.items():
        material = history_raw(source)
        if not material.strip():
            print(f"    {source}: 历史对话层也没有原文, 跳过")
            continue
        print(f"    {source}  ({pieces} 片)")
        try:
            result = clean_one(source, material)
        except Exception as error:  # noqa: BLE001 —— 一个失败不该带崩整轮
            print(f"        ✘ 失败: {error}", file=sys.stderr)
            continue
        for key in ("概述", "知识", "别名"):
            total[key] += result[key]
        print(f"        概述 {result['概述']} / 知识 {result['知识']} / 别名 {result['别名']}")
    print(
        f"\n回填完成: 概述 {total['概述']} 条 / 知识 {total['知识']} 条 / 别名 {total['别名']} 组"
    )
    return total


# ---------------- 主流程 ----------------


def run_once(quiet: bool = False) -> dict[str, int]:
    """清一次: 复制 -> 清洗 -> 清空二层。

    ★ 时间戳: 日志是 cron 追加的, 原来一行时间都没有、对不上账 —— 每轮开头打一个。
    ★ 待重洗: ② 读不到原文先拿三层原文回填; 两边都没有才记账, 不当"洗过了"。
    """
    started = time.time()
    groups = tier2_groups()
    if not groups:
        if not quiet:
            print("二层是空的, 没什么可清")
        write_heartbeat(0, len(load_pending()))
        return {"对话": 0, "概述": 0, "知识": 0, "别名": 0}

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 要清 {len(groups)} 次问答:")
    for source in groups:
        print(f"    {source}  ({len(groups[source])} 片)")
    if 远端端点 or 并发度 > 1 or 文件并发度 > 1:
        哪 = 远端端点 or ("127.0.0.1:8790(本地)" if 本地模式 else "(.env 里那个端点)")
        print(f"    [模型] {哪} · 并发 {并发度} · 文件并发 {文件并发度}")

    total = {"对话": 0, "概述": 0, "知识": 0, "别名": 0}

    print("\n① 先复制 —— 二层切片原样搬进历史对话层(带时间线, 永久留)")
    total["对话"] = copy_to_history(groups)
    print(f"    原文 {total['对话']} 片已进历史对话层(tier=1 kind='对话')")

    print("\n② 再清洗 —— 概述 / 知识 / 别名")
    pending = load_pending()
    washed: set[str] = set()          # ② 真洗成了的 —— ③ 只清这些
    failed = 0
    停信号: list[str] = []            # 一旦有值 = 全线停(模型不答): 不再起新文件, 绝不进 ③
    if 文件并发度 > 1:
        print(f"    [文件并发] {文件并发度} 个文件同时在飞"
              f"(单个文件只发 3×段数 条请求, 池子开再大也填不满; 多文件才填得满)")

        def 干一个(source: str) -> tuple[str, dict[str, int] | None, str, str]:
            """扫/洗一个文件。★ 不在这里打印 —— 打印一律回主线程做, 打印锁与索引锁交叉会死锁。"""
            try:
                material, origin = read_material(source)
            except Exception as error:  # noqa: BLE001 —— 一个文件不该带崩整条管线
                return source, None, "失败", f"读原文失败: {error}"
            if not material.strip():
                return source, None, "缺原文", ""
            tag = "" if origin == "语料文件" else f"  [从{origin}清洗]"
            try:
                return source, clean_one(source, material), "好", tag
            except 全线停 as error:
                return source, None, "全线停", str(error)
            except Exception as error:  # noqa: BLE001
                return source, None, "失败", f"{type(error).__name__}: {error}"

        def 记一个(件: tuple[str, dict[str, int] | None, str, str]) -> None:
            """收一个文件的结果 —— 账(待重洗/洗成/合计)只在主线程动, 并发改同一个 dict 会丢。"""
            nonlocal failed
            source, result, 情况, 说明 = 件
            if 情况 == "缺原文":
                known: dict[str, Any] = pending.get(source) or {}
                pending[source] = {
                    "片数": len(groups[source]),
                    "首次发现": str(known.get("首次发现") or time.strftime("%Y-%m-%d %H:%M:%S")),
                    "最近发现": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "原因": "语料文件没了, 三层也没有这一批的原文",
                }
                print(f"    {source}: 语料文件没了、三层也没原文 → 记进待重洗(当没洗过)")
                return
            if 情况 == "全线停":
                print(f"    {source}", file=sys.stderr)
                print(f"        ⛔ 全线停: {说明}", file=sys.stderr)
                停信号.append(说明)
                return
            if 情况 == "失败":
                print(f"    {source}", file=sys.stderr)
                print(f"        ✘ 失败: {说明}", file=sys.stderr)
                failed += 1
                return
            assert result is not None
            pending.pop(source, None)  # ★ 洗成了就从待重洗里划掉
            washed.add(source)
            for key in ("概述", "知识", "别名"):
                total[key] += result[key]
            print(f"    {source}{说明}")
            print(f"        概述 {result['概述']} / 知识 {result['知识']} / 别名 {result['别名']}")

        with ThreadPoolExecutor(max_workers=文件并发度) as 池:
            在飞 = {池.submit(干一个, source): source for source in groups}
            for 期货 in as_completed(在飞):
                件 = 期货.result()
                with 输出锁:      # 一个文件的两三行别跟别的文件交错
                    记一个(件)
                if 停信号:        # ★ 全线停: 收摊, 剩下的文件不起了
                    for 剩下 in 在飞:
                        剩下.cancel()
                    break
        save_pending(pending)
    else:
        for source in groups:
            material, origin = read_material(source)
            if not material.strip():
                known: dict[str, Any] = pending.get(source) or {}
                pending[source] = {
                    "片数": len(groups[source]),
                    "首次发现": str(known.get("首次发现") or time.strftime("%Y-%m-%d %H:%M:%S")),
                    "最近发现": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "原因": "语料文件没了, 三层也没有这一批的原文",
                }
                print(f"    {source}: 语料文件没了、三层也没原文 → 记进待重洗(当没洗过)")
                continue
            tag = "" if origin == "语料文件" else f"  [从{origin}清洗]"
            print(f"    {source}{tag}")
            try:
                result = clean_one(source, material)
            except 全线停 as error:
                print(f"        ⛔ 全线停: {error}", file=sys.stderr)
                停信号.append(str(error))
                break
            except Exception as error:  # noqa: BLE001 —— 一个问答失败不该带崩整条管线
                print(f"        ✘ 失败: {error}", file=sys.stderr)
                failed += 1
                continue
            pending.pop(source, None)  # ★ 洗成了就从待重洗里划掉
            washed.add(source)
            for key in ("概述", "知识", "别名"):
                total[key] += result[key]
            print(f"        概述 {result['概述']} / 知识 {result['知识']} / 别名 {result['别名']}")
        save_pending(pending)

    if 停信号:
        # ★ 全线停: 模型一直不答 —— 本轮当场停手, 一个字都不写。
        #   绝不能往下走 ③(清二层/删语料原文): 原文一删就再也补不回来。
        #   下一轮(每分钟 cron 那条)自己会重来, 模型修好就接着洗。
        print(f"\n⛔ 全线停 —— {停信号[0]}")
        print(f"   ② 停在第 {len(washed)} 个文件: 空账一条没写, ③ 跳过 —— 二层/三层/语料原样留着")
        print("   模型修好后不用管, 下一轮自己接着洗")
        write_heartbeat(len(groups), len(pending))
        print(f"\n完成(未洗): 原文 {total['对话']} 片(已进历史对话层) · 耗时 {int(time.time() - started)} 秒")
        return total

    if not washed:
        # ★ 一个都没洗成就别动三层和语料 —— 否则等于把热库掏空、零产出,
        #   而且状态还记成"洗过了"(2026-10-08 实测: 模型端点 401 时就是这个下场).
        #   注意**不能** note_refined(), 否则下轮判据说"这批已经清过了"就不重试了。
        print(f"\n③ 跳过清空 —— ② 一个都没洗成({failed} 个失败), 语料和二层原样留着, 下轮重试")
        write_heartbeat(len(groups), len(pending))
        print(f"\n完成: 原文 {total['对话']} 片(已进历史对话层) / ② 失败 {failed} 次"
              f" · 耗时 {int(time.time() - started)} 秒")
        return total

    print("\n③ 清空二层(只清刚清过的这批, 项目语料留着)")
    dropped, removed = clear_tier2(washed)
    print(f"    索引清掉 {dropped} 片, 语料删掉 {removed} 个文件")

    note_refined()
    write_heartbeat(len(groups), len(pending))
    tail_note = f", 待重洗 {len(pending)} 个" if pending else ""
    print(
        f"\n完成: 原文 {total['对话']} 片(历史对话层) / 概述 {total['概述']} 条 / "
        f"知识 {total['知识']} 条 / 别名 {total['别名']} 组{tail_note}"
        f" · 耗时 {int(time.time() - started)} 秒"
    )
    return total


# ---------------- 看守: 任务结束 + 20 分钟无操作 ----------------


def read_activity() -> dict[str, Any]:
    """读主 agent 留下的"这轮任务结束了没有" —— seek skill 的 `任务结束` 键。"""
    if not ACTIVITY_PATH.is_file():
        return {}
    try:
        data = json.loads(ACTIVITY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return cast(dict[str, Any], data) if isinstance(data, dict) else {}


def note_refined() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REFINE_STATE_PATH.write_text(
        json.dumps({"上次清洗": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def last_refined() -> str:
    if not REFINE_STATE_PATH.is_file():
        return ""
    try:
        data = json.loads(REFINE_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(cast(dict[str, Any], data).get("上次清洗", ""))


def should_refine(activity: dict[str, Any]) -> tuple[bool, str]:
    """该不该清 —— 三条判据 + 一条兜底。

    ① 静默够久 (软阈值 idle_seconds, 默认 20 分钟)
    ② 上一轮任务**结束**了, **或者**静默超过硬阈值 (hard_idle_seconds, 默认 2 小时)
       —— 兜底那条管的是"模型判任务没办完、人却再没回来"的情况:
          没这条, 二层会一直积着不清
    ③ 这之后没清过 (少了它, 自动触发就变成每分钟把同一批重新喂模型)
    ④ 二层得真有对话产出

    ★ 少了"② 的结束判据"或"③ 没清过"任一条, 都会白烧算力还越攒越乱。
    """
    if not activity:
        return False, "主 agent 还没留下活动记录"
    last = str(activity.get("时间", ""))
    if not last:
        return False, "活动记录里没有时间"

    config = refine_config()
    soft = int(config["idle_seconds"])
    hard = int(config["hard_idle_seconds"])
    try:
        passed = time.time() - time.mktime(time.strptime(last, "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return False, f"活动记录的时间读不懂: {last}"
    if passed < soft:
        return False, f"才静默 {int(passed)} 秒, 没到 {soft} 秒"

    ended = bool(activity.get("任务结束"))
    if not ended and passed < hard:
        return False, f"任务还没结束, 静默也没到硬阈值 {hard} 秒 (才 {int(passed)} 秒)"

    if not tier2_groups():
        return False, "二层是空的"
    previous = last_refined()
    if previous and previous >= last:
        return False, "这批已经清过了"
    tail = "" if ended else " [兜底: 任务没结束, 但静默过了硬阈值]"
    return True, f"静默 {int(passed)} 秒{tail} —— 该清了"


def watch(interval: int, quiet: bool) -> None:
    """常驻看守: 每 interval 秒看一次, 到点自己跑清洗。"""
    config = refine_config()
    idle = int(config["idle_seconds"])
    hard = int(config["hard_idle_seconds"])
    print(f"[看守] 每 {interval} 秒看一次", flush=True)
    print(f"[看守] 判据: 静默 ≥ {idle} 秒 且 (任务结束=true 或 静默 ≥ {hard} 秒)",
          flush=True)
    print("[看守] 停下按 Ctrl-C", flush=True)
    while True:
        try:
            activity = read_activity()
            ready, why = should_refine(activity)
            if ready:
                print(f"\n[看守] {time.strftime('%H:%M:%S')} {why}", flush=True)
                run_once(quiet=quiet)
            elif not quiet:
                print(f"[看守] {time.strftime('%H:%M:%S')} 不动: {why}", flush=True)
        except KeyboardInterrupt:
            print("\n[看守] 停了", flush=True)
            return
        except Exception as error:  # noqa: BLE001 —— 看守不能因为一次失手就死
            print(f"[看守] 出错: {error}", file=sys.stderr)
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="清洗管线: 二层(热) -> 三层(冷)")
    parser.add_argument("--看守", action="store_true", help="常驻, 到点自己清")
    parser.add_argument("--干跑", action="store_true", help="只列要清什么, 不动库")
    parser.add_argument("--安静", action="store_true", help="没活干不出声")
    parser.add_argument("--待重洗", action="store_true", help="列出洗不了的账(语料文件没了、三层也没原文)")
    parser.add_argument("--回填", action="store_true", help="把三层里的半成品(有原文没概述)补洗一遍")
    parser.add_argument("--间隔", type=int, default=0, help="看守多久看一次 (默认取配置)")
    parser.add_argument("--强制", action="store_true",
                          help="不看静默判据, 立刻清(手动补洗/调试用)")
    parser.add_argument("--忽略停机闸门", action="store_true",
                          help="停机状态(state/停机 在)也照样跑 —— 只有手动补洗才用得上")
    parser.add_argument("--本地", action="store_true",
                          help="钉死本机模型(127.0.0.1:8790), 不看 .env —— 清洗是长跑批处理, 走云在烧钱")
    parser.add_argument("--端点", default="",
                          help="模型端点(必须带 /v1, 如 https://<实例ID>.zzai.scnet.cn:58043/v1), "
                               "优先于 --本地 与 .env")
    parser.add_argument("--密钥", default="", help="配合 --端点 的 API Key (端点不要就留空)")
    parser.add_argument("--模型", default="", help="配合 --端点 的模型名 (默认取 .env 的 OPENAI_MODEL)")
    parser.add_argument("--并发", type=int, default=1,
                          help="同时在飞的模型请求数 (默认 1 = 老行为逐段串行; 清洗是预填主导, 并发才是收益来源)")
    parser.add_argument("--并发文件", type=int, default=1,
                          help="同时在飞的**文件**数 (默认 1 = 老行为一个文件一个文件走)。"
                               "★ 单个文件只发 3×段数 条请求, 光调 --并发 填不满卡: "
                               "实测 --并发 16 时在飞只有 2~3 条(batch 1 = 21 tok/s, batch 16 = 153 tok/s), "
                               "要不要多文件同时走来把 batch 填起来, 是这个开关。")
    args = parser.parse_args()

    global 本地模式, 远端端点, 远端密钥, 远端模型, 并发度, 文件并发度
    本地模式 = bool(args.本地)
    远端端点 = str(args.端点)
    远端密钥 = str(args.密钥)
    远端模型 = str(args.模型)
    并发度 = max(1, int(args.并发))
    文件并发度 = max(1, int(args.并发文件))

    # cron 把 stdout 重定向到文件时是**全缓冲**: 输出要等进程退出才落盘,
    # 日志里就看不到实时进度(实测: 跑完 3 分钟, 期间日志 0 字节)。
    # 改成行缓冲 —— 每打完一行就落盘。
    for stream in (sys.stdout, sys.stderr):
        try:
            cast(Any, stream).reconfigure(line_buffering=True)
        except (AttributeError, ValueError):
            pass  # 不是文本流(被别的东西替换过)就算了, 不影响干活

    config = refine_config()
    interval = int(args.间隔) or int(config["watch_interval"])

    # ★ 停机闸门: web 上「关模型/全部」会落一个 state/停机 —— 机器都停机了, 清洗没有模型可问,
    #   不要让 cron 每分钟把它叫起来空转(8 次退避重试 → 全线停 → 下一分钟再来, 空耗 CPU)。
    #   开机走「以本地模型启动」会自己把闸门撤掉; 想强制跑就带 --忽略停机闸门。
    #   --干跑 / --待重洗 是只看不干的活, 不受闸门拦。
    if not (args.干跑 or args.待重洗) and not args.忽略停机闸门 and (STATE_DIR / "停机").exists():
        print("⏸ 停机闸门在(state/停机) —— 机器停机中, 这轮不起。开机/以本地模型启动会自动撤掉。")
        return

    if bool(args.看守):
        watch(interval, bool(args.安静))
        return

    if bool(args.回填):
        backfill(quiet=bool(args.安静))
        return

    if bool(args.待重洗):
        pending = load_pending()
        if not pending:
            print("待重洗是空的")
            return
        print(f"待重洗 {len(pending)} 个(洗不了, 等语料回来或人工处理):")
        for source, info in pending.items():
            print(f"    {source}  ({info.get('片数', '?')} 片 · 首次 {info.get('首次发现', '?')})")
        return

    groups = tier2_groups()
    if bool(args.干跑):
        if not groups:
            print("二层是空的, 没什么可清")
            return
        total2 = len(cast(list[Any], load_index(TIER2_PATH).get("items") or []))
        print(f"二层共 {total2} 片, 其中对话产出 {sum(len(v) for v in groups.values())} 片 —— "
              f"要清 {len(groups)} 次问答 (--干跑, 到此为止):")
        for source, entries in groups.items():
            print(f"    {source}  ({len(entries)} 片)")
        return

    # ★ 这道门以前只在 --看守 里有, 而 cron 走的是这条**非看守**路径(每分钟一次):
    #   于是刚入二层的对话产出最长活 60 秒就被搬进三层、语料删掉 ——
    #   多轮对话只在隔一分钟就"想不起来上一轮说了什么"(2026-10-07 实测复现)。
    #   现在两条路都守同一道闸; 真要立刻清就显式 --强制。
    if not bool(args.强制):
        ready, why = should_refine(read_activity())
        if not ready:
            if not bool(args.安静):
                print(f"[看守] 不动: {why}")
            return
    run_once(quiet=bool(args.安静))


if __name__ == "__main__":
    main()

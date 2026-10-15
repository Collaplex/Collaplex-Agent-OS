#!/usr/bin/env python3
"""切片转向量: 切片列表 -> 向量模型 -> JSON 文件.

表结构: 索引 / 向量 / 原文 / 哈希
模型调用信息统一读 .env (EMBEDDING_BASE_URL / EMBEDDING_MODEL).

跑法:
    .venv/bin/python skill/rag/scripts/embed.py skill/seek/SKILL.md
    .venv/bin/python skill/rag/scripts/embed.py 语料目录/
前提: 向量服务起着 (scripts/embed_server.sh start)
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, cast

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent      # skill/rag/scripts
SKILL_DIR = HERE.parent                      # skill/rag
ROOT = SKILL_DIR.parent.parent               # 项目根 (放 .env)
sys.path.insert(0, str(HERE))

import store  # noqa: E402  (同目录模块, 得先补 sys.path)
from chunker import split_file, split_file_semantic  # noqa: E402

CONFIG_PATH = SKILL_DIR / "resources" / "embed.json"
ENV_PATH = ROOT / ".env"

# 本机 http_proxy 会拦 127.0.0.1, 显式清空代理
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

load_dotenv(ENV_PATH)


# ============================================================
# 配置
# ============================================================

def load_config(config_path: Path) -> dict[str, Any]:
    """读配置 JSON."""
    if not config_path.is_file():
        raise FileNotFoundError(f"配置不存在: {config_path}")
    with open(config_path, "r", encoding="utf-8") as fp:
        config: dict[str, Any] = json.load(fp)
    if not config:
        raise ValueError(f"配置是空的: {config_path}")
    return config


def resolve_model() -> dict[str, str]:
    """模型调用信息统一从 .env 取."""
    base_url = (os.getenv("EMBEDDING_BASE_URL") or "").rstrip("/")
    model = os.getenv("EMBEDDING_MODEL") or ""
    if not base_url or not model:
        raise RuntimeError(f".env 缺 EMBEDDING_BASE_URL 或 EMBEDDING_MODEL: {ENV_PATH}")
    return {"endpoint": f"{base_url}/embeddings", "model": model}


# ============================================================
# 切片
# ============================================================

def collect_files(inputs: list[str], config: dict[str, Any]) -> list[str]:
    """展开文件列表. 格式不在白名单里怎么办, 由 on_unsupported 决定 (refuse=整批拒绝 / skip=只跳过它)."""
    exclude_dirs = {str(name) for name in config.get("exclude_dirs", [])}
    exclude_files = {str(name) for name in config.get("exclude_files", [])}
    allowed = {str(name).lower() for name in config.get("allowed_exts", [])}
    on_unsupported = str(config.get("on_unsupported", "refuse")).lower()
    if not allowed:
        raise ValueError("配置缺 allowed_exts, 无法做格式验证")

    files: list[str] = []
    rejected: list[str] = []

    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            candidates = [
                candidate
                for candidate in sorted(path.rglob("*"))
                if candidate.is_file()
                and not candidate.name.startswith(".")
                and candidate.name not in exclude_files
                and not any(part in exclude_dirs for part in candidate.parts)
            ]
        elif path.is_file():
            candidates = [] if path.name in exclude_files else [path]
        else:
            print(f"[跳过] 路径不存在: {raw}")
            continue

        for candidate in candidates:
            if candidate.suffix.lower() in allowed:
                files.append(str(candidate))
            else:
                rejected.append(str(candidate))

    if rejected:
        print(f"[不支持] {len(rejected)} 个文件的格式不在支持清单:")
        for name in rejected[:20]:
            print(f"  {name}")
        if len(rejected) > 20:
            print(f"  ... 另有 {len(rejected) - 20} 个")
        if on_unsupported == "skip":
            print("[跳过] on_unsupported=skip, 只处理支持格式的文件")
        else:
            print(f"[支持格式] {' '.join(sorted(allowed))}")
            raise SystemExit(2)

    return files


def text_hash(text: str) -> str:
    """切片级哈希, 用于去重与增量."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def rel_source(file_path: str) -> str:
    """源文件相对项目根的路径; 不在项目里就存绝对路径."""
    resolved = Path(file_path).resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def split_one(
    file_path: str,
    chunk_size: int,
    semantic: dict[str, Any] | None,
    embed_fn: Callable[[list[str]], list[list[float]]] | None,
) -> list[tuple[str, list[float] | None]]:
    """切一个文件: 语义开着且给了嵌入器就走语义, 否则走规则。"""
    if semantic is not None and embed_fn is not None:
        return split_file_semantic(
            file_path,
            chunk_size,
            embed_fn,
            cut_threshold=float(semantic["cut_threshold"]),
            cut_zscore=float(semantic.get("cut_zscore", 0.8)),
            min_ratio=float(semantic["min_chunk_ratio"]),
            max_ratio=float(semantic["max_chunk_ratio"]),
            min_text_chars=int(semantic["min_text_chars"]),
        )
    return [(chunk, None) for chunk in split_file(file_path, chunk_size)]


def build_chunks(
    files: list[str],
    chunk_size: int,
    semantic: dict[str, Any] | None = None,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    digits: int = 6,
) -> list[dict[str, Any]]:
    """切片, 每块记下它出自哪个文件。语义切片会调嵌入器算单元向量(有网络)。"""
    items: list[dict[str, Any]] = []
    carried = 0
    for file_path in files:
        try:
            pieces = split_one(file_path, chunk_size, semantic, embed_fn)
        except (OSError, ValueError) as exc:
            print(f"[跳过] 切片失败 {file_path}: {exc}")
            continue
        source = rel_source(file_path)
        for text, vector in pieces:
            item: dict[str, Any] = {
                "index": len(items),
                "text": text,
                "hash": text_hash(text),
                "source": source,
            }
            if vector is not None:
                # 单单元块: 语义切片时已经算过它这条向量, 上层不要再算一遍
                item["vector"] = [round(value, digits) for value in vector]
                carried += 1
            items.append(item)
    if carried:
        print(f"[语义] 单元向量直接复用 {carried} 块 (单句成块)")
    return items


# ============================================================
# 向量
# ============================================================

def request_vectors(
    texts: list[str],
    config: dict[str, Any],
    model_info: dict[str, str],
) -> list[list[float]]:
    """调一次向量接口, 带重试. 返回顺序与输入一一对应."""
    payload = json.dumps(
        {"input": texts, "model": model_info["model"]},
        ensure_ascii=False,
    ).encode("utf-8")
    retry = int(config["retry"])
    last_error = ""

    for attempt in range(1, retry + 1):
        request = urllib.request.Request(
            model_info["endpoint"],
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with OPENER.open(request, timeout=float(config["timeout"])) as response:
                body = json.loads(response.read().decode("utf-8"))
            rows = sorted(body["data"], key=_row_index)
            return [[float(value) for value in row["embedding"]] for row in rows]
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retry:
                wait = 2 ** attempt
                print(f"[重试] 第 {attempt} 次失败 ({last_error}), {wait}s 后再来", flush=True)
                time.sleep(wait)

    raise RuntimeError(f"向量接口连续 {retry} 次失败: {last_error}")


def _row_index(row: dict[str, Any]) -> int:
    """接口返回的排序键."""
    return int(row["index"])


EMBED_MAX_CHARS = 4000  # ★ 服务端 -c 8192 是 token 数, 中文 1 字 ≈ 1.5 token
# 老值 11000 按 -c/1(一个字符一个 token)算的, 实际是 1.6 万 token -> 直接被 500 打回
# (实测 2026-10-08: 跑到 11% 时 4 个超长块把嵌入服务打挂, 整批重来)
# 4000 字 ≈ 6000 token, 对 8192 窗口留了 1/4 余量; 正常块是 chunk_size=800, 碰不到这个上限


def _clip_text(text: str) -> str:
    """单块超嵌入窗口会被服务端 400 打回(整批崩), 这里截断并记日志。"""
    if len(text) <= EMBED_MAX_CHARS:
        return text
    print(f"[截断] 单块 {len(text)} 字符 > 上限 {EMBED_MAX_CHARS}, 截断后送", flush=True)
    return text[:EMBED_MAX_CHARS]


def embed_items(
    items: list[dict[str, Any]],
    config: dict[str, Any],
    reused: dict[str, list[float]],
    model_info: dict[str, str],
) -> None:
    """给切片补上 vector 字段, 原地修改. 命中 reused 或已带向量的都不打模型."""
    batch_size = int(config["batch_size"])
    digits = int(config["vector_digits"])

    # ★ 已带 vector 的(语义切片单句成块)不要再算一遍 —— 早先只按 reused 过滤, 会白执行一次
    pending = [
        item for item in items
        if item["hash"] not in reused and item.get("vector") is None
    ]
    print(f"[增量] 复用 {len(items) - len(pending)} 块, 待算 {len(pending)} 块")

    total = len(pending)
    started = time.perf_counter()
    done = 0

    for start in range(0, total, batch_size):
        batch = pending[start:start + batch_size]
        vectors = request_vectors([_clip_text(str(item["text"])) for item in batch], config, model_info)
        if len(vectors) != len(batch):
            raise RuntimeError(f"返回向量数 {len(vectors)} 与请求数 {len(batch)} 不一致")
        for item, vector in zip(batch, vectors):
            item["vector"] = [round(value, digits) for value in vector]
        done += len(batch)
        elapsed = time.perf_counter() - started
        speed = done / elapsed if elapsed > 0 else 0.0
        print(f"[向量] {done}/{total}  用时 {elapsed:.1f}s  速度 {speed:.1f} 块/s", flush=True)

    for item in items:
        if "vector" not in item:
            cached = reused.get(str(item["hash"]))
            if cached is not None:
                item["vector"] = cached


# ============================================================
# 存取
# ============================================================

def load_existing(output_path: Path) -> list[dict[str, Any]]:
    """读回旧索引条目, 用于增量复用与累积."""
    if not output_path.is_file():
        return []
    try:
        with open(output_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (json.JSONDecodeError, OSError):
        print(f"[增量] 旧文件读不了, 按全量处理: {output_path}")
        return []

    existing: list[dict[str, Any]] = []
    for item in data.get("items", []):
        chunk_hash = item.get("hash")
        vector = item.get("vector")
        if isinstance(chunk_hash, str) and isinstance(vector, list):
            existing.append({
                "index": item.get("index", 0),
                "vector": vector,
                "text": item.get("text", ""),
                "hash": chunk_hash,
                "source": item.get("source", ""),
            })
    return existing


def export_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只保留表结构的五个字段, 顺序即表顺序."""
    export: list[dict[str, Any]] = []
    for item in items:
        vector = item.get("vector")
        if vector is None:
            print(f"[警告] 第 {item['index']} 块没有向量, 跳过")
            continue
        export.append({
            "index": item["index"],
            "vector": vector,
            "text": item["text"],
            "hash": item["hash"],
            "source": item.get("source", ""),
        })
    return export


def save_index(data: dict[str, Any], output_path: Path) -> None:
    """先写临时文件再改名, 避免半截 JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(output_path.name + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False)
    temp_path.replace(output_path)


# ============================================================
# 主流程
# ============================================================

def resolve_tier(config: dict[str, Any], tier: str) -> tuple[str, Path]:
    """层号 -> (层名, 索引路径). 层定义在 resources/embed.json 的 tiers 段."""
    tiers = config.get("tiers")
    if not isinstance(tiers, dict):
        raise ValueError(f"配置缺 tiers 段: {CONFIG_PATH}")
    table = cast(dict[str, Any], tiers)
    entry = table.get(tier)
    if not isinstance(entry, dict):
        raise ValueError(f"配置里没有这一层: {tier}  (可选 {sorted(table)})")
    row = cast(dict[str, Any], entry)
    return str(row.get("name", tier)), SKILL_DIR / str(row["output"])


def run(inputs: list[str], config: dict[str, Any], tier: str, force_rule: bool = False) -> None:
    model_info = resolve_model()
    chunk_size = int(config["chunk_size"])
    tier_name, output_path = resolve_tier(config, tier)
    print(f"[层] {tier} {tier_name}")

    print(f"[模型] {model_info['model']} @ {model_info['endpoint']}")
    files = collect_files(inputs, config)
    if not files:
        print("[错误] 没有可处理的文件")
        return

    print(f"[切片] 文件 {len(files)} 个, 目标块大小 {chunk_size} 字")
    semantic = config.get("semantic")
    semantic_cfg = cast(dict[str, Any], semantic) if isinstance(semantic, dict) else None
    if force_rule or semantic_cfg is None or not bool(semantic_cfg.get("enabled")):
        semantic_cfg = None

    def embed_units(texts: list[str]) -> list[list[float]]:
        """给语义切片算单元向量; 按 batch_size 分批, 以免一次推太大。"""
        step = int(config["batch_size"])
        vectors: list[list[float]] = []
        for start in range(0, len(texts), step):
            part = texts[start:start + step]
            vectors.extend(request_vectors([_clip_text(text) for text in part], config, model_info))
        return vectors

    if semantic_cfg is not None:
        print(f"[切片] 语义模式 (切点阈值 {semantic_cfg['cut_threshold']}, "
              f"短于 {semantic_cfg['min_text_chars']} 字的文件仍走规则)")
    items = build_chunks(
        files,
        chunk_size,
        semantic_cfg,
        embed_units if semantic_cfg is not None else None,
        int(config["vector_digits"]),
    )
    print(f"[切片] 共 {len(items)} 块")

    use_pg = store.is_pg(config)
    conn = store.connect(config) if use_pg else None

    if use_pg and conn is not None:
        existing = store.load_existing(conn, config, tier)
    else:
        existing = load_existing(output_path)
    reused = {str(item["hash"]): item["vector"] for item in existing}
    embed_items(items, config, reused, model_info)
    fresh = export_items(items)

    mode = str(config.get("mode", "accumulate"))
    dropped = 0
    if mode == "replace":
        merged = fresh
    else:
        # 本次碰过的源文件, 旧切片整批换掉 (文件改了/删了都不留残片)
        touched = {str(item.get("source", "")) for item in fresh}
        kept = [item for item in existing if str(item.get("source", "")) not in touched]
        merged = fresh + kept
        dropped = len(existing) - len(kept)
    merged = [dict(item, index=position) for position, item in enumerate(merged)]
    if mode != "replace":
        note = f", 清掉旧切片 {dropped} 条" if dropped else ""
        print(f"[累积] 旧索引 {len(existing)} 条, 本次 {len(fresh)} 条{note}, 合并后 {len(merged)} 条")

    dimension = len(merged[0]["vector"]) if merged else 0

    if use_pg and conn is not None:
        store.ensure_schema(conn, config, dimension)
        written = store.upsert(conn, config, tier, merged)
        print(f"[落库] PG {store.table_name(config)} tier={tier}, 写入 {written} 条")
        print(f"[完成] {written} 条, {dimension} 维")
        conn.close()
    else:
        result = {
            "meta": {
                "model": model_info["model"],
                "endpoint": model_info["endpoint"],
                "dimension": dimension,
                "count": len(merged),
                "chunk_size": chunk_size,
                "mode": mode,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
            "items": merged,
        }
        save_index(result, output_path)
        print(f"[落盘] {output_path}")
        print(f"[完成] {len(merged)} 条, {dimension} 维")

    for item in merged[:2]:
        head = str(item["text"]).replace("\n", " ")[:60]
        print(f"  #{item['index']} {head}...")


def main() -> None:
    parser = argparse.ArgumentParser(description="切片转向量, 落 JSON 索引")
    parser.add_argument("inputs", nargs="+", help="要处理的文件或目录")
    parser.add_argument("--tier", choices=("2", "3"), default=None,
                        help="写哪一层 (2=热 RAG 原始未清洗, 3=冷 RAG 完整记忆与知识)")
    parser.add_argument("--规则切片", action="store_true",
                        help="这次不用语义切片, 强制走规则 (做对照实验用)")
    args = parser.parse_args()

    config = load_config(CONFIG_PATH)
    tier = args.tier or str(config.get("tier", "2"))
    run(args.inputs, config, tier, force_rule=bool(args.规则切片))


if __name__ == "__main__":
    main()

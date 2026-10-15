#!/usr/bin/env python3
"""skill 检索的共用底座: 配置 / 模型调用 / 向量 / 余弦 / 读写索引.

模型调用信息统一读项目根的 .env (EMBEDDING_BASE_URL / EMBEDDING_MODEL),
跟 rag skill 用的是同一个向量服务.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv
from numpy.typing import NDArray

FloatMatrix = NDArray[np.float32]

HERE = Path(__file__).resolve().parent      # skill/skill_search/scripts
SKILL_DIR = HERE.parent                      # skill/skill_search
ROOT = SKILL_DIR.parent.parent               # 项目根 (放 .env)

CONFIG_PATH = SKILL_DIR / "resources" / "skill_index.json"
ENV_PATH = ROOT / ".env"

# 本机 http_proxy 会拦 127.0.0.1, 显式清空代理
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
load_dotenv(ENV_PATH)


# ============================================================
# 配置与路径
# ============================================================

def load_config(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """读配置 JSON."""
    if not config_path.is_file():
        raise FileNotFoundError(f"配置不存在: {config_path}")
    with open(config_path, "r", encoding="utf-8") as fp:
        config: dict[str, Any] = json.load(fp)
    if not config:
        raise ValueError(f"配置是空的: {config_path}")
    return config


def skill_root(config: dict[str, Any]) -> Path:
    """语料来源: skill 目录. 配置留空就取本项目 skill/ (即本 skill 的上一级)."""
    raw = str(config.get("skill_root") or "").strip()
    return (ROOT / raw) if raw else SKILL_DIR.parent


def index_path(config: dict[str, Any]) -> Path:
    """库文件路径 (相对本 skill 目录)."""
    return SKILL_DIR / str(config["index"])


def resolve_model() -> dict[str, str]:
    """模型调用信息统一从 .env 取."""
    base_url = (os.getenv("EMBEDDING_BASE_URL") or "").rstrip("/")
    model = os.getenv("EMBEDDING_MODEL") or ""
    if not base_url or not model:
        raise RuntimeError(f".env 缺 EMBEDDING_BASE_URL 或 EMBEDDING_MODEL: {ENV_PATH}")
    return {"endpoint": f"{base_url}/embeddings", "model": model}


def rel_source(path: Path) -> str:
    """源目录相对项目根的路径; 不在项目里就存绝对路径."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


# ============================================================
# 向量
# ============================================================

def text_hash(text: str) -> str:
    """切片文本 sha256 前 16 位."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


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


def embed_texts(
    texts: list[str],
    config: dict[str, Any],
    model_info: dict[str, str],
) -> list[list[float]]:
    """一批文本 -> 向量, 按 vector_digits 收敛小数位."""
    digits = int(config["vector_digits"])
    vectors = request_vectors(texts, config, model_info)
    if len(vectors) != len(texts):
        raise RuntimeError(f"返回向量数 {len(vectors)} 与请求数 {len(texts)} 不一致")
    return [[round(value, digits) for value in vector] for vector in vectors]


# ============================================================
# 索引读写
# ============================================================

def load_items(path: Path) -> list[dict[str, Any]]:
    """读回索引条目; 读不了就当空."""
    if not path.is_file():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (json.JSONDecodeError, OSError):
        print(f"[索引] 旧文件读不了, 按空处理: {path}")
        return []

    items: list[dict[str, Any]] = []
    for item in data.get("items", []):
        if isinstance(item.get("vector"), list):
            items.append({
                "index": item.get("index", 0),
                "vector": item["vector"],
                "text": item.get("text", ""),
                "hash": item.get("hash", ""),
                "source": item.get("source", ""),
            })
    return items


def write_items(
    path: Path,
    items: list[dict[str, Any]],
    model: str,
    endpoint: str,
) -> None:
    """落盘. meta 记下模型和条数, 便于日后判断要不要重建."""
    path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "meta": {
            "kind": "skill-index",
            "model": model,
            "endpoint": endpoint,
            "dimension": len(items[0]["vector"]) if items else 0,
            "count": len(items),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
        "items": [
            dict(item, index=position) for position, item in enumerate(items)
        ],
    }
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False)


def to_matrix(items: list[dict[str, Any]]) -> FloatMatrix:
    """条目列表 -> 归一化后的矩阵 (每行一个向量)."""
    matrix = np.asarray([item["vector"] for item in items], dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def cosine(
    query_vector: list[float],
    matrix: FloatMatrix,
    items: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """余弦排序, 返回源数据 (刻意不带 vector 字段)."""
    query = np.asarray(query_vector, dtype=np.float32)
    if query.shape[0] != matrix.shape[1]:
        raise ValueError(
            f"查询向量 {query.shape[0]} 维与索引 {matrix.shape[1]} 维不一致 (模型换过了?)"
        )
    norm = float(np.linalg.norm(query))
    if norm > 0:
        query = query / norm

    scores = matrix @ query
    order = np.argsort(-scores)[: max(top_k, 0)]

    results: list[dict[str, Any]] = []
    for rank, position in enumerate(order, 1):
        item = items[int(position)]
        results.append({
            "rank": rank,
            "score": round(float(scores[int(position)]), 6),
            "index": item.get("index"),
            "source": item.get("source", ""),
            "text": item.get("text", ""),
        })
    return results

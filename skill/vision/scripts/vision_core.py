#!/usr/bin/env python3
"""看图的公共件: 读配置 / 读 .env / 查图 / 发那一次请求.

约定 (定调, 不是参数):
    图只在**那一次请求**里出现 (base64 进请求体), 回来的是文字 —— 图不存、不落第二份、不进会话历史.
    谁先谁后(主路云端 → 兜底本地)由 see.py 定; 这里只负责"发一次, 成没成如实说".
"""

from __future__ import annotations

import base64
import json
import os
import struct
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent      # skill/vision/scripts
SKILL_DIR = HERE.parent                     # skill/vision
ROOT = SKILL_DIR.parent.parent              # 项目根 (放 .env 与 .venv)
CONFIG_PATH = SKILL_DIR / "resources" / "vision.json"

# 后缀 → MIME (视觉模型按 data URL 里的这个认)
SUFFIX_MIME: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def tiny_png() -> bytes:
    """现造一张 1x1 的 PNG (纯标准库, 不依赖 PIL).

    只为试"这条路能不能读图": 送一张最小的合法图, 看它认不认"图"这个输入.
    (放这里而不是放 status.py —— status 这个名字跟别家 skill 的重名, 测试没法 import 它.)
    """
    def 块(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)   # 1x1 / 8bit / 真彩
    原数据 = b"\x00" + b"\xff\x00\x00"                     # 一行, 滤波 0, 一个红像素
    return (b"\x89PNG\r\n\x1a\n" + 块(b"IHDR", ihdr)
            + 块(b"IDAT", zlib.compress(原数据)) + 块(b"IEND", b""))


def as_dict(value: Any) -> dict[str, Any]:
    """不是 dict 就当空 dict —— 外面回来的 JSON 什么都不保证."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    """不是 list 就当空 list."""
    return cast(list[Any], value) if isinstance(value, list) else []


def load_config() -> dict[str, Any]:
    """读 resources/vision.json —— 参数全在那儿, 代码里不硬编码."""
    try:
        raw: Any = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"读不到配置: {CONFIG_PATH} ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"配置不是合法 JSON: {CONFIG_PATH} ({exc})") from exc
    return as_dict(raw)


def env_sources(config: dict[str, Any], section: str) -> list[str]:
    """某一节声明的 .env 来源 (按顺序找, 先命中先用)."""
    section_dict = as_dict(config.get(section))
    listed = as_list(section_dict.get("env来源"))
    return [str(item) for item in listed]


def read_env(key: str, sources: list[str]) -> str:
    """先看环境变量, 再按顺序翻 .env 文件. 找不到返回空串 (调用方自己说人话)."""
    direct = os.environ.get(key, "").strip()
    if direct:
        return direct
    for source in sources:
        path = Path(source).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            name, _, value = text.partition("=")
            if name.strip() == key:
                return value.strip().strip("'\"")
    return ""


def image_limits_of(config: dict[str, Any]) -> tuple[float, list[str]]:
    """(单图上限 MB, 允许的后缀)."""
    section = as_dict(config.get("图片"))
    try:
        max_mb = float(section.get("最大MB", 8))
    except (TypeError, ValueError):
        max_mb = 8.0
    suffixes = [str(item).lower() for item in as_list(section.get("允许后缀"))]
    return max_mb, suffixes or sorted(SUFFIX_MIME)


def call_config_of(config: dict[str, Any]) -> tuple[int, float, float]:
    """(max_tokens, 温度, 超时秒)."""
    section = as_dict(config.get("调用"))
    try:
        max_tokens = int(section.get("max_tokens", 1024))
    except (TypeError, ValueError):
        max_tokens = 1024
    try:
        temperature = float(section.get("温度", 0.1))
    except (TypeError, ValueError):
        temperature = 0.1
    try:
        timeout = float(section.get("超时_秒", 180))
    except (TypeError, ValueError):
        timeout = 180.0
    return max_tokens, temperature, timeout


def system_prompt_of(config: dict[str, Any]) -> str:
    """看图那一发的系统提示词."""
    return str(config.get("提示词") or "你看图, 只说图里真有的东西。")


def budget(config: dict[str, Any], cost: int = 1, peek: bool = False) -> dict[str, Any]:
    """单轮次数闸: 看一张图算 1 次, 超上限就抛.

    一轮 = 连续动作之间不超过 round_gap_seconds (默认 30 分钟) 的那一段;
    停手超过这个间隔就自动开新一轮. 状态落 cache/budget.json —— 跟 search 的闸同款.
    """
    section = as_dict(config.get("闸"))
    limit = int(section.get("max_per_round", 100))
    gap = float(section.get("round_gap_seconds", 1800))
    path = SKILL_DIR / str(section.get("state", "cache/budget.json"))
    now = time.time()
    state: dict[str, Any] = {}
    if path.exists():
        try:
            loaded: Any = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state = cast(dict[str, Any], loaded)
        except (OSError, ValueError):
            state = {}
    if now - float(state.get("last", 0.0)) > gap:
        state = {"round": int(state.get("round", 0)) + 1, "count": 0, "last": 0.0}
    count = int(state.get("count", 0))
    if peek:
        return {
            "轮次": int(state.get("round", 1)), "已用": count, "上限": limit,
            "剩": max(0, limit - count), "窗口秒": int(gap),
        }
    count += max(1, cost)
    if count > limit:
        raise RuntimeError(
            f"这一轮已经看了 {count - 1} 张图, 到上限 {limit} 就停 —— 这是防钻牛角尖的闸。"
            f" 还想看: 等 {int(gap // 60)} 分钟自动开新一轮, 或调 resources/vision.json 的 闸.max_per_round"
        )
    state["count"] = count
    state["last"] = now
    state["round"] = int(state.get("round", 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"轮次": int(state["round"]), "已用": count, "上限": limit, "剩": limit - count}


def check_image(path_text: str, config: dict[str, Any]) -> tuple[Path, bytes, str]:
    """查图: 在不在 / 后缀认不认 / 超没超上限. 过了就回 (路径, 字节, MIME).

    失败抛 ValueError —— 里面的这句话是给模型看的人话, 直接照说.
    """
    if not path_text.strip():
        raise ValueError("没给图片路径")
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        raise ValueError(f"图片不在: {path}")

    suffix = path.suffix.lower()
    max_mb, allowed = image_limits_of(config)
    if suffix not in allowed:
        raise ValueError(f"这个后缀不认: {suffix or '(没有后缀)'} (认这些: {' '.join(allowed)})")
    mime = SUFFIX_MIME.get(suffix)
    if mime is None:
        raise ValueError(f"这个后缀没有对应的图片类型: {suffix}")

    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"这是个空文件: {path}")
    if size > max_mb * 1024 * 1024:
        raise ValueError(f"图太大了: {size / 1024 / 1024:.1f}MB (上限 {max_mb:g}MB)")

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"读不了这张图: {path} ({exc})") from exc
    return path, raw, mime


def call_vision(
    *,
    base_url: str,
    api_key: str,
    model: str,
    raw: bytes,
    mime: str,
    question: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> dict[str, Any]:
    """发一次视觉请求. 图只在这一发的请求体里活着, 回来的是文字.

    返回 {成功, 文字, 模型, 耗时秒, 错误, 用量}. 拿不到内容一律标失败 —— 绝不静默当成功.
    """
    blank: dict[str, Any] = {
        "成功": False, "文字": "", "模型": model, "耗时秒": 0.0, "错误": "", "用量": {},
    }
    if not base_url:
        return blank | {"错误": "没端点 (base_url 空)"}
    if not model:
        return blank | {"错误": "没模型名"}

    data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key or 'local'}", "Content-Type": "application/json"},
        method="POST",
    )
    # 绕开本机代理: 打的是模型端点, 不要让 127.0.0.1:7897 插手
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.time()
    try:
        with opener.open(request, timeout=timeout) as response:
            body: Any = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:  # noqa: BLE001 - 读不到错误正文也不该盖掉原始错误
            detail = "(读不到错误正文)"
        return blank | {"耗时秒": round(time.time() - started, 1), "错误": f"HTTP {exc.code}: {detail}"}
    except Exception as exc:  # noqa: BLE001 - 网络侧什么都可能, 一律说人话
        return blank | {"耗时秒": round(time.time() - started, 1), "错误": f"{type(exc).__name__}: {exc}"}

    elapsed = round(time.time() - started, 1)
    body_dict = as_dict(body)
    usage = as_dict(body_dict.get("usage"))
    text = ""
    choices = as_list(body_dict.get("choices"))
    if choices:
        message = as_dict(as_dict(choices[0]).get("message"))
        text = str(message.get("content") or "")
    if not text.strip():
        return {
            "成功": False, "文字": "", "模型": model, "耗时秒": elapsed,
            "用量": usage,
            "错误": f"回来了但是空的 (completion_tokens={usage.get('completion_tokens', '?')}, 多半被 token 上限吃光)",
        }
    return {"成功": True, "文字": text.strip(), "模型": model, "耗时秒": elapsed, "错误": "", "用量": usage}

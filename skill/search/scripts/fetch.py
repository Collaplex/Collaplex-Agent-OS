#!/usr/bin/env python3
"""联网取页 —— 给个 URL, 把 HTML 拿回来（带落盘缓存）.

本件只干"取"这一件事, 分工:
    serp.py     结果页 -> 结果列表（标题 / 链接 / 摘要）
    article.py  正文页 -> 正文段落
    pick.py     一堆段落 -> 跟问题最相关的几段

★ 零依赖: 标准库 urllib, 不引 requests / httpx.
★ 不走代理: 本机 http_proxy 指着 Clash(127.0.0.1:7897, 常不在跑), 走它会拿到 502 空 body.
  所以显式 ProxyHandler({}) 绕开 —— 这是已踩坑记录, 不要改回去.
★ 缓存: cache/pages/<url 的 sha1 前 16 位>.html 加同名 .meta.json(取的时间 / 状态 / 最终地址).
  同一个 URL 默认 24 小时内不重打（fetch(..., refresh=True) 或缓存过期才重取）。
★ 单页字节上限(默认 5MB, store.json 的 page_max_mb): 读到这个数就截断 —— 不要让一个超大页
  把内存/磁盘打爆(体积闸的第一道)。单次(一条命令)的上限在 serp.py 那边累加, 是第二道。
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent      # skill/search/scripts
SKILL = HERE.parent                         # skill/search
CACHE = SKILL / "cache" / "pages"           # 页面缓存（不进 git）
STORE_CONFIG = SKILL / "resources" / "store.json"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS: dict[str, str] = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

TIMEOUT = 20                  # 秒
CACHE_TTL = 24 * 3600         # 缓存活多久（秒）
_META_CHARSET = re.compile(rb"""charset=["']?\s*([\w-]+)""", re.I)


def store_mb(key: str, default: float) -> float:
    """从 store.json 读一个以 MB 为单位的数（读不到就按默认）.

    ★ 体积闸的几个档都在 store.json: page_max_mb(单页) / single_max_mb(单次) / disk_max_mb(落盘)。
      fetch 与 serp 共用这一个读法, 免得两处各写一遍还各错一遍。
    """
    mb = default
    try:
        raw = json.loads(STORE_CONFIG.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("store.json 不是对象")
        data = cast(dict[str, Any], raw)
        value = data.get(key, default)
        mb = float(value) if isinstance(value, (int, float, str)) else default
    except (OSError, ValueError):
        mb = default
    return mb


def page_max_bytes() -> int:
    """单页字节上限（默认 5MB）—— 防一个超大页把内存/磁盘打爆(体积闸第一道)."""
    return max(1, int(store_mb("page_max_mb", 5) * 1048576))


@dataclass
class Page:
    """取回来的一页."""

    url: str            # 最终地址（跟完跳转之后）
    html: str
    status: int
    from_cache: bool    # True = 这次读的是缓存, 没打网络


def cache_paths(url: str) -> tuple[Path, Path]:
    """(html 路径, meta 路径)."""
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return CACHE / f"{key}.html", CACHE / f"{key}.meta.json"


def decode_bytes(raw: bytes, content_type: str) -> str:
    """按 响应头 charset -> 正文 meta charset -> utf-8 -> gb18030 的顺序解码."""
    charset = ""
    found = re.search(r"charset=([\w-]+)", content_type, re.I)
    if found is not None:
        charset = found.group(1)
    if not charset:
        in_body = _META_CHARSET.search(raw[:4096])
        if in_body is not None:
            charset = in_body.group(1).decode("ascii", "replace")
    for name in (charset, "utf-8", "gb18030"):
        if not name:
            continue
        try:
            return raw.decode(name)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def read_cache(url: str, ttl: int = CACHE_TTL) -> Page | None:
    """读缓存; 没有 / 过期 / 读坏了都当没有."""
    html_path, meta_path = cache_paths(url)
    try:
        loaded = json.loads(meta_path.read_text("utf-8"))
        if not isinstance(loaded, dict):
            return None
        info = cast(dict[str, Any], loaded)
        if time.time() - float(info.get("taken", 0)) > ttl:
            return None
        html = html_path.read_text("utf-8")
        return Page(
            url=str(info.get("url", url)),
            html=html,
            status=int(info.get("status", 200)),
            from_cache=True,
        )
    except (OSError, ValueError, TypeError):
        return None


def write_cache(url: str, page: Page) -> None:
    """落盘; 写不进去不该让取页失败(缓存是加速件, 不是必需品)."""
    html_path, meta_path = cache_paths(url)
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        html_path.write_text(page.html, "utf-8")
        meta_path.write_text(
            json.dumps({"url": page.url, "status": page.status, "taken": time.time()},
                       ensure_ascii=False),
            "utf-8",
        )
    except OSError:
        pass


def fetch(url: str, refresh: bool = False, ttl: int = CACHE_TTL,
          timeout: int = TIMEOUT) -> Page:
    """取一页: 先看缓存, 没有或过期或 refresh 就真打网络.

    出错一律抛 RuntimeError(带人话原因), 交给上层打印 —— 不静默吞成空页.
    """
    if not refresh:
        cached = read_cache(url, ttl)
        if cached is not None:
            return cached

    cap = page_max_bytes()                    # ★ 单页上限(体积闸第一道)
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with OPENER.open(request, timeout=timeout) as response:
            raw = response.read(cap + 1)      # 多读一个字节, 好知道有没有超
            status = response.status
            final_url = response.geturl()
            encoding = (response.headers.get("Content-Encoding") or "").lower()
            content_type = response.headers.get("Content-Type") or ""
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code}: {url}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"打不开 {url}: {error.reason}") from error
    except TimeoutError as error:
        raise RuntimeError(f"{timeout} 秒没应答: {url}") from error

    if len(raw) > cap:
        raw = raw[:cap]
    if encoding == "gzip":
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError, zlib.error) as error:
            raise RuntimeError(f"响应解压失败(可能超了单页上限): {url}") from error
    elif encoding == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error as error:
            raise RuntimeError(f"响应解压失败(可能超了单页上限): {url}") from error
    if len(raw) > cap:
        raw = raw[:cap]

    page = Page(url=final_url, html=decode_bytes(raw, content_type),
                status=status, from_cache=False)
    write_cache(url, page)
    return page

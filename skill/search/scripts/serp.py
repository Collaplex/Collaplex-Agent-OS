#!/usr/bin/env python3
"""结果页 -> 结构化结果（零 API key）: bing 与百度两路, 可一起打.

★ 为什么走 cn.bing.com: 本机在校网 / GFW 下, google 不通; cn.bing.com 直连实测
  HTTP 200 / 100KB / 0.7s。cn 挂了自动回落 www.bing.com。
★ 每站的取页路不一样, 这是实测出来的, 不要改:
    bing  真浏览器优先(防爬虫识别), 挂了回落直抓 —— 两条路都能拿到结果
    百度  只能直抓 —— 真浏览器打百度拿到的是"空页面"(正文 52 字, 被挡/空壳),
          而 HTTP 直抓 200 / 988KB / 7~8 条真结果(实测对题 7/7)
★ 解析
    bing  <li class="b_algo"> 块里取 h2>a 的标题与链接、<p> 的摘要
    百度  <div class="result c-container" mu="真链">; 标题在块内第一个 <h3>;
          摘要先取可见的 summary-text/c-abstract/c-span-last, 拿不到就翻块内嵌 JSON
          的 "abstract" 字段。★ h3 里的 href 是 link?url= 跳转壳, 真地址在容器的 mu 上
★ 重排: 中文切"单字 + 相邻双字组"、英文切小写词, 按 IDF 加权 —— 标题命中 ×3, 摘要 ×1。
  这一步是为多页结果准备的（第 3 页的结果常常没有第 1 页对题）。
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import re
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import browser
import fetch

from html import unescape as unescape_entities

PAGE_SIZE = 10
# 每个搜索站: 支持哪些域名(前者挂了回落后者) / 取页路的偏好顺序 / 人看的名字
SITE_HOSTS: dict[str, tuple[str, ...]] = {
    "bing": ("cn.bing.com", "www.bing.com"),
    "baidu": ("www.baidu.com",),
}
SITE_TRANSPORT: dict[str, tuple[str, ...]] = {
    "bing": ("browser", "http"),      # 真浏览器优先, 挂了回落直抓
    "baidu": ("http",),               # ★ 只能直抓: 真浏览器打百度是空页面(实测)
}
SITE_LABELS: dict[str, str] = {"bing": "bing", "baidu": "百度"}
SITES: tuple[str, ...] = ("bing", "baidu")

STORE_CONFIG = Path(__file__).resolve().parent.parent / "resources" / "store.json"

# 单次(一条命令)取的字节预算: 跨站跨页累加, 到顶就不再取后面的页(体积闸第二道, 默认 20MB)
_FETCHED: dict[str, Any] = {"bytes": 0, "limit": 0, "hit": False}


def _single_limit_bytes() -> int:
    """单次字节上限(默认 20MB): 读 store.json(借 fetch 的读法), 读不到按默认."""
    return max(1, int(fetch.store_mb("single_max_mb", 20) * 1048576))


def _budget_reset() -> None:
    """开搜前清账."""
    _FETCHED["bytes"] = 0
    _FETCHED["limit"] = _single_limit_bytes()
    _FETCHED["hit"] = False


def _over_budget() -> bool:
    return bool(_FETCHED["limit"]) and _FETCHED["bytes"] >= _FETCHED["limit"]


_CN = re.compile(r"[\u4e00-\u9fff]")
_WRAPPED = re.compile(r"bing\.com/ck/a", re.I)
_BAIDU_BLOCK = re.compile(r'<div[^>]*class="result c-container[^"]*"')
_BAIDU_TITLE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
_BAIDU_MU = re.compile(r'\smu="(http[^"]+)"')
_BAIDU_ABSTRACT = (
    r'class="[^"]*summary-text[^"]*"[^>]*>(.*?)</div>',
    r'class="c-abstract[^"]*"[^>]*>(.*?)</div>',
    r'class="c-span-last[^"]*"[^>]*>(.*?)</div>',
)
_BAIDU_JSON_ABSTRACT = re.compile(r'"abstract":"((?:[^"\\]|\\.)*)"')


class BingParser(HTMLParser):
    """把结果页的 HTML 拆成一条条结果."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, Any]] = []
        self._in_algo = False
        self._in_title = False
        self._in_link = False
        self._in_p = False
        self._title: list[str] = []
        self._snippet: list[str] = []
        self._url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        table = {name: value for name, value in attrs if value is not None}
        classes = table.get("class", "")
        if tag == "li" and "b_algo" in classes:
            self._in_algo = True
            self._title, self._snippet, self._url = [], [], ""
        elif self._in_algo and tag == "h2":
            self._in_title = True
        elif self._in_title and tag == "a":
            self._in_link = True
            self._url = table.get("href", "")
        elif self._in_algo and tag == "p":
            self._in_p = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "li" and self._in_algo:
            self._in_algo = False
            title = "".join(self._title).strip()
            snippet = "".join(self._snippet).strip()
            if title and self._url:
                self.rows.append({"title": title, "url": unwrap(self._url),
                                  "snippet": re.sub(r"\s+", " ", snippet)})
        elif tag == "h2":
            self._in_title = False
        elif tag == "a":
            self._in_link = False
        elif tag == "p":
            self._in_p = False

    def handle_data(self, data: str) -> None:
        if self._in_p:
            self._snippet.append(data)
        elif self._in_link:
            self._title.append(data)


def unwrap(url: str) -> str:
    """把 bing 的跳转壳（/ck/a?u=a1<base64>）还原成真地址; 不是壳就原样返回."""
    if not _WRAPPED.search(url):
        return url
    query = urllib.parse.urlparse(url).query
    raw = urllib.parse.parse_qs(query).get("u", [""])[0]
    if not raw:
        return url
    if raw.startswith("a1"):
        raw = raw[2:]
    padding = "=" * (-len(raw) % 4)
    try:
        real = base64.urlsafe_b64decode(raw + padding).decode("utf-8", "replace")
    except (ValueError, UnicodeDecodeError):
        return url
    return real if real.startswith("http") else url


def tokenize(text: str) -> list[str]:
    """中文: 单字 + 相邻双字组; 英文: 小写整词."""
    tokens: list[str] = []
    for part in text.split():
        if _CN.search(part):
            chars = list(part)
            tokens.extend(chars)
            tokens.extend(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
        else:
            tokens.append(part.lower())
    return [token for token in tokens if token]


def rerank(query: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 IDF 加权重排; 标题命中 ×3, 摘要 ×1."""
    if len(rows) < 2:
        return rows
    tokens = set(tokenize(query))
    total = len(rows)
    scores: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        title = str(row.get("title", "")).lower()
        snippet = str(row.get("snippet", "")).lower()
        score = 0.0
        for token in tokens:
            hit = sum(1 for other in rows
                      if token in (str(other.get("title", ""))
                                   + str(other.get("snippet", ""))).lower())
            weight = max(0.1, math.log(1 + total / max(hit, 1)))
            if token in title:
                score += 3.0 * weight
            if token in snippet:
                score += weight
        scores.append((score, row))
    scores.sort(key=lambda pair: pair[0], reverse=True)
    ordered: list[dict[str, Any]] = []
    for place, (_, row) in enumerate(scores, 1):
        row["rank"] = place
        ordered.append(row)
    return ordered


def norm_url(url: str) -> str:
    """去重用的规范化地址: 去掉 fragment 与 utm/spm/from/source/ref 这类跟踪参数."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    query = re.sub(r"([?&])(utm_|spm|from|source|ref|share_token)[^&]*", "", parts.query).strip("&?")
    path = parts.path.rstrip("/")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc.lower(), path, query, ""))


def search_url(site: str, host: str, query: str, page: int) -> str:
    """拼一条结果页地址(page 从 1 开始).

    ★ bing 的 count=10 要带上 —— 不带它 bing 会给一个更差的默认集(实测同一查询明显不对题)。
    ★ 百度用 wd + pn(pn 从 0 起, 每页 10) + rn; 实测直抓能拿到 7~8 条真结果。
    """
    if site == "baidu":
        params = urllib.parse.urlencode({"wd": query, "pn": (page - 1) * PAGE_SIZE, "rn": PAGE_SIZE})
        return f"https://{host}/s?{params}"
    params = urllib.parse.urlencode({"q": query, "count": PAGE_SIZE, "first": (page - 1) * PAGE_SIZE + 1})
    return f"https://{host}/search?{params}"


def strip_tags(raw: str) -> str:
    """去注释去标签 + 收空白 + 解实体 —— 用来把结果块里的标题/摘要抠干净."""
    body = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    body = re.sub(r"<[^>]+>", "", body)
    return re.sub(r"\s+", " ", unescape_entities(body)).strip()


def parse_baidu(doc: str) -> list[dict[str, Any]]:
    """百度结果页 -> 条目列表.

    ★ 真地址在结果容器的 mu 属性上, 不要用 h3 里那个 link?url= 跳转壳。
    ★ 摘要: 先取页面上看得见的那几块, 拿不到就翻块内嵌 JSON 的 abstract 字段。
    """
    starts = [m.start() for m in _BAIDU_BLOCK.finditer(doc)]
    if not starts:
        return []
    starts.append(len(doc))
    rows: list[dict[str, Any]] = []
    for i in range(len(starts) - 1):
        block = doc[starts[i]:starts[i + 1]]
        mu = _BAIDU_MU.search(block)
        title_tag = _BAIDU_TITLE.search(block)
        if not (mu and title_tag):
            continue
        link = unescape_entities(mu.group(1))
        if re.fullmatch(r"https?://(www\.)?baidu\.com/?", link):     # 空壳 / 自家推广位
            continue
        title = strip_tags(title_tag.group(1))
        if not title:
            continue
        snippet = ""
        for pattern in _BAIDU_ABSTRACT:
            found = re.search(pattern, block, re.S)
            if found:
                snippet = strip_tags(found.group(1))
                if len(snippet) >= 20:
                    break
        if len(snippet) < 20:
            blobs = _BAIDU_JSON_ABSTRACT.findall(block)
            if blobs:
                snippet = strip_tags(max(blobs, key=len).replace('\\"', '"'))
        rows.append({"title": title, "url": link, "snippet": snippet})
    return rows


def parse_html(doc: str, site: str = "bing") -> list[dict[str, Any]]:
    """结果页 HTML -> 条目列表(标题 / 链接 / 摘要)."""
    if site == "baidu":
        return parse_baidu(doc)
    parser = BingParser()
    parser.feed(doc)
    return parser.rows


def detect_site(doc: str) -> str:
    """从 HTML 猜这是哪家的结果页(给 parse 子命令用)."""
    return "baidu" if _BAIDU_BLOCK.search(doc) else "bing"


def fresh_rows(rows: list[dict[str, Any]], seen: set[str]) -> list[dict[str, Any]]:
    """挑出没见过的、链接像样的条目(同一地址规范化后只留第一条)."""
    fresh: list[dict[str, Any]] = []
    for row in rows:
        link = str(row.get("url", ""))
        if not link.startswith("http"):
            continue
        key = norm_url(link)
        if not key or key in seen:
            continue
        seen.add(key)
        fresh.append(row)
    return fresh


def fetch_html(url: str, engine: str = "browser") -> tuple[str, int]:
    """按引擎取一页 HTML: browser=真浏览器(防爬虫识别), http=直抓(快, 但会被挡).

    回 (HTML, 状态码) —— 状态码跟着结果落库(表里的 status 列), 0 = 没拿到。
    """
    if engine == "http":
        page = fetch.fetch(url)
        return page.html, int(page.status)
    result = browser.fetch(browser.load_config(), url)
    path = str(result.get("html_path") or "")
    if not path or not Path(path).is_file():
        kind = str(result.get("err_kind") or "取不到")
        msg = str(result.get("err_msg") or "")
        raise RuntimeError(f"{kind}: {msg}".strip())
    status = int(result.get("status") or 0)
    return Path(path).read_text(encoding="utf-8", errors="replace"), status


def terms(query: str) -> list[str]:
    """把查询拆成词(空格/中英标点都算分隔)."""
    return [t for t in re.split(r"[\s,，。、+;；/|]+", query.strip()) if t]


# 搜索算子: 值不是内容词的(site:/filetype: 这些, 值是域名或格式)整条丢,
# 值是词的(intitle: 这些)剥壳留词
_算子丢 = ("site:", "filetype:", "ext:", "inurl:", "allinurl:", "related:", "link:", "define:")
_算子剥 = ("intitle:", "allintitle:", "intext:", "allintext:")


def 去算子(part: str) -> str:
    """剥掉一个词外面的搜索算子壳; 剥不成内容词(域名/格式/排除词)就返回空串.

    ★ 为什么必须剥: 不剥的话 core_term 会挑出 `site:github.com` / `intitle:爬虫` 这种
      带算子的串 —— 对题率用它去数一条也对不上(**实测误报 0.0%**, 百度那条明明 6/6 全中),
      而默认的"不对题就退回核心词重查"还会拿着这个串去重查, 回来一屏无关结果。
    """
    word = part.strip('"“”\'')
    if word.startswith(("-", "+")):
        return ""                                  # 排除词/强制词: 拿它当核心词等于搜反了
    low = word.lower()
    for 算子 in _算子丢:
        if low.startswith(算子):
            return ""
    for 算子 in _算子剥:
        if low.startswith(算子):
            return word[len(算子):]
    return word


def core_term(query: str) -> str:
    """挑查询的"核心词": 最长的中文词; 没有中文就取最长的词(算子壳先剥掉).

    ★ 为什么要挑: cn.bing.com 对长中文机构名的分词很差 —— 给它
      「浙江工业职业技术学院 绍兴」会退化成按「浙江」泛搜, 给「机器学习 入门」
      会退化成按「机器」查词典. 退回核心词单查反而对题(实测 7/10 vs 0/10).
    ★ 为什么要先剥算子: 见 去算子.
    """
    parts = [word for word in (去算子(piece) for piece in terms(query)) if word]
    if not parts:
        return query.strip()
    cn = [p for p in parts if _CN.search(p)]
    pool = cn or parts
    return max(pool, key=len)


def relevance(rows: list[dict[str, Any]], term: str) -> float:
    """这批结果有多少条真含这个词 —— 用来判"bing 是不是在灌泛结果"."""
    if not rows or not term:
        return 0.0
    hit = 0
    for row in rows:
        blob = (str(row.get("title", "")) + " " + str(row.get("snippet", ""))).lower()
        if term.lower() in blob:
            hit += 1
    return hit / len(rows)


def _why_empty(site: str, doc: str) -> str:
    """拿到页面却一条都没解析出来, 说清是哪一种（被挡 / 改版 / 真没结果）.

    ★ 实测 2026-10-08: 百度连打几次会换成"百度安全验证"页（1438 字, 零结果块）——
      这种必须报"被挡了", 不能混在"没搜到"里, 不然人会以为真没结果。
    """
    marks = [mark for mark in ("安全验证", "wappass", "网络不给力", "请输入验证码", "captcha", "verify")
             if mark in doc]
    if marks:
        return f"{SITE_LABELS[site]} 被挡成验证页了（页面里出现「{marks[0]}」）—— 歇一会儿再试, 或先只用 bing"
    return f"{SITE_LABELS[site]} 页面拿到了（{len(doc)} 字）但没解析出结果 —— 可能它改了版式, 也可能这条真没有"


def site_once(site: str, query: str, pages: int, engine: str = "") -> list[dict[str, Any]]:
    """打一个站一遍（不退）: 去重 + 重排 + 标来源.

    按该站偏好的取页路轮着试（engine 给了就只用它）, 每条路里再按域名轮着试;
    拿到结果就停(多页就并到一起)。拿到页面却没结果也要留个说法, 不得静默成"没搜到"。
    """
    transports = (engine,) if engine else SITE_TRANSPORT[site]
    last_error = ""
    for transport in transports:
        for host in SITE_HOSTS[site]:
            rows: list[dict[str, Any]] = []
            seen: set[str] = set()
            for page in range(1, max(1, pages) + 1):
                if _over_budget():           # ★ 体积闸第二道: 这条命令取的页到顶就不再往下取
                    _FETCHED["hit"] = True
                    break
                url = search_url(site, host, query, page)
                try:
                    doc, status = fetch_html(url, transport)
                except RuntimeError as error:
                    last_error = str(error)
                    rows = []
                    break
                _FETCHED["bytes"] += len(doc.encode("utf-8", "replace"))
                fresh = fresh_rows(parse_html(doc, site), seen)
                if not fresh and not rows:
                    last_error = _why_empty(site, doc)
                for row in fresh:
                    row["status"] = status      # 结果页的 HTTP 码, 跟着条目一起落库
                rows.extend(fresh)
            if rows:
                for row in rows:
                    row["来源"] = SITE_LABELS[site]
                    row["取页"] = transport
                return rerank(query, rows)
    if last_error:
        raise RuntimeError(f"没拿到结果（{last_error}）")
    return []


def search_site(site: str, query: str, pages: int, engine: str = "",
                fallback: bool = True) -> list[dict[str, Any]]:
    """打一个站（带"不对题就退回核心词"的自检）.

    ★ 为什么要按站退: bing 对长中文机构名会灌泛结果, 百度不会 —— 两站一起打时
      要是按合起来的结果判, bing 那堆泛结果会把整体拉低。按站各退各的, 再合并。
    """
    rows = site_once(site, query, pages, engine)
    if not fallback:
        return rows
    core = core_term(query)
    if core and core != query.strip() and relevance(rows, core) < 0.3:
        alt = site_once(site, core, pages, engine)
        if relevance(alt, core) > relevance(rows, core):
            for row in alt:
                row["note"] = f"退回核心词「{core}」重查的结果"
            return alt
    return rows


def merge(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """跨站合并: 同一地址只留先到的那条, 来源并起来（如 "bing+百度"）."""
    order: list[str] = []
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = norm_url(str(row.get("url", "")))
        if not key:
            continue
        if key in merged:
            old = str(merged[key].get("来源", ""))
            new = str(row.get("来源", ""))
            if new and new not in old:
                merged[key]["来源"] = f"{old}+{new}" if old else new
            if not str(merged[key].get("snippet", "")).strip():
                merged[key]["snippet"] = row.get("snippet", "")
            continue
        merged[key] = row
        order.append(key)
    return [merged[key] for key in order]


def search(query: str, pages: int = 1, site: str = "both", engine: str = "",
           fallback: bool = True) -> list[dict[str, Any]]:
    """真去打搜索站, 拿回结果列表（跨站去重 + 重排 + 相关性自检后）.

    pages:    每站打几页（每页 10 条）。
    site:     both=两站一起打(默认) / bing / baidu; 每站的取页路按 SITE_TRANSPORT 定。
    engine:   给值就强制走这一条取页路（browser / http）, 空 = 按各站自己的偏好。
    fallback: 结果不对题(含核心词的比例 < 30%) 就退回核心词重查一次, 谁对题用谁。
    """
    _budget_reset()                    # ★ 体积闸第二道: 开搜前清字节账
    picked = SITES if site == "both" else (site,)
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    for one in picked:
        try:
            rows.extend(search_site(one, query, pages, engine, fallback))
        except RuntimeError as error:
            problems.append(str(error))
    if _FETCHED["hit"]:
        print(f"[体积闸] 这条命令取的页到 {_FETCHED['limit'] / 1048576:g}MB 上限, 后面的页没再取",
              file=sys.stderr)
    if not rows:
        raise RuntimeError("; ".join(problems) if problems else "什么都没拿到")
    if problems:
        print("[有站没成] " + "; ".join(problems), file=sys.stderr)
    return rerank(query, merge(rows))


def show(query: str, rows: list[dict[str, Any]], as_json: bool) -> None:
    """结果打出来: 默认给人看, --json 给程序吃."""
    core = core_term(query)
    score = relevance(rows, core) if core else 0.0
    from_site: dict[str, int] = {}
    for row in rows:
        label = str(row.get("来源", "?"))
        from_site[label] = from_site.get(label, 0) + 1
    if as_json:
        print(json.dumps(
            {"query": query, "count": len(rows), "core": core, "relevance": round(score, 3),
             "from_site": from_site, "rows": rows},
            ensure_ascii=False, indent=2))
        return
    head = "  ".join(f"{label} {count} 条" for label, count in from_site.items())
    print(f"查询: {query}    拿到 {len(rows)} 条（{head}）    含核心词「{core}」的 {score:.0%}")
    if score < 0.3:
        print("★ 对题率低: 这俩站对这类查询会给泛结果, 换个更具体的词再搜")
    for row in rows:
        note = str(row.get("note", ""))
        print(f"\n{row.get('rank', '?')}. {row.get('title', '')}   [{row.get('来源', '')}]")
        print(f"   {row.get('url', '')}")
        snippet = str(row.get("snippet", "")).strip()
        if snippet:
            print(f"   {snippet}")
        if note:
            print(f"   [{note}]")


def _gate() -> None:
    """过单轮次数闸（防模型钻牛角尖）: 过不去就直接禁止搜索.

    ★ 先扣再搜, 不做事后账: 搜完了再说"你超了"等于没闸。
    ★ 诊断都写 stderr —— stdout 要留给 --json, 不能被这类行污染。
    """
    try:
        import corpus
        info: dict[str, Any] = corpus.budget(corpus.load_config())
    except (RuntimeError, OSError, ValueError) as error:
        print(f"[闸出问题] {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"[闸] 第 {info['轮次']} 轮: 已用 {info['已用']}/{info['上限']}, 还剩 {info['剩']}", file=sys.stderr)


def _save(query: str, rows: list[dict[str, Any]]) -> None:
    """把这次的结果落热库（落不动不影响已经拿到的结果, 但错误必须打出来）."""
    try:
        import corpus
        config: dict[str, Any] = corpus.load_config()
        with corpus.connect(config) as conn:
            corpus.ensure_schema(conn, config)
            added, reused = corpus.put_serp(conn, config, query, rows)
            tidied: dict[str, int] = corpus.tidy(conn, config)
    except (RuntimeError, OSError, ValueError) as error:
        print(f"[落库没成] {error}", file=sys.stderr)
        return
    tail = "; 顺手维护 " + " ".join(f"{key} {value}" for key, value in tidied.items() if value) if any(tidied.values()) else ""
    print(f"[落库] 热库: 新增 {added} 条, 复用 {reused} 条{tail}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="结果页(bing / 百度) -> 结构化结果")
    sub = ap.add_subparsers(dest="action", required=True)
    p_search = sub.add_parser("search", help="真去打搜索站拿结果")
    p_search.add_argument("query")
    p_search.add_argument("--pages", type=int, default=1, help="每站打几页(每页 10 条)")
    p_search.add_argument("--site", choices=("both", "bing", "baidu"), default="both",
                          help="打哪个站(默认 both: 两家一起, 跨站去重)")
    p_search.add_argument("--engine", choices=("auto", "browser", "http"), default="auto",
                          help="取页路(默认 auto: 按各站自己的偏好)")
    p_search.add_argument("--no-fallback", action="store_true", help="不对题也不退回核心词重查")
    p_search.add_argument("--no-save", action="store_true", help="这次不落热库(默认落)")
    p_search.add_argument("--no-gate", action="store_true", help="不过单轮次数闸(默认过)")
    p_search.add_argument("--json", action="store_true", help="出 JSON")
    p_parse = sub.add_parser("parse", help="解析本地存下来的结果页 HTML")
    p_parse.add_argument("file")
    p_parse.add_argument("--site", choices=("auto", "bing", "baidu"), default="auto", help="哪家的页(默认自动认)")
    p_parse.add_argument("--query", default="", help="给了就顺手重排")
    p_parse.add_argument("--json", action="store_true", help="出 JSON")
    args = ap.parse_args()

    try:
        if args.action == "search":
            query = str(args.query)
            if not args.no_gate:
                _gate()
            engine = "" if args.engine == "auto" else str(args.engine)
            rows = search(query, int(args.pages), str(args.site), engine, not bool(args.no_fallback))
        else:
            query = str(args.query)
            doc = Path(str(args.file)).read_text(encoding="utf-8", errors="replace")
            site = detect_site(doc) if args.site == "auto" else str(args.site)
            rows = parse_html(doc, site)
            for row in rows:
                row["来源"] = SITE_LABELS.get(site, site)
            rows = rerank(query, rows) if query else rows
    except RuntimeError as error:
        print(f"[取不到] {error}")
        return 1
    show(query, rows, bool(args.json))
    if args.action == "search" and not args.no_save:
        _save(query, rows)
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""真浏览器(CDP 驱动系统 Chrome): 取页 / 截图 / 错误分类.

为什么不 HTTP 直抓: 有一批站按 UA / JS 挑战 / TLS 指纹挡爬虫, 直抓拿回的是挑战页.
用真 Chrome 出网, 拿到的是人看到的那一份.

常驻: chrome 起一次留着复用(冷启 2~4 秒, 每次都起太亏).
延时看门狗: 闲置超过 idle_seconds 就杀掉, 下次用时再拉起 —— 常驻但不养老.

用法:
    .venv/bin/python skill/search/scripts/browser.py start|stop|status|watch
    .venv/bin/python skill/search/scripts/browser.py fetch <url> [--shot 路径] [--seconds 2.5]

输出: 一行 JSON(UTF-8) —— 给程序侧直接吃, 不加工.
配置: skill/search/resources/browser.json(每次跑现读, 改了不用重启).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, cast

import websocket

HERE = Path(__file__).resolve().parent          # skill/search/scripts
SKILL = HERE.parent                             # skill/search
CACHE = SKILL / "cache"                         # 不进 git
STATE = CACHE / "browser"                       # pid / last_use / profile
SHOTS = CACHE / "shots"                         # 截图落这
PAGES = CACHE / "pages"                         # 落盘 html 落这
CONFIG = SKILL / "resources" / "browser.json"
LOGDIR = SKILL / "logs"
LOG = LOGDIR / "browser.log"

Json = dict[str, Any]

DEFAULTS: Json = {
    "chrome": "/usr/bin/google-chrome",
    "port": 9334,
    "headless": True,
    "window": [1440, 900],
    "idle_seconds": 300,
    "watch_tick": 10,
    "nav_timeout": 25,
    "dom_grace_seconds": 3.0,
    "settle_seconds": 2.5,
    "max_html_bytes": 5242880,
    "max_shot_height": 8000,
    "min_text_chars": 200,
    "shot_quality": 70,
    "lang": "zh-CN",
    "hide_webdriver": True,
    "no_proxy": True,
    "wipe_profile_on_stop": True,
}

# CDP 网络错 -> 我们的口径(第 3 页失败四类). 前缀匹配.
NET_ERRORS: list[tuple[str, str]] = [
    ("ERR_NAME_NOT_RESOLVED", "站点不存在"),
    ("ERR_CERT", "HTTPS 错误"),
    ("ERR_SSL", "HTTPS 错误"),
    ("ERR_CONNECTION_TIMED_OUT", "响应超时"),
    ("ERR_TIMED_OUT", "响应超时"),
    ("ERR_ABORTED", "响应超时"),
    ("ERR_CONNECTION_REFUSED", "站点拒绝"),
    ("ERR_CONNECTION_RESET", "站点拒绝"),
    ("ERR_CONNECTION_CLOSED", "站点拒绝"),
    ("ERR_EMPTY_RESPONSE", "响应为空"),
    ("ERR_BLOCKED_BY_CLIENT", "被拦截"),
    ("ERR_TOO_MANY_REDIRECTS", "跳转过多"),
]


class CdpError(RuntimeError):
    """CDP 通信出问题(连接断 / 命令超时 / 拿不到 target)."""


# ---------------------------------------------------------------- 取值窄化

def as_dict(value: object) -> Json:
    """是 dict 就当 dict 用, 不是就给个空的 —— 挡住 Any 里的未知类型."""
    return cast(Json, value) if isinstance(value, dict) else {}


def as_list(value: object) -> list[object]:
    """是 list 就当 list 用, 不是就给个空的."""
    return cast(list[object], value) if isinstance(value, list) else []


def as_str(value: object) -> str:
    """是字符串才要, 别的给空串."""
    return value if isinstance(value, str) else ""


def as_float(value: object, fallback: float) -> float:
    """能当数用就当数用, 不能就用兜底值."""
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    return fallback


# ---------------------------------------------------------------- 配置与状态

def load_config() -> Json:
    """读配置: resources/browser.json 覆盖默认值(缺项用默认)."""
    cfg: Json = dict(DEFAULTS)
    if CONFIG.is_file():
        raw = cast(object, json.loads(CONFIG.read_text(encoding="utf-8")))
        cfg.update(as_dict(raw))
    return cfg


def ensure_dirs() -> None:
    """把要写的目录都建出来."""
    for d in (CACHE, STATE, SHOTS, PAGES, LOGDIR):
        d.mkdir(parents=True, exist_ok=True)


def pid_file() -> Path:
    return STATE / "chrome.pid"


def watch_pid_file() -> Path:
    return STATE / "watch.pid"


def last_use_file() -> Path:
    return STATE / "last_use"


def touch() -> None:
    """记一次"刚用过" —— 看门狗照这个判闲置."""
    ensure_dirs()
    last_use_file().write_text(str(time.time()), encoding="utf-8")


def idle_for() -> float:
    """距上次用过了多少秒(没有记录 = 无穷大)."""
    f = last_use_file()
    if not f.is_file():
        return float("inf")
    try:
        return max(0.0, time.time() - float(f.read_text(encoding="utf-8").strip()))
    except ValueError:
        return float("inf")


def log(msg: str) -> None:
    """往 logs/browser.log 记一行, 同时打到 stderr(前台跑时能看见)."""
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, file=sys.stderr)
    try:
        ensure_dirs()
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- 进程活着没

def opener() -> urllib.request.OpenerDirector:
    """绕开本机代理 —— 打 127.0.0.1 走代理会被拦成 502 空 body."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def cdp_http(path: str, port: int, timeout: float = 5.0) -> object:
    """问 CDP 的 HTTP 口(--remote-debugging-port), 拿回解析好的 JSON."""
    url = f"http://127.0.0.1:{port}{path}"
    with opener().open(url, timeout=timeout) as resp:
        return cast(object, json.loads(resp.read().decode("utf-8", "replace")))


def port_speaks(port: int) -> bool:
    """CDP 口答不答话 —— 判活只看这个, 不看端口有没有被占."""
    try:
        cdp_http("/json/version", port, timeout=2.0)
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def cmdline_has(pid: int, needle: str) -> bool:
    """该 pid 的命令行里有没有这个串(按 /proc 精确点名, 不用 ps|grep)."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    return needle in raw.decode("utf-8", "replace")


def read_pid(port: int) -> int:
    """读自己记的 pid; 进程没了或命令行不对(口被别人占了) -> 0."""
    f = pid_file()
    if not f.is_file():
        return 0
    try:
        pid = int(f.read_text(encoding="utf-8").strip())
    except ValueError:
        return 0
    if pid <= 0 or not cmdline_has(pid, f"remote-debugging-port={port}"):
        return 0
    return pid


def chrome_alive(cfg: Json) -> int:
    """我们那只 chrome 还活着吗: 返回 pid, 不在返回 0."""
    port = int(as_float(cfg.get("port"), 9334.0))
    pid = read_pid(port)
    return pid if pid and port_speaks(port) else 0


def watchdog_pid() -> int:
    """看门狗还在不在."""
    f = watch_pid_file()
    if not f.is_file():
        return 0
    try:
        pid = int(f.read_text(encoding="utf-8").strip())
    except ValueError:
        return 0
    if pid > 0 and cmdline_has(pid, "browser.py"):
        return pid
    return 0


# ---------------------------------------------------------------- 起 / 杀

def launch(cfg: Json) -> int:
    """起一只 chrome(setsid 独立会话), 等 CDP 口答话才算成."""
    chrome = as_str(cfg.get("chrome"))
    if not Path(chrome).is_file():
        raise CdpError(f"找不到 chrome: {chrome}")
    win = as_list(cfg.get("window"))
    w = int(as_float(win[0] if len(win) > 0 else None, 1440.0))
    h = int(as_float(win[1] if len(win) > 1 else None, 900.0))
    port = int(as_float(cfg.get("port"), 9334.0))
    ensure_dirs()

    args: list[str] = [chrome]
    if bool(cfg.get("no_proxy", True)):
        args.append("--no-proxy-server")
    args.append("--headless=new" if bool(cfg.get("headless", True)) else "--start-maximized")
    args.extend(
        [
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-timer-throttling",
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--window-size={w},{h}",
            f"--lang={as_str(cfg.get('lang')) or 'zh-CN'}",
            f"--user-data-dir={STATE / 'profile'}",
            "about:blank",
        ]
    )

    with (LOGDIR / "chrome.out").open("a", encoding="utf-8") as out:
        proc = subprocess.Popen(args, stdout=out, stderr=out, start_new_session=True)

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise CdpError(f"chrome 起完就退了(码 {proc.returncode}), 看 logs/chrome.out")
        if port_speaks(port):
            pid_file().write_text(str(proc.pid), encoding="utf-8")
            log(f"chrome 起来了 pid={proc.pid} port={port}")
            return proc.pid
        time.sleep(0.3)
    kill_pid(proc.pid)
    raise CdpError("chrome 起来了但 CDP 口 30 秒没答话")


def kill_pid(pid: int) -> bool:
    """杀掉整个会话(树一起收), 复查真没了才返回 True."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(pid), sig)
        except (ProcessLookupError, PermissionError):
            pass
        deadline = time.monotonic() + (8.0 if sig == signal.SIGTERM else 5.0)
        while time.monotonic() < deadline:
            if not Path(f"/proc/{pid}").exists():
                return True
            time.sleep(0.2)
    return False


def clear_state(cfg: Json) -> None:
    """清掉我们记的状态; 按配置把浏览数据(profile)也一起清.

    ★ 为什么清 profile: 连打一阵之后 profile 养脏, bing 会给泛结果
      (实测同一查询 连打 20 多次后 对题率 7/10 掉到 0/10, 换新 profile 立刻回到 7/10).
    """
    for f in (pid_file(), last_use_file(), watch_pid_file()):
        f.unlink(missing_ok=True)
    if bool(cfg.get("wipe_profile_on_stop", True)):
        shutil.rmtree(STATE / "profile", ignore_errors=True)


def kill_browser(cfg: Json) -> bool:
    """杀 chrome 本体 + 清状态(不碰看门狗自己 —— 看门狗收尾时要能调它)."""
    port = int(as_float(cfg.get("port"), 9334.0))
    pid = read_pid(port)
    gone = True if not pid else kill_pid(pid)
    clear_state(cfg)
    return gone


def stop(cfg: Json) -> Json:
    """停: 杀看门狗 + 杀 chrome + 清状态.

    ★ 看门狗要一起杀 —— 只清 watch.pid 不清进程会留孤儿, 下次 start 又起一个,
      于是两个看门狗同时盯同一个 chrome.
    """
    port = int(as_float(cfg.get("port"), 9334.0))
    pid = read_pid(port)
    if not pid and not watchdog_pid():
        if port_speaks(port):
            return {"ok": False, "action": "stop", "note": f"口 {port} 有东西在答话, 但不是我们起的, 不动它"}
        clear_state(cfg)
        return {"ok": True, "action": "stop", "note": "本来就没在跑"}
    watcher = watchdog_pid()
    if watcher:
        kill_pid(watcher)
    gone = kill_browser(cfg)
    log(f"停了 chrome pid={pid} 看门狗={watcher} 干净={gone}")
    return {"ok": gone, "action": "stop", "pid": pid, "watchdog_pid": watcher,
            "note": "已停" if gone else "杀了但进程还在"}


def start_watchdog() -> int:
    """看门狗另起一个独立进程(不在就起), 它只管闲置超时杀 chrome."""
    ensure_dirs()
    alive = watchdog_pid()
    if alive:
        return alive
    out = (LOGDIR / "watchdog.out").open("a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "watch"],
        stdout=out,
        stderr=out,
        start_new_session=True,
    )
    watch_pid_file().write_text(str(proc.pid), encoding="utf-8")
    log(f"看门狗起来了 pid={proc.pid}")
    return proc.pid


def ensure_browser(cfg: Json) -> int:
    """要用浏览器了: 在跑就续命, 不在就跑起来."""
    pid = chrome_alive(cfg)
    if pid:
        touch()
        return pid
    stale = read_pid(int(as_float(cfg.get("port"), 9334.0)))
    if stale:
        kill_pid(stale)
    pid = launch(cfg)
    touch()
    start_watchdog()
    return pid


def watch(cfg: Json) -> int:
    """看门狗主循环: 闲置超了 -> 杀 chrome 收工; chrome 没了 -> 自己也退."""
    idle_limit = as_float(cfg.get("idle_seconds"), 300.0)
    tick = as_float(cfg.get("watch_tick"), 10.0)
    log(f"看门狗开始盯: 闲置 {idle_limit:.0f}s 就杀, 每 {tick:.0f}s 看一次")
    while True:
        time.sleep(tick)
        if not chrome_alive(cfg):
            log("chrome 已经不在, 看门狗收工")
            watch_pid_file().unlink(missing_ok=True)
            return 0
        waited = idle_for()
        if waited >= idle_limit:
            log(f"闲置 {waited:.0f}s >= {idle_limit:.0f}s, 杀掉")
            kill_browser(cfg)          # 只收 chrome, 不动自己
            log("看门狗收工")
            return 0


# ---------------------------------------------------------------- CDP 会话

class Session:
    """一条 CDP 连接: 命令与事件共用一条 socket, 按 id 分流."""

    def __init__(self, ws_url: str, timeout: float = 40.0) -> None:
        self._ws = websocket.create_connection(ws_url, timeout=timeout)
        self._ws.settimeout(0.25)
        self._id = 0
        self._replies: dict[int, Json] = {}
        self._closed = False
        # 事件钩子挂在会话上: 命令回包内部也会 pump, 挂这里才不会漏事件
        self.event_hook: Callable[[str, Json], None] | None = None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001 - 关不掉也不碍事
                pass

    def send(self, method: str, params: Json | None = None) -> int:
        self._id += 1
        self._ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        return self._id

    def pump(self, deadline: float, want: int | None = None) -> None:
        """读到 deadline 为止: 回包按 id 存下(等 call 来取), 事件扔给会话上的钩子.

        事件钩子挂在会话上(不是参数) —— 命令回包内部也会 pump, 挂这里才不会漏事件.
        want 给了就是"在等这条回包": 它一到立刻返回, 不吃满这一轮的时间片.
        """
        cb = self.event_hook
        while time.monotonic() < deadline:
            try:
                raw = self._ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except websocket.WebSocketConnectionClosedException as exc:
                raise CdpError(f"CDP 连接断了: {exc}") from exc
            if not raw:
                continue
            try:
                msg = as_dict(cast(object, json.loads(raw)))
            except ValueError:
                continue
            mid = msg.get("id")
            if isinstance(mid, int):
                self._replies[mid] = msg
                if want is not None and mid == want:
                    return
            elif cb is not None:
                method = msg.get("method")
                if isinstance(method, str):
                    cb(method, as_dict(msg.get("params")))

    def call(self, method: str, params: Json | None = None, wait: float = 20.0) -> Json:
        """发一条命令并等它的回包(顺路把事件排掉)."""
        mid = self.send(method, params)
        deadline = time.monotonic() + wait
        if mid in self._replies:
            return self._replies.pop(mid)
        while time.monotonic() < deadline:
            try:
                self.pump(min(deadline, time.monotonic() + 5.0), want=mid)
            except CdpError:
                if mid in self._replies:
                    return self._replies.pop(mid)
                raise
            if mid in self._replies:
                return self._replies.pop(mid)
        raise CdpError(f"CDP 命令没回话: {method}")

    def result(self, method: str, params: Json | None = None, wait: float = 20.0) -> Json:
        """发命令并只要 result 那一段(同时把 CDP 报的错变成异常)."""
        msg = self.call(method, params, wait)
        if "error" in msg:
            raise CdpError(f"{method} 被 CDP 拒了: {as_dict(msg.get('error')).get('message')}")
        return as_dict(msg.get("result"))

    def value(self, expr: str, wait: float = 20.0) -> object:
        """跑一段 JS 把结果拿回来(returnByValue)."""
        got = self.result("Runtime.evaluate", {"expression": expr, "returnByValue": True}, wait)
        return as_dict(got.get("result")).get("value")


def page_target(cfg: Json) -> Json:
    """挑一个 page 型 target; 没有就开一个."""
    port = int(as_float(cfg.get("port"), 9334.0))
    for item in as_list(cdp_http("/json/list", port)):
        target = as_dict(item)
        if target.get("type") == "page" and as_str(target.get("webSocketDebuggerUrl")):
            return target
    req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
    with opener().open(req, timeout=5) as resp:
        fresh = as_dict(cast(object, json.loads(resp.read().decode("utf-8", "replace"))))
    if as_str(fresh.get("webSocketDebuggerUrl")):
        return fresh
    raise CdpError("拿不到 page target")


def map_net_error(text: str) -> tuple[str, str]:
    """CDP 的 net::ERR_* -> (口径, 给人看的原文)."""
    for needle, kind in NET_ERRORS:
        if needle in text:
            return kind, text
    return "具体报错", text


def save_shot(data: str, out: Path | None, url: str) -> Path:
    """截图的 base64 落盘, 返回路径."""
    raw = base64.b64decode(data)
    path = out if out is not None else SHOTS / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def save_html(cfg: Json, html: str, url: str) -> tuple[Path, int, bool]:
    """html 落盘(超上限就截断), 返回 (路径, 字节, 有没有截断)."""
    limit = int(as_float(cfg.get("max_html_bytes"), 5242880.0))
    blob = html.encode("utf-8", "replace")
    cut = len(blob) > limit
    if cut:
        blob = blob[:limit]
    path = PAGES / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}.html"
    path.write_bytes(blob)
    return path, len(blob), cut


def shoot(sess: Session, cfg: Json, url: str, out: Path | None) -> str:
    """整页截图(高度按实际内容, 夹上限), 返回落盘路径(没成给空串)."""
    win = as_list(cfg.get("window"))
    width = int(as_float(win[0] if len(win) > 0 else None, 1440.0))
    height = as_float(win[1] if len(win) > 1 else None, 900.0)
    try:
        metrics = sess.result("Page.getLayoutMetrics", wait=10)
        content = as_dict(metrics.get("cssContentSize"))
        height = as_float(content.get("height"), height)
    except CdpError:
        pass
    height = min(max(height, 200.0), as_float(cfg.get("max_shot_height"), 8000.0))
    got = sess.result(
        "Page.captureScreenshot",
        {
            "format": "jpeg",
            "quality": int(as_float(cfg.get("shot_quality"), 70.0)),
            "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1},
        },
        wait=90,
    )
    data = as_str(got.get("data"))
    if not data:
        return ""
    try:
        return str(save_shot(data, out, url))
    except (OSError, ValueError) as exc:
        log(f"截图落盘失败: {exc}")
        return ""


def fetch(cfg: Json, url: str, shot: Path | None = None, seconds: float | None = None) -> Json:
    """取一页: 导航 -> 等渲染 -> 抓状态/标题/html/截图 -> 分类错误."""
    t0 = time.monotonic()
    pid = ensure_browser(cfg)
    sess = Session(as_str(page_target(cfg).get("webSocketDebuggerUrl")))
    out: Json = {
        "ok": False,
        "action": "fetch",
        "url": url,
        "chrome_pid": pid,
        "status": None,
        "final_url": url,
        "err_kind": "",
        "err_msg": "",
        "title": "",
        "text_chars": 0,
        "html_path": "",
        "html_bytes": 0,
        "html_truncated": False,
        "shot_path": "",
        "ms": 0,
    }
    seen: Json = {"status": None, "final_url": url, "loaded": False, "dom": False, "status_at": 0.0}

    def hook(method: str, params: Json) -> None:
        if method == "Network.responseReceived" and seen["status"] is None and params.get("type") == "Document":
            resp = as_dict(params.get("response"))
            if resp:
                seen["status"] = resp.get("status")
                seen["status_at"] = time.monotonic()
                seen["final_url"] = as_str(resp.get("url")) or seen["final_url"]
        elif method == "Page.lifecycleEvent":
            # Chrome 155 不发 domContentEventFired/loadEventFired 那两个老事件, 只发这个
            name = as_str(params.get("name"))
            if name == "DOMContentLoaded":
                seen["dom"] = True
            elif name == "load":
                seen["loaded"] = True
        elif method == "Page.domContentEventFired":
            seen["dom"] = True
        elif method == "Page.loadEventFired":
            seen["loaded"] = True

    try:
        sess.event_hook = hook          # 先挂上, 导航那一瞬间的事件才漏不掉
        sess.result("Page.enable", wait=10)
        sess.result("Network.enable", wait=10)
        sess.result("Runtime.enable", wait=10)
        sess.result("Page.setLifecycleEventsEnabled", {"enabled": True}, wait=10)
        win = as_list(cfg.get("window"))
        sess.result(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": int(as_float(win[0] if len(win) > 0 else None, 1440.0)),
                "height": int(as_float(win[1] if len(win) > 1 else None, 900.0)),
                "deviceScaleFactor": 1,
                "mobile": False,
            },
            wait=10,
        )
        if bool(cfg.get("hide_webdriver", True)):
            # 真浏览器的样子: headless + CDP 会把 navigator.webdriver 亮出来, 清除
            sess.result(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"},
                wait=10,
            )

        nav = sess.result("Page.navigate", {"url": url}, wait=15)
        error_text = as_str(nav.get("errorText"))

        # 等 DOM 立起来就够了 —— 等 load 事件要等全部子资源, 有的站能拖到超时.
        # 渲染还要多久由 settle_seconds 说话.
        grace = as_float(cfg.get("dom_grace_seconds"), 3.0)
        deadline = time.monotonic() + as_float(cfg.get("nav_timeout"), 25.0)
        while not error_text and time.monotonic() < deadline:
            if seen["dom"] and seen["status"] is not None:
                break
            # 兜底: 响应已经到手了, DOM 事件再等不到就不等 —— 别为一条事件干等 25 秒
            status_at = as_float(seen["status_at"], 0.0)
            if status_at and time.monotonic() - status_at >= grace:
                break
            sess.pump(min(deadline, time.monotonic() + 0.5))
        sess.pump(time.monotonic() + 0.3)         # 把路上剩的事件收干净

        settle = as_float(cfg.get("settle_seconds"), 2.5) if seconds is None else seconds
        if settle > 0 and not error_text:
            time.sleep(settle)

        final_url = as_str(seen["final_url"]) or url
        out["final_url"] = final_url
        out["title"] = as_str(sess.value("document.title", wait=10))
        out["text_chars"] = int(
            as_float(sess.value("document.body ? document.body.innerText.length : 0", wait=10), 0.0)
        )
        if not error_text:
            html = as_str(sess.value("document.documentElement ? document.documentElement.outerHTML : ''", wait=40))
            if html:
                path, size, cut = save_html(cfg, html, final_url)
                out["html_path"], out["html_bytes"], out["html_truncated"] = str(path), size, cut
            out["shot_path"] = shoot(sess, cfg, final_url, shot)

        status = seen["status"]
        status_num = int(as_float(status, 0.0))
        out["status"] = status
        if error_text:
            kind, msg = map_net_error(error_text)
            out["err_kind"], out["err_msg"] = kind, msg
        elif status is None:
            out["err_kind"], out["err_msg"] = "响应超时", "导航完了但没收到 Document 响应"
        elif status_num >= 400:
            out["err_kind"], out["err_msg"] = "具体报错", f"HTTP {status_num}"
        elif out["text_chars"] < int(as_float(cfg.get("min_text_chars"), 200.0)):
            out["err_kind"] = "空页面"
            out["err_msg"] = f"正文只有 {out['text_chars']} 字(没内容的页面只回截图)"
        else:
            out["ok"] = True
    except CdpError as exc:
        out["err_kind"], out["err_msg"] = "CDP 故障", str(exc)
    except OSError as exc:
        out["err_kind"], out["err_msg"] = "本机 IO 故障", str(exc)
    finally:
        sess.close()
        touch()
        out["ms"] = int((time.monotonic() - t0) * 1000)
    return out


# ---------------------------------------------------------------- 命令入口

def do_start(cfg: Json) -> Json:
    """把浏览器拉起来(在跑就续命)."""
    alive = chrome_alive(cfg)
    if alive:
        touch()
        start_watchdog()
        return {"ok": True, "action": "start", "pid": alive, "note": "本来就在跑, 已续命"}
    pid = ensure_browser(cfg)
    return {"ok": True, "action": "start", "pid": pid, "note": "起来了"}


def do_status(cfg: Json) -> Json:
    """看浏览器什么状态(在不在 / 闲了多久 / 看门狗还在不在)."""
    port = int(as_float(cfg.get("port"), 9334.0))
    pid = chrome_alive(cfg)
    waited = idle_for()
    return {
        "ok": True,
        "action": "status",
        "alive": bool(pid),
        "pid": pid,
        "port": port,
        "port_speaks": port_speaks(port),
        "watchdog_pid": watchdog_pid(),
        "idle_limit": as_float(cfg.get("idle_seconds"), 300.0),
        "idle_for": None if waited == float("inf") else round(waited, 1),
        "shots": len(list(SHOTS.glob("*.jpg"))) if SHOTS.is_dir() else 0,
        "shot_dir": str(SHOTS),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="真浏览器(CDP): 取页 / 截图 / 错误分类")
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("start", help="拉起浏览器(常驻)")
    sub.add_parser("stop", help="停掉浏览器")
    sub.add_parser("status", help="看状态")
    sub.add_parser("watch", help="看门狗(内部用, 别手跑)")
    p_fetch = sub.add_parser("fetch", help="取一页")
    p_fetch.add_argument("url")
    p_fetch.add_argument("--shot", default="", help="截图存哪(默认 cache/shots/<url摘要>.jpg)")
    p_fetch.add_argument("--seconds", type=float, default=None, help="等渲染多少秒(默认配置里的)")
    p_shot = sub.add_parser("shot", help="只截一张整页图(不解析正文)")
    p_shot.add_argument("url")
    p_shot.add_argument("--shot", default="", help="截图存哪(默认 cache/shots/<url摘要>.jpg)")
    args = ap.parse_args()

    cfg = load_config()
    ensure_dirs()
    action = str(args.action)

    if action == "watch":
        return watch(cfg)

    try:
        if action == "start":
            result = do_start(cfg)
        elif action == "stop":
            result = stop(cfg)
        elif action == "status":
            result = do_status(cfg)
        elif action == "shot":
            out_path = Path(str(args.shot)).expanduser() if args.shot else None
            full = fetch(cfg, str(args.url), out_path)
            result = {
                "ok": bool(full.get("shot_path")),
                "action": "shot",
                "url": str(args.url),
                "final_url": full.get("final_url"),
                "status": full.get("status"),
                "title": full.get("title"),
                "shot_path": full.get("shot_path"),
                "err_kind": full.get("err_kind"),
                "err_msg": full.get("err_msg"),
                "ms": full.get("ms"),
            }
        else:
            shot = Path(str(args.shot)).expanduser() if args.shot else None
            result = fetch(cfg, str(args.url), shot, args.seconds)
    except CdpError as exc:
        result = {"ok": False, "action": action, "err_kind": "浏览器起不来", "err_msg": str(exc)}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("ok"):
        return 0
    return 1 if result.get("err_kind") else 0


if __name__ == "__main__":
    sys.exit(main())

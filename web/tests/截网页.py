#!/usr/bin/env python3
"""给一个 HTTP 地址截全屏图 —— 走 CDP（headless chrome 9333）。

用 http 而不是 file://, 因为要验的是真实服务返回的页面(相对路径的 CSS/JS 才连得上)。

用法: uv run --with websocket-client python 截网页.py <url> <输出png> [宽] [高] [等待秒]
前置: google-chrome --headless=new --disable-gpu --no-sandbox \
        --remote-debugging-port=9333 --remote-allow-origins='*' --incognito about:blank &
"""
from __future__ import annotations

import base64
import json
import sys
import time
import urllib.request
from typing import Any

import websocket  # type: ignore[reportMissingImports]

URL = sys.argv[1]
OUT = sys.argv[2]
W = int(sys.argv[3]) if len(sys.argv) > 3 else 1440
H = int(sys.argv[4]) if len(sys.argv) > 4 else 900
等秒 = float(sys.argv[5]) if len(sys.argv) > 5 else 2.5

targets = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json/list"))  # noqa: S310
pages = [t for t in targets if t["type"] == "page"]
if not pages:
    print("没有可用的 page target", file=sys.stderr)
    sys.exit(1)
ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=40)


def 发(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == 1:
            return msg


发("Emulation.setDeviceMetricsOverride", {"width": W, "height": H, "deviceScaleFactor": 1, "mobile": False})
发("Page.enable")
发("Runtime.enable")
发("Page.navigate", {"url": URL})
time.sleep(等秒)  # 等前端脚本把 DOM 立起来（空态是 JS 渲染的）

# 可选的"空态": 第 6 个参数为 空态 时, 把消息清掉、露出空态 —— 空态 HTML 是服务端给的,
# 这里只是造出"没有消息"的条件, 验的仍是服务端那份标记
if len(sys.argv) > 6 and sys.argv[6] == "空态":
    发("Runtime.evaluate", {"expression": (
        "(()=>{const s=document.getElementById('流');if(s)s.innerHTML='';"
        "const k=document.getElementById('空态');if(k)k.hidden=false;"
        "const h=document.getElementById('历史');if(h)h.innerHTML='<div class=史空>暂无记录</div>';"
        "return 'ok'})()"
    )})
    time.sleep(0.6)

# 同时把控制台错误取出 —— 页面白屏时这是唯一的线索
错 = 发("Runtime.evaluate", {"expression": "JSON.stringify({标题:document.title, 文本:document.body.innerText.slice(0,180), 错:[...(window.__err||[])]})", "returnByValue": True})
print("页面自述:", 错.get("result", {}).get("result", {}).get("value", "?"))

shot = 发("Page.captureScreenshot", {"format": "png"})
数据 = shot.get("result", {}).get("data")
if not isinstance(数据, str):
    print("截图失败:", shot, file=sys.stderr)
    sys.exit(1)
with open(OUT, "wb") as f:
    f.write(base64.b64decode(数据))
print(f"已存 {OUT}")
ws.close()

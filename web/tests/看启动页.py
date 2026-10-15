#!/usr/bin/env python3
"""启动页自检 —— 点「正常启动」走一遍, 看它是不是真把链路跑起来了。

用法: .venv/bin/python web/tests/看启动页.py [url] [输出png]
前置: web 在 :8791 跑着, headless chrome 在 :9333

★ 只点「正常启动」: 它不碰本地模型 —— 那边正跑着清洗, 动它要出乱子。
  「以本地模型启动」那条链的接口同一套(拉模型那步 start_models.sh 自己会跳过
  已经在跑的), 不在这个脚本里重复起模型。
"""
from __future__ import annotations

import base64
import json
import sys
import time
import urllib.request
from typing import Any

import websocket  # type: ignore[reportMissingImports]

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8791/启动"
OUT = sys.argv[2] if len(sys.argv) > 2 else ""

targets = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json/list"))  # noqa: S310
pages = [t for t in targets if t["type"] == "page"]
if not pages:
    print("没有可用的 page target", file=sys.stderr)
    sys.exit(1)
ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=90)
_编号 = 0
出错: list[str] = []


def 发(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    global _编号
    _编号 += 1
    ws.send(json.dumps({"id": _编号, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("method") == "Runtime.exceptionThrown":
            出错.append(str(msg["params"]["exceptionDetails"].get("text", "?")))
        if msg.get("id") == _编号:
            return msg


def 求值(表达式: str) -> Any:
    r = 发("Runtime.evaluate", {"expression": 表达式, "returnByValue": True, "awaitPromise": True})
    return r.get("result", {}).get("result", {}).get("value")


发("Emulation.setDeviceMetricsOverride", {"width": 1100, "height": 860, "deviceScaleFactor": 1, "mobile": False})
发("Page.enable")
发("Runtime.enable")
发("Page.navigate", {"url": URL})
time.sleep(3.0)

print("① 页面上的东西")
print("   标题  :", 求值("document.title"))
print("   两按钮:", 求值("(()=>{const b=[...document.querySelectorAll('.大钮 b')];"
                      "return b.length+' 个 → '+b.map(x=>x.textContent).join(' / ')})()"))
print("   四盏灯:", 求值("(()=>{const l=[...document.querySelectorAll('.灯')];"
                      "return l.map(x=>x.textContent+'='+(x.querySelector('.点').classList.contains('通')?'绿':"
                      "(x.querySelector('.点').classList.contains('忙')?'忙':'灰'))).join('  ')})()"))
print("   日志框:", 求值("document.getElementById('日志').innerText.slice(0,50)"))

print()
print("② 点「正常启动」……")
求值("document.getElementById('钮普通').click()")

好了 = False
for _ in range(95):
    time.sleep(1.0)
    文 = 求值("document.getElementById('日志').innerText")
    if isinstance(文, str) and ("启动完成" in 文 or "✗" in 文 and "自检" in 文):
        好了 = "启动完成" in 文
        break

print("   跑完了吗:", "是 — 全过" if 好了 else "✗ 没等到「启动完成」（超时或中间断了）")
print()
print("③ 日志框（这就是老板会看到的）")
文 = 求值("document.getElementById('日志').innerText")
for 行 in str(文 or "").split("\n"):
    if 行.strip():
        print("   " + 行.strip())
print()
print("④ 「进入」按钮显了吗:", 求值("!!document.querySelector('.进.显')"))
print("⑤ 四盏灯现在 :", 求值("(()=>{const l=[...document.querySelectorAll('.灯')];"
                          "return l.map(x=>x.textContent+'='+(x.querySelector('.点').classList.contains('通')?'绿':'灰')).join('  ')})()"))
print("⑥ JS 报错     :", 出错 or "无")

if OUT:
    图 = 发("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data", "")
    if 图:
        open(OUT, "wb").write(base64.b64decode(图))
        print("   截图已存:", OUT)

ws.close()
sys.exit(0 if (好了 and not 出错) else 1)

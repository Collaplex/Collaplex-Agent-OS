#!/usr/bin/env python3
"""验设置页的分栏 —— 走 CDP(headless chrome 9333)。

验什么:
  ① 左栏列了哪几节, 当前哪颗亮着
  ② 逐颗点过去: 右区标题换没换、高亮跟没跟着走、那一节有没有出料
  ③ 保存条只在"改得动"的节(接口/开关)上出现, 只读节上不摆
  ④ 刷新页面后回到上次待的那一节
  ⑤ 全程无 JS 报错;  最后截图

用法: ./.venv/bin/python web/tests/check_settings_panes.py <url> <输出png> [宽] [高]
前置: headless chrome 9333 起着
"""
from __future__ import annotations

import base64
import json
import sys
import time
import urllib.request
from typing import Any, cast

import websocket  # type: ignore[reportMissingImports]

URL = sys.argv[1]
OUT = sys.argv[2]
W = int(sys.argv[3]) if len(sys.argv) > 3 else 1440
H = int(sys.argv[4]) if len(sys.argv) > 4 else 1080

targets = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json/list"))  # noqa: S310
pages = [t for t in targets if t["type"] == "page"]
if not pages:
    print("没有可用的 page target", file=sys.stderr)
    sys.exit(1)
ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=60)
_编号 = 0


def 发(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    global _编号
    _编号 += 1
    ws.send(json.dumps({"id": _编号, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == _编号:
            return msg


def 求值(表达式: str) -> Any:
    r = 发("Runtime.evaluate", {"expression": 表达式, "returnByValue": True, "awaitPromise": True})
    return r.get("result", {}).get("result", {}).get("value")


发("Emulation.setDeviceMetricsOverride", {"width": W, "height": H, "deviceScaleFactor": 1, "mobile": False})
发("Page.enable")
发("Runtime.enable")
发("Page.navigate", {"url": URL})
time.sleep(3.0)
求值("document.getElementById('设置钮').click()")
time.sleep(1.5)

print("① 左栏:", 求值(
    "(()=>{const b=[...document.querySelectorAll('.设钮')];"
    "return b.length+' 颗: '+b.map(x=>(x.classList.contains('在')?'['+x.textContent+']':x.textContent)).join(' ')})()"
))
print("   右区节题:", 求值("(()=>{const e=document.querySelector('.设区 .设节题');return e?e.textContent:'（空）'})()"))

节名 = 求值("JSON.stringify([...document.querySelectorAll('.设钮')].map(x=>x.textContent))")
名单: list[str] = list(cast(list[str], json.loads(节名))) if isinstance(节名, str) else []
print("② 逐颗点过去:")
for 名 in 名单:
    求值(
        "(()=>{const b=[...document.querySelectorAll('.设钮')].find(x=>x.textContent===" + json.dumps(名) + ");"
        "if(b)b.click();return 'ok'})()"
    )
    time.sleep(1.4)
    此刻 = 求值(
        "(()=>{const e=document.querySelector('.设区 .设节题');const 亮=document.querySelector('.设钮.在');"
        "const 有保存=!!document.querySelector('.设区 .保条');"
        "const 出料=document.querySelector('.设区').innerText.replace(/\\s+/g,' ').length;"
        "return JSON.stringify({节题:e?e.textContent:'（空）',亮:亮?亮.textContent:'?',保存条:有保存,字:出料})})()"
    )
    print(f"   {名}:", 此刻)

print("③ 刷新后记不记得住:", end=" ")
发("Page.navigate", {"url": URL})
time.sleep(3.0)
求值("document.getElementById('设置钮').click()")
time.sleep(1.6)
print(求值(
    "(()=>{const 亮=document.querySelector('.设钮.在');const e=document.querySelector('.设区 .设节题');"
    "return '回到「'+(亮?亮.textContent:'?')+'」, 右区是「'+(e?e.textContent:'空')+'」'})()"
))

print("④ JS 报错:", 求值("JSON.stringify(window.__err||[])"))

# 切回数据库那节再截, 画面里有左栏 + 一节内容
求值(
    "(()=>{const b=[...document.querySelectorAll('.设钮')].find(x=>x.textContent==='数据库');"
    "if(b)b.click();return 'ok'})()"
)
time.sleep(2.5)
print("⑤ 截图前的位置:", 求值(
    "(()=>{const 亮=document.querySelector('.设钮.在');return 亮?亮.textContent:'?'})()"
))
shot = 发("Page.captureScreenshot", {"format": "png"})
数据 = shot.get("result", {}).get("data")
if isinstance(数据, str):
    with open(OUT, "wb") as f:
        f.write(base64.b64decode(数据))
    print(f"已存 {OUT}")
ws.close()

#!/usr/bin/env python3
"""验设置页的「数据库」节 —— 走 CDP(headless chrome 9333)。

验什么:
  ① 点「设置」能进设置页
  ② 概览那句从"正在读库…"变成真话(条数/来源数)
  ③ 表格真出料: 行数/表头/第一条/分页讯
  ④ 搜索走通: 结果头报的"走哪条路" + 命中条数
  ⑤ 全程无 JS 报错
最后把截图存下来。

用法: uv run --with websocket-client python check_db_page.py <url> <输出png> [宽] [高]
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
H = int(sys.argv[4]) if len(sys.argv) > 4 else 1500
搜词 = sys.argv[5] if len(sys.argv) > 5 else "切片算法是怎么定的"

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

print("① 点设置钮:", 求值(
    "(()=>{const b=document.getElementById('设置钮');if(!b)return '找不到设置钮';b.click();return '点了'})()"
))
time.sleep(1.2)
print("② 设置页可见:", 求值(
    "(()=>{const s=document.getElementById('设置页');return s? !s.hidden : '找不到设置页'})()"
))

概 = ""
for _ in range(40):  # 等概览那句从"正在读库…"变成真话
    概 = 求值("(()=>{const e=document.querySelector('.库概');return e?e.textContent:''})()") or ""
    if 概 and "正在读库" not in 概:
        break
    time.sleep(0.5)
print("③ 概览:", 概)

print("④ 表格行数:", 求值("document.querySelectorAll('.库表 tbody tr').length"))
print("   表头:", 求值("[...document.querySelectorAll('.库表 thead th')].map(e=>e.textContent).join(' / ')"))
print("   第一条:", 求值(
    "(()=>{const r=document.querySelector('.库表 tbody tr');"
    "return r? [...r.children].map(e=>e.textContent).join(' | ').slice(0,120):''})()"
))
print("   分页:", 求值("(()=>{const e=document.querySelector('.库页讯');return e?e.textContent:''})()"))
print("   页码钮:", 求值(
    "(()=>{const bs=[...document.querySelectorAll('.库页钮')];"
    "return bs.length+' 颗 -> '+bs.map(b=>(b.classList.contains('当')?'['+b.textContent+']':b.textContent)).join(' ')})()"
))
print("   首行 id(第1页):", 求值("(()=>{const r=document.querySelector('.库表 tbody tr');return r?r.children[0].textContent:'?'})()"))
# 点页码要真跳页(不然只是画了几颗按钮)
求值("(()=>{const b=[...document.querySelectorAll('.库页钮')].find(x=>x.textContent==='3');if(b)b.click();return 'ok'})()")
time.sleep(1.6)
print("   点第3页后:", 求值(
    "(()=>{const e=document.querySelector('.库页讯');const d=document.querySelector('.库页钮.当');"
    "return (e?e.textContent:'')+'  ｜ 当页钮='+(d?d.textContent:'?')})()"
))
print("   首行 id(第3页):", 求值("(()=>{const r=document.querySelector('.库表 tbody tr');return r?r.children[0].textContent:'?'})()"))
求值("(()=>{const b=[...document.querySelectorAll('.库页钮')].find(x=>x.textContent==='1');if(b)b.click();return 'ok'})()")
time.sleep(1.4)

print("⑤ 滚到数据库节:", 求值(
    "(()=>{const e=document.querySelector('.库概');if(!e)return '没有库概';e.scrollIntoView({block:'start'});return 'ok'})()"
))
time.sleep(0.6)

print("⑥ 填搜索词:", 求值(
    "(()=>{const b=document.querySelector('.库框.宽');if(!b)return '没有搜索框';"
    f"b.value={json.dumps(搜词)};return 'ok'}})()"
))
求值("(()=>{const bs=[...document.querySelectorAll('.库刷')];const b=bs[bs.length-1];if(b)b.click();return 'ok'})()")
讯 = ""
for _ in range(90):  # 语义路要过嵌入模型, 给足时间
    讯 = 求值("(()=>{const e=document.querySelector('.库果讯');return e?e.textContent:''})()") or ""
    if 讯 and "在搜" not in 讯:
        break
    time.sleep(0.5)
print("⑦ 搜索:", 讯)
print("   命中块:", 求值("document.querySelectorAll('.库果块').length"))
print("   首块头:", 求值("(()=>{const e=document.querySelector('.库果头');return e?e.textContent:''})()"))

print("⑧ JS 报错:", 求值("JSON.stringify(window.__err||[])"))

# 分两张截(视口内截, 不用 captureBeyondViewport —— 它会把整页拉成一张超长图):
#   表.png   = 概览 + 筛选栏 + 表格上半
#   搜.png   = 搜索栏 + 结果卡片
def 截(路径: str) -> None:
    图 = 发("Page.captureScreenshot", {"format": "png"})
    数 = 图.get("result", {}).get("data")
    if not isinstance(数, str):
        print("截图失败:", 图, file=sys.stderr)
        return
    with open(路径, "wb") as f:
        f.write(base64.b64decode(数))
    print(f"已存 {路径}")


求值(
    "(()=>{const e=[...document.querySelectorAll('.设节题')].find(x=>x.textContent==='数据库');"
    "if(!e)return '没找到数据库节';e.scrollIntoView({block:'start'});window.scrollBy(0,-70);return 'ok'})()"
)
time.sleep(0.6)
截(OUT)

if OUT.endswith(".png") and len(sys.argv) > 6:
    求值("(()=>{const e=document.querySelector('.库搜题');if(e)e.scrollIntoView({block:'start'});return 'ok'})()")
    time.sleep(0.6)
    截(sys.argv[6])
ws.close()

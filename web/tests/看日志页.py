#!/usr/bin/env python3
"""验设置页新增的两节：「日志」和「关闭」—— 走 CDP(headless chrome 9333)。

验什么:
  ① 左栏多了「日志」「关闭」两颗, 点亮跟不跟着走
  ② 日志节: 九类都列出来了(空类也要列); 点「主模型」右边必须出内容, 不许空框
  ③ 日志节: 换"最后 N 行"会真重拉 —— 行数跟着变
  ④ 日志节: 切走之后自动刷要停(计时器不收会一直在后台拉)
  ⑤ 关闭节: 三张卡三个按钮都在 —— ★ 这个脚本不真点(点了模型就停了, 清洗断,
     agent 也没了), 只验它在
  ⑥ 全程无 JS 报错;  两节各截一张图

用法: ./.venv/bin/python web/tests/看日志页.py <url> <输出前缀> [宽] [高]
前置: headless chrome 9333 起着;  web 在跑
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
H = int(sys.argv[4]) if len(sys.argv) > 4 else 1000

targets = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json/list"))  # noqa: S310
pages = [t for t in targets if t["type"] == "page"]
if not pages:
    print("没有可用的 page target", file=sys.stderr)
    sys.exit(1)
ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=60)
_编号 = 0
出错: list[str] = []


def 发(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    global _编号
    _编号 += 1
    ws.send(json.dumps({"id": _编号, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("method") == "Runtime.exceptionThrown":
            详 = msg.get("params", {}).get("exceptionDetails", {})
            描 = 详.get("exception", {}).get("description") or 详.get("text") or "?"
            出错.append(str(描).split("\n")[0])
        if msg.get("id") == _编号:
            return msg


def 求值(表达式: str) -> Any:
    r = 发("Runtime.evaluate", {"expression": 表达式, "returnByValue": True, "awaitPromise": True})
    return r.get("result", {}).get("result", {}).get("value")


def 截图(路径: str) -> None:
    d = 发("Page.captureScreenshot", {"format": "png"})
    图 = d.get("result", {}).get("data")
    if isinstance(图, str):
        with open(路径, "wb") as f:
            f.write(base64.b64decode(图))
        print("     已存", 路径)


def 点节(名: str) -> None:
    求值(
        "(()=>{const b=[...document.querySelectorAll('.设钮')].find(x=>x.textContent==="
        + json.dumps(名) + ");if(b)b.click();return !!b})()"
    )
    time.sleep(1.6)


发("Emulation.setDeviceMetricsOverride", {"width": W, "height": H, "deviceScaleFactor": 1, "mobile": False})
发("Page.enable")
发("Runtime.enable")
发("Log.enable")
发("Network.enable")
发("Network.setCacheDisabled", {"cacheDisabled": True})   # ★ 必须: 否则改完 app.js 还是拿旧的
发("Page.navigate", {"url": URL})
time.sleep(3.0)
求值("document.getElementById('设置钮').click()")
time.sleep(1.5)

print("① 左栏:")
print("   ", 求值("(()=>{const b=[...document.querySelectorAll('.设钮')];return b.length+' 颗: '+b.map(x=>x.textContent).join(' / ')})()"))

print()
print("② 日志节:")
点节("日志")
print("   分类:", 求值(
    "(()=>{const b=[...document.querySelectorAll('.日志类')];"
    "return b.length+' 类 → '+b.map(x=>x.querySelector('b').textContent+'('+(x.classList.contains('空')?'空':'有')+')').join(' ')})()"
))
求值("(()=>{const b=[...document.querySelectorAll('.日志类')].find(x=>x.dataset.名=='主模型');if(b)b.click();return !!b})()")
time.sleep(1.4)
print("   点「主模型」:", 求值(
    "(()=>{const p=document.querySelector('.日志框');const t=document.querySelector('.日志题');"
    "return (p?p.innerText.length:0)+' 字  |  题: '+(t?t.innerText:'（无）')})()"
))

print()
print("③ 换行数:")
for n in (100, 1000):
    求值(
        "(()=>{const s=document.querySelector('.日志选');s.value='" + str(n) + "';"
        "s.dispatchEvent(new Event('change'));return s.value})()"
    )
    time.sleep(1.4)
    print(f"   最后 {n} 行 →", 求值(
        "(()=>{const p=document.querySelector('.日志框');return p?p.innerText.split('\\n').length+' 行':'（无）'})()"
    ))

print()
print("④ 切走再回来(计时器该被收掉):")
求值("(()=>{const c=document.querySelector('.日志自动 input');if(c&&!c.checked)c.click();return !!c})()")  # 开自动刷
time.sleep(0.5)
print("   开自动刷后 window.__日志计时 是函数吗:", 求值("typeof window.__日志计时"))
点节("数据库")
print("   切走后:  计时器收了?", 求值("!window.__日志计时"), "  ← 该是 True（不收它就在后台一直拉）")
点节("日志")
print("   切回后:  ", 求值("typeof window.__日志计时"), "  ← 该是 function（这一节重新挂的）")
print("   自动刷那勾:", 求值("(()=>{const c=document.querySelector('.日志自动 input');return c?c.checked:'（无）'})()"), "  ← 该是 False（重造的 DOM, 没勾）")

print()
print("⑤ 关闭节(只验在, 不真点):")
点节("关闭")
print("   卡片:", 求值(
    "(()=>{const c=[...document.querySelectorAll('.关卡')];"
    "return c.length+' 张 → '+c.map(x=>x.querySelector('b').textContent+'/'+x.querySelector('.关钮').textContent).join('  ')})()"
))
截图(OUT + "-日志.png")
点节("日志")
截图(OUT + "-日志节.png")
点节("关闭")
截图(OUT + "-关闭节.png")

print()
print("⑥ JS 报错:", 出错 or "无")
ws.close()

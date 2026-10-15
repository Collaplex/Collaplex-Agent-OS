#!/usr/bin/env python3
"""验顶栏两个改动 —— 走 CDP(headless chrome 9333)。

验什么:
  ① 点侧栏历史条目 => 顶栏页眉跟着变成那一轮的问题
  ② 点 ☰ 按钮 / 按 Ctrl+B => 侧栏收起(body.收栏), 再点收回
  ③ 全程无 JS 报错

用法: uv run --with websocket-client python verify_topbar.py [url] [截图输出png]
前置: google-chrome --headless=new --disable-gpu --no-sandbox \
        --remote-debugging-port=9333 --remote-allow-origins='*' \
        --user-data-dir=/tmp/chrome-cdp-9333 --incognito about:blank &
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from typing import Any

import websocket  # type: ignore[reportMissingImports]

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8791/"
OUT = sys.argv[2] if len(sys.argv) > 2 else ""

targets = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json/list"))  # noqa: S310
pages = [t for t in targets if t["type"] == "page"]
if not pages:
    print("没有可用的 page target", file=sys.stderr)
    sys.exit(1)
ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=40)

序号 = 0


def 发(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    global 序号
    序号 += 1
    我的 = 序号
    ws.send(json.dumps({"id": 我的, "method": method, "params": params or {}}))
    while True:
        消息 = json.loads(ws.recv())
        if 消息.get("id") == 我的:
            return 消息


def 求值(表达式: str) -> Any:
    回 = 发("Runtime.evaluate", {"expression": 表达式, "returnByValue": True, "awaitPromise": True})
    return 回.get("result", {}).get("result", {}).get("value")


发("Page.enable")
发("Runtime.enable")
发("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
发("Page.navigate", {"url": URL})
time.sleep(3.0)

失败: list[str] = []


def 判(名: str, 通过: bool, 详情: str) -> None:
    print(f"  {'✓' if 通过 else '✗'} {名}  {详情}")
    if not 通过:
        失败.append(名)


print("══ ① 页眉跟着点中的历史走")
基线 = 求值("document.getElementById('页眉').textContent")
条数 = 求值("document.querySelectorAll('.史项').length") or 0
print(f"    基线页眉: {基线!r}   历史条目 {条数} 条")
if 条数 >= 2:
    期望 = 求值("(()=>{const b=document.querySelectorAll('.史项')[1];const t=b.title.trim();b.click();return t})()")
    time.sleep(1.2)
    现在 = 求值("document.getElementById('页眉').textContent")
    判("页眉变成第 2 条的问题", bool(现在) and 现在 != 基线, f"{现在!r} ← {期望[:30]!r}")
else:
    print("    （历史不足 2 条, 跳过）")

print("══ ② 收栏按钮 / Ctrl+B")
判("点之前没收栏", not (求值("document.body.classList.contains('收栏')") or False), "")
求值("document.getElementById('收栏钮').click()")
time.sleep(0.5)
判("点 ☰ 后收栏", bool(求值("document.body.classList.contains('收栏')")), "")
左移 = 求值("getComputedStyle(document.querySelector('.侧栏')).transform")
主区左距 = 求值("getComputedStyle(document.querySelector('.主区')).marginLeft")
判("主区让位归零", 主区左距 in ("0px", "0"), f"margin-left={主区左距}  transform={左移}")

# Ctrl+B 走真实按键事件, 不走 .click() —— 验的是那个快捷键真的挂上了
发("Input.dispatchKeyEvent", {"type": "keyDown", "key": "b", "code": "KeyB", "windowsVirtualKeyCode": 66, "modifiers": 2})
发("Input.dispatchKeyEvent", {"type": "keyUp", "key": "b", "code": "KeyB", "windowsVirtualKeyCode": 66, "modifiers": 2})
time.sleep(0.5)
判("Ctrl+B 收回", not (求值("document.body.classList.contains('收栏')") or False), "")

print("══ ③ 控制台")
控错 = 求值("JSON.stringify(window.__err||[])")
判("无 JS 报错", 控错 in ("[]", "null", None), f"{控错}")

if OUT:
    发("Runtime.evaluate", {"expression": "document.getElementById('收栏钮').click()"})
    time.sleep(0.6)
    shot = 发("Page.captureScreenshot", {"format": "png"})
    数据 = shot.get("result", {}).get("data")
    if isinstance(数据, str):
        import base64
        with open(OUT, "wb") as f:
            f.write(base64.b64decode(数据))
        print(f"    已存 {OUT}（收起态）")

print()
print(f"{'全过' if not 失败 else '有失败: ' + ', '.join(失败)}")
sys.exit(1 if 失败 else 0)

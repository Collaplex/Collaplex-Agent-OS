"""网页版端到端试水: 真发一问, 边流边拍 DOM。

验三件事(照 2026-10-07 拆出来的规矩):
  ① 流式全程页面里不出现裸 ```    ② 代码块在流式中就已经高亮/带复制按钮
  ③ 表格在流式中就已经是真 table  ④ 这轮完 .md-完成 挂上(动画关掉)
用法: uv run --with websocket-client python web/tests/e2e.py "要问的话" [出图目录]
"""

import json
import os
import sys
import time
import urllib.request

import websocket

地址 = "http://127.0.0.1:8791/?直进=1"  # ★ 直进=1: 不带它会被 app.js 弹到启动页, 页面上没有问框/发送按钮
问题 = sys.argv[1] if len(sys.argv) > 1 else (
    "用 markdown 给我一份《本地 agent 的取舍》短文：要有三级标题、一个三列对比表格、一段 python 代码、一个块级公式"
)
出图 = sys.argv[2] if len(sys.argv) > 2 else "/home/lou/.hermes/cache/scratch/web试水"

事实_JS = r"""
(() => {
  const 们 = document.querySelectorAll('.答案');
  const 末 = 们[们.length - 1];
  const 文 = 末 ? 末.innerText : '';
  return JSON.stringify({
    轮数: document.querySelectorAll('.轮').length,
    答字: 文.length,
    pre: 末 ? 末.querySelectorAll('pre').length : 0,
    代码头: 末 ? 末.querySelectorAll('.代码头').length : 0,
    高亮span: 末 ? 末.querySelectorAll('[class*="hljs-"]').length : 0,
    表: 末 ? 末.querySelectorAll('table').length : 0,
    公式: 末 ? 末.querySelectorAll('.katex').length : 0,
    新块: 末 ? 末.querySelectorAll('.md-新').length : 0,
    完成: 末 ? 末.classList.contains('md-完成') : false,
    裸围栏: 文.includes('```'),
    步骤: document.querySelectorAll('.过程体 .步').length,
    状态: (document.getElementById('状态行') || {}).textContent || '',
    尾巴: 文.slice(-70)
  });
})()
"""


class Cdp:
    def __init__(self, ws_url: str) -> None:
        self.ws = websocket.create_connection(ws_url, timeout=300)
        self.n = 0
        self.事件: list[dict] = []

    def cmd(self, method: str, **params: object) -> dict:
        self.n += 1
        编号 = self.n
        self.ws.send(json.dumps({"id": 编号, "method": method, "params": params}))
        while True:
            讯 = json.loads(self.ws.recv())
            if 讯.get("id") == 编号:
                return 讯
            self.事件.append(讯)

    def js(self, 表达式: str) -> str:
        回 = self.cmd("Runtime.evaluate", expression=表达式, returnByValue=True)
        try:
            return str(回["result"]["result"].get("value") or "")
        except Exception:
            return ""


def main() -> None:
    os.makedirs(出图, exist_ok=True)
    目标 = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json/list"))
    页 = [t for t in 目标 if t["type"] == "page"][0]
    cdp = Cdp(页["webSocketDebuggerUrl"])
    cdp.cmd("Page.enable")
    cdp.cmd("Runtime.enable")
    cdp.cmd("Log.enable")
    cdp.cmd("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
    cdp.cmd("Page.navigate", url=地址)
    time.sleep(3)

    错误 = [e for e in cdp.事件 if e.get("method") in ("Runtime.exceptionThrown", "Log.entryAdded")]
    print("页面加载后 JS 异常/错误日志:", len(错误))
    for e in 错误[:5]:
        print("   ", json.dumps(e, ensure_ascii=False)[:220])

    # 打字 + 真点发送按钮
    cdp.js("document.getElementById('问框').focus()")
    cdp.cmd("Input.insertText", text=问题)
    time.sleep(0.4)
    矩形 = cdp.js(
        "(() => { const r = document.getElementById('发送').getBoundingClientRect();"
        " return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2}); })()"
    )
    点 = json.loads(矩形)
    for 型 in ("mousePressed", "mouseReleased"):
        cdp.cmd(
            "Input.dispatchMouseEvent", type=型, x=点["x"], y=点["y"],
            button="left", clickCount=1, buttons=1,
        )
    print(f"已发问（点了发送按钮 {点['x']:.0f},{点['y']:.0f}）:", 问题[:60])

    起 = time.time()
    上一条 = ""
    时刻表 = [2, 4, 6, 9, 13, 18, 24, 32, 42, 55, 70, 90, 115, 145]
    for 秒 in 时刻表:
        while time.time() - 起 < 秒:
            time.sleep(0.2)
        条 = cdp.js(事实_JS)
        try:
            数据 = json.loads(条)
        except Exception:
            数据 = {}
        剪 = json.dumps(数据, ensure_ascii=False)
        if 剪 != 上一条:
            print(f"t={秒:>4}s {剪}", flush=True)
            上一条 = 剪
        if 数据.get("完成") and 数据.get("答字", 0) > 0:
            break
        if "这轮用时" in str(数据.get("状态", "")):
            break

    # 接着等这轮真结束(完成标记 / 状态行给出用时), 最多再等 5 分钟
    期限 = time.time() + 300
    while time.time() < 期限:
        条 = cdp.js(事实_JS)
        try:
            数据 = json.loads(条)
        except Exception:
            数据 = {}
        剪 = json.dumps(数据, ensure_ascii=False)
        if 剪 != 上一条:
            print(f"t={int(time.time() - 起):>4}s {剪}", flush=True)
            上一条 = 剪
        if 数据.get("完成") or "用时" in str(数据.get("状态", "")):
            break
        time.sleep(1.5)

    time.sleep(1.5)
    终 = json.loads(cdp.js(事实_JS) or "{}")
    print("\n=== 终态 ===")
    print(json.dumps(终, ensure_ascii=False, indent=1))
    图 = cdp.cmd("Page.captureScreenshot", format="png", captureBeyondViewport=True)
    路径 = os.path.join(出图, "终态.png")
    with open(路径, "wb") as fh:
        fh.write(__import__("base64").b64decode(图["result"]["data"]))
    print("截图:", 路径, os.path.getsize(路径) // 1024, "KB")
    剩 = [e for e in cdp.事件 if e.get("method") in ("Runtime.exceptionThrown", "Log.entryAdded")]
    print("全程 JS 异常/错误日志:", len(剩))
    for e in 剩[:6]:
        print("   ", json.dumps(e, ensure_ascii=False)[:200])


if __name__ == "__main__":
    main()

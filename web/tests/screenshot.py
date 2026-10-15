"""按元素裁切放大截图: 代码块/表格/公式/整屏。只读页面。"""

import base64
import json
import os
import sys
import time
import urllib.request

import websocket

出图 = sys.argv[1] if len(sys.argv) > 1 else "/home/lou/.hermes/cache/scratch/web试水"
os.makedirs(出图, exist_ok=True)


class Cdp:
    def __init__(self, ws_url: str) -> None:
        self.ws = websocket.create_connection(ws_url, timeout=120)
        self.n = 0

    def cmd(self, method: str, **params: object) -> dict:
        self.n += 1
        编号 = self.n
        self.ws.send(json.dumps({"id": 编号, "method": method, "params": params}))
        while True:
            讯 = json.loads(self.ws.recv())
            if 讯.get("id") == 编号:
                return 讯

    def js(self, 表达式: str) -> str:
        回 = self.cmd("Runtime.evaluate", expression=表达式, returnByValue=True)
        try:
            return str(回["result"]["result"].get("value") or "")
        except Exception:
            return ""


目标 = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json/list"))
页 = [t for t in 目标 if t["type"] == "page"][0]
cdp = Cdp(页["webSocketDebuggerUrl"])
cdp.cmd("Page.enable")
cdp.cmd("Runtime.enable")
cdp.cmd("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)

def 拍(名字: str, 选择器: str | None, 放大: float = 2.0) -> None:
    # 选择器后缀 @N 取第 N 个(0 起), 不给就取最后一个
    序号 = -1
    if 选择器 and "@" in 选择器:
        选择器, _, 尾 = 选择器.partition("@")
        序号 = int(尾)
    if 选择器 is None:
        盒 = {"x": 0, "y": 0, "width": 1280, "height": 900, "scale": 1}
    else:
        # ★ CDP 的 clip 是**页面坐标**(不是视口坐标): 量矩形必须加上滚动偏移,
        #   否则整张裁到空白区(上一次就是栽在这儿, 图只有 1 种颜色)。
        矩形 = cdp.js(
            "(() => { const es = document.querySelectorAll('%s');"
            " const el = es[%d < 0 ? es.length - 1 : %d];"
            " if (!el) return ''; const r = el.getBoundingClientRect();"
            " return JSON.stringify({x: r.x + window.scrollX, y: r.y + window.scrollY,"
            " w: r.width, h: r.height}); })()" % (选择器, 序号, 序号)
        )
        if not 矩形:
            print(f"   {名字}: 页面上没有 {选择器}, 跳过")
            return
        坐标 = json.loads(矩形)
        盒 = {
            "x": max(0, 坐标["x"] - 12), "y": max(0, 坐标["y"] - 12),
            "width": min(1280, 坐标["w"] + 24), "height": min(820, 坐标["h"] + 24),
            "scale": 放大,
        }
    图 = cdp.cmd("Page.captureScreenshot", format="png", clip=盒, captureBeyondViewport=True)
    路径 = os.path.join(出图, 名字 + ".png")
    with open(路径, "wb") as fh:
        fh.write(base64.b64decode(图["result"]["data"]))
    print(f"   {名字}: {路径} {os.path.getsize(路径) // 1024} KB")

拍("1-整屏", None)
拍("2-代码块-python", ".代码块@0", 2.0)
拍("2b-输出块", ".代码块", 2.0)
拍("3-表格", ".md table", 2.0)
拍("4-公式", ".数学块", 2.5)

#!/usr/bin/env python3
"""验"边流边吐": 真开页面、真发问, 一边跑一边量正文区 —— 看它**在跑的时候**长不长字。

★ 为什么单开一个探针: 页面在跑的时候到底有没有字, **光看最后的结果看不出来**。
  2026-10-09 这个坑走了两个极端 ——
    ① 先: exec 那轮的 `<调用>…</调用>` 协议标记原样流进正文区(一串原始md);
    ② 后: 干脆改成"跑的时候不写正文, 只在 final 一次成型" → 老板: "web的流式输出没了"。
  两次都是"DOM 里有内容"就能交差的错觉。这个探针量的是**时间轴**:
    首涨(正文第一次有字) 必须早于 完成, 并且途中采样点要一直有字;
    同时**正文里一次都不许出现裸协议标记**(整个跑的过程都盯着)。

用法:
    # 先把页面服务起起来(别占 8791 —— 那是老板手动起的): .venv/bin/python -m web.server --端口 8792
    uv run --no-project --with websocket-client python web/tests/验流式.py "问题" [地址]
    # 默认地址 http://127.0.0.1:8791/?直进=1 (直进=1 = 跳过启动页)
前置: Chrome 带 --remote-debugging-port=9333 --remote-allow-origins='*'
      google-chrome --headless=new --remote-debugging-port=9333 --remote-allow-origins='*' \\
        --user-data-dir=/tmp/cdp-9333 --window-size=1280,900 about:blank &
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from typing import Any, cast

import websocket  # type: ignore[reportMissingImports]

地址 = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8791/?直进=1"
问题 = sys.argv[1] if len(sys.argv) > 1 else "用一句话打个招呼"
最长等待 = 200  # 秒

# 一轮的现场: 正文多少字 / 完成没有 / 过程几步 / 正文里有没有裸标记
事实_JS = r"""
(() => {
  const 轮们 = document.querySelectorAll('.轮');
  const 末 = 轮们[轮们.length - 1];
  const 答 = 末 ? 末.querySelector('.答案') : null;
  const 文 = 答 ? 答.innerText : '';
  const 过程 = 末 ? 末.querySelector('details.过程') : null;
  return JSON.stringify({
    答字: 文.length,
    完成: 答 ? 答.classList.contains('md-完成') : false,
    步骤: 末 ? 末.querySelectorAll('.过程体 .步').length : 0,
    裸标记: /<调用>|<\/调用>|<tool_call|｜｜DSML｜｜|<dsml:|<｜tool/.test(文),
    尾巴: 文.slice(-36),
    状态: (document.getElementById('状态行') || {}).textContent || ''
  });
})()
"""


class Cdp:
    """跟 headless chrome 的一条 websocket 说话 —— 只留用到的几条命令."""

    def __init__(self, ws_url: str) -> None:
        self.ws = websocket.create_connection(ws_url, timeout=600)
        self.编号 = 0
        self.事件: list[dict[str, Any]] = []

    def cmd(self, method: str, **params: Any) -> dict[str, Any]:
        self.编号 += 1
        本 = self.编号
        self.ws.send(json.dumps({"id": 本, "method": method, "params": params}))
        while True:
            讯 = json.loads(self.ws.recv())
            if 讯.get("id") == 本:
                return 讯
            self.事件.append(讯)

    def js(self, 表达式: str) -> str:
        回 = self.cmd("Runtime.evaluate", expression=表达式, returnByValue=True)
        try:
            return str(回["result"]["result"].get("value") or "")
        except Exception:  # noqa: BLE001  (表达式抛错时拿不到 value, 当空处理)
            return ""


def main() -> int:
    页们 = [t for t in json.load(urllib.request.urlopen("http://127.0.0.1:9333/json/list")) if t["type"] == "page"]
    if not 页们:
        print("✗ 9333 上没找到页面 —— Chrome 起了没?")
        return 1
    cdp = Cdp(str(页们[0]["webSocketDebuggerUrl"]))
    for 条 in (("Page.enable", {}), ("Runtime.enable", {}), ("Log.enable", {})):
        cdp.cmd(str(条[0]), **cast(dict[str, Any], 条[1]))
    cdp.cmd("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
    cdp.cmd("Network.clearBrowserCache")  # 改过 app.js 的话, 别让内存缓存糊弄人
    cdp.cmd("Page.navigate", url=地址)

    # 等界面真出来(问框在才算好 —— 不然是启动页/白屏)
    期限 = time.time() + 25
    while time.time() < 期限 and not cdp.js("!!document.getElementById('问框') && !!document.getElementById('发送')"):
        time.sleep(0.5)
    if not cdp.js("!!document.getElementById('问框') && !!document.getElementById('发送')"):
        print("✗ 问框/发送按钮没出来 —— 页面没加载好:", cdp.js("document.title"))
        return 1
    错 = [e for e in cdp.事件 if e.get("method") in ("Runtime.exceptionThrown", "Log.entryAdded")]
    print(f"界面就绪 · 标题 {cdp.js('document.title')} · 加载期 JS 异常 {len(错)}")

    cdp.js("document.getElementById('问框').focus()")
    cdp.cmd("Input.insertText", text=问题)
    time.sleep(0.3)
    点 = json.loads(
        cdp.js(
            "(() => { const r = document.getElementById('发送').getBoundingClientRect();"
            " return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2}); })()"
        )
    )
    for 型 in ("mousePressed", "mouseReleased"):
        cdp.cmd("Input.dispatchMouseEvent", type=型, x=点["x"], y=点["y"], button="left", clickCount=1, buttons=1)
    print("已发问:", 问题[:60])

    起 = time.time()
    上一条 = ""
    首涨: float | None = None
    最大答字 = 0
    见过裸标记: list[str] = []
    跑着时有字: list[float] = []
    while time.time() - 起 < 最长等待:
        数据: dict[str, Any] = json.loads(cdp.js(事实_JS) or "{}")
        答字 = int(数据.get("答字") or 0)
        完成 = bool(数据.get("完成"))
        时刻 = round(time.time() - 起, 1)
        if 答字 > 0 and 首涨 is None:
            首涨 = 时刻
        if 答字 > 0 and not 完成:
            跑着时有字.append(时刻)
        最大答字 = max(最大答字, 答字)
        if 数据.get("裸标记"):
            见过裸标记.append(str(数据.get("尾巴")))
        剪 = json.dumps(数据, ensure_ascii=False)
        if 剪 != 上一条:
            print(f"  t={时刻:6.1f}s {剪}", flush=True)
            上一条 = 剪
        if 完成:
            break
        # ★ 采样间隔 0.2s（原来 1.0s）: 正文碎片是在模型"想完"之后约 0.4 秒内成串到齐的
        #   （实测短答 4 个 / 长答 14 个 answer 事件全落在 0.4 秒窗口里），1 秒采一次常常整段
        #   落在两次采样之间 → 只看到"0 字"和"完成时 21 字"，判成"流式没了"(2026-10-14 查实)。
        #   这是判据的采样窗口问题，不是流式坏了：服务端确实边收边吐。0.2s 实测短答 3/3 稳定过。
        time.sleep(0.2)

    print()
    好 = 首涨 is not None and bool(跑着时有字) and not 见过裸标记
    if 首涨 is None:
        print("✗ 跑完了正文一个字都没有 —— 流式没了")
    else:
        print(f"首涨 +{首涨}s · 跑着时就已有字的采样点 {跑着时有字[:8]} · 最大 {最大答字} 字")
    if 见过裸标记:
        print(f"✗ 正文里露了协议标记({len(见过裸标记)} 次), 例如: {见过裸标记[:2]}")
    print("✓ web 边流边吐 且 正文干净" if 好 else "✗ web 流式不合格")
    return 0 if 好 else 1


if __name__ == "__main__":
    raise SystemExit(main())

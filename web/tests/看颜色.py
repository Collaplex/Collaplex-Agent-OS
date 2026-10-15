"""读渲染后的实际颜色(客观核验高亮/表格/公式), 只读。"""

import json
import urllib.request

import websocket

JS = r"""
(() => {
  const 们 = document.querySelectorAll('.答案');
  const 末 = 们[们.length - 1];
  if (!末) return JSON.stringify({错: '页面上没有答案'});
  const 取色 = (el) => {
    const s = getComputedStyle(el);
    return {标签: el.tagName.toLowerCase(), 类: String(el.className).slice(0, 40),
            色: s.color, 底: s.backgroundColor, 字重: s.fontWeight};
  };
  const 记号 = Array.from(末.querySelectorAll('[class*="hljs-"]')).slice(0, 6).map(取色);
  const 码 = 末.querySelector('pre code');
  const 表头 = 末.querySelector('th');
  const 公式 = 末.querySelector('.katex');
  const 标题 = 末.querySelector('h1, h2, h3');
  return JSON.stringify({
    记号们: 记号,
    代码元素: 码 ? 取色(码) : null,
    首记号类名: 码 ? Array.from(码.querySelectorAll('span')).slice(0, 5).map((s) => s.className) : [],
    表头: 表头 ? 取色(表头) : null,
    公式: 公式 ? 取色(公式) : null,
    标题: 标题 ? 取色(标题) : null,
    主题表已载: !!getComputedStyle(document.documentElement),
    hljs样式条: Array.from(document.styleSheets).map((s) => s.href || '(内联)')
  }, null, 1);
})()
"""
目标 = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json/list"))
页 = [t for t in 目标 if t["type"] == "page"][0]
ws = websocket.create_connection(页["webSocketDebuggerUrl"], timeout=30)
ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                    "params": {"expression": JS, "returnByValue": True}}))
while True:
    讯 = json.loads(ws.recv())
    if 讯.get("id") == 1:
        print(讯["result"]["result"].get("value"))
        break

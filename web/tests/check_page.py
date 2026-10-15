"""看页面当前状态(调试用): 只读, 不发问。"""

import json
import sys
import urllib.request

import websocket

JS = r"""
(() => {
  const 们 = document.querySelectorAll('.答案');
  const 末 = 们[们.length - 1];
  const 文 = 末 ? 末.innerText : '';
  const 步 = Array.from(document.querySelectorAll('.过程体 .步')).slice(-6).map(
    (b) => (b.innerText || '').replace(/\s+/g, ' ').slice(0, 90));
  return JSON.stringify({
    轮数: document.querySelectorAll('.轮').length,
    答字: 文.length,
    pre: 末 ? 末.querySelectorAll('pre').length : 0,
    高亮: 末 ? 末.querySelectorAll('[class*="hljs-"]').length : 0,
    表: 末 ? 末.querySelectorAll('table').length : 0,
    公式: 末 ? 末.querySelectorAll('.katex').length : 0,
    完成: 末 ? 末.classList.contains('md-完成') : false,
    裸围栏: 文.includes('```'),
    状态: (document.getElementById('状态行') || {}).textContent,
    尾: 文.slice(-90),
    最近步骤: 步
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

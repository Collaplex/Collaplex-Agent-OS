"""验三件: 开页只摆最新一批 + 上翻懒加载 + 动态卸载 + 侧栏跳点; 顺带核设置页读数与"只写改动"。

跑法:
    cd ~/桌面/collaplex_agent
    uv run --no-project --with websocket-client python web/tests/验历史与设置.py
    WEB端口=8792 … python web/tests/验历史与设置.py      # 对临时实例跑(设置那几步自动跳过)
    WEB_PORT=8792 … python web/tests/验历史与设置.py      # 同上(有些 shell 不认中文变量名)

★ 前提: Chrome 带 --remote-debugging-port=9333; 服务在 8791(或 WEB端口 指的那个)。
★ 会先清浏览器缓存(同 URL 的脚本会留在内存缓存里, 不清就跑到旧代码上)。
★ 翻页一律用**真滚轮**(Input.dispatchMouseEvent) —— 程序性 scrollTo 会被页面"贴着底跟随"又拉回去,
  那不是 bug 是设计: 真用户就是滚轮, 滚轮才解除跟随。
★ 设置页那几步会真写设置, 所以只对 8791(自己的实例)跑; 指向临时端口时自动跳过。
"""

import base64
import json
import os
import time
import urllib.request
from typing import Any

import websocket

端口 = os.environ.get("WEB端口") or os.environ.get("WEB_PORT") or "8791"
主页 = f"http://127.0.0.1:{端口}/"
目标 = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json/list"))
页 = [项 for 项 in 目标 if 项.get("type") == "page"][0]
连 = websocket.create_connection(页["webSocketDebuggerUrl"], timeout=30)
号 = 0


def 发(法: str, 参: dict[str, Any]) -> dict[str, Any]:
    global 号
    号 += 1
    连.send(json.dumps({"id": 号, "method": 法, "params": 参}))
    while True:
        回 = json.loads(连.recv())
        if 回.get("id") == 号:
            return 回


def 取(回: dict[str, Any]) -> Any:
    """★ 读不到必须当场喊出来 —— 静默的 null 会让整份验收"全绿"地撒谎。"""
    果 = 回.get("result", {}).get("result", {})
    if "value" not in 果:
        print("   ！这一读没拿到值, 原始回包:",
              json.dumps(回.get("result", {}), ensure_ascii=False)[:500])
    return 果.get("value")


def 读(式: str) -> Any:
    return 取(发("Runtime.evaluate", {"returnByValue": True, "expression": 式}))


def 读异步(式: str) -> Any:
    """等 Promise 落地再取值 —— 直接 Runtime.evaluate 拿到的是个 Promise 壳(序列化成 {})。"""
    return 取(发("Runtime.evaluate", {"returnByValue": True, "awaitPromise": True, "expression": 式}))


def 拍(名: str) -> None:
    回 = 发("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
    open(f"/home/lou/.hermes/cache/scratch/web试水/{名}.png", "wb").write(base64.b64decode(回["result"]["data"]))
    print("   存:", 名)


def 滚(竖: int, 次数: int, 停: float = 0.05) -> None:
    """真滚轮: 指针先挪到视口中间(滚轮按指针位置命中), 再连发。"""
    发("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 600, "y": 450})
    for _ in range(次数):
        发("Input.dispatchMouseEvent",
          {"type": "mouseWheel", "x": 600, "y": 450, "deltaX": 0, "deltaY": 竖})
        time.sleep(停)


发("Page.enable", {})
发("Network.enable", {})
发("Network.clearBrowserCache", {})      # ★ 不清的话可能跑到缓存里的旧脚本
# ★ 2026-10-08 起 app.js 多了一层拦: 没走过启动页的会话会被送去 /启动(老板要的"软件先站启动页")。
#   测试要验的是**对话页**, 所以先留痕再回 / —— 不然读到的是启动页, 每个字段都是 null。
发("Page.navigate", {"url": f"{主页}启动"})
time.sleep(2)
发("Runtime.evaluate", {"expression": "sessionStorage.setItem('已过启动页','1'); location.replace('/'); 'ok'"})
time.sleep(3.5)

print(f"① 一打开(端口 {端口}): 只摆最新一批 + 落在最新那轮上:")
print("  ", json.dumps(读("""(() => ({
  侧栏条数: document.querySelectorAll('.史项').length,
  正文轮数: document.querySelectorAll('#流 .轮[data-序号]').length,
  挂着的: [...document.querySelectorAll('#流 .轮[data-序号]')].filter(r => !r.classList.contains('壳')).length,
  哨兵: document.getElementById('哨兵').textContent,
  空态藏了: document.getElementById('空态').hidden,
  序号: [...document.querySelectorAll('#流 .轮[data-序号]')].map(r => r.dataset.序号),
  // ★ 过程随轮入库(2026-10-09 补): 关掉再开, 那轮的过程得铺回来, 且默认折着
  带过程的轮: document.querySelectorAll('#流 .轮 .过程').length,
  过程步数: [...document.querySelectorAll('#流 .轮 .过程')].map(p => p.querySelectorAll('.步').length),
  过程都折着: [...document.querySelectorAll('#流 .轮 .过程')].every(p => !p.open),
  贴着底: document.documentElement.scrollHeight - (window.scrollY + window.innerHeight) < 8,
  最新那轮在视口里: (() => {
    const 们 = [...document.querySelectorAll('#流 .轮[data-序号]')];
    if (!们.length) return false;
    const b = 们[们.length - 1].getBoundingClientRect();
    return b.bottom > 0 && b.top < window.innerHeight;
  })()
}))()"""), ensure_ascii=False))

print("② 真滚轮翻到顶 → 该自动补更早的(一次 10 轮):")
滚(-1200, 40)
time.sleep(1.2)
print("  ", json.dumps(读("""(() => ({
  正文轮数: document.querySelectorAll('#流 .轮[data-序号]').length,
  最老的一轮: (() => {
    const 们 = [...document.querySelectorAll('#流 .轮[data-序号]')];
    return 们.length ? 们[0].dataset.序号 : null;
  })(),
  哨兵: document.getElementById('哨兵').textContent,
  滚动位置: Math.round(window.scrollY)
}))()"""), ensure_ascii=False))

print("③ 动态卸载: 离视口远的轮只留壳(内容掏空), 挂着的不超过 30:")
滚(-1200, 40)          # 继续顶, 把更早的也取回来
time.sleep(1.5)
print("  ", json.dumps(读("""(() => ({
  全部轮: document.querySelectorAll('#流 .轮[data-序号]').length,
  挂着的: [...document.querySelectorAll('#流 .轮[data-序号]')].filter(r => !r.classList.contains('壳')).length,
  空壳: document.querySelectorAll('#流 .轮[data-序号].壳').length,
  壳里的字: [...document.querySelectorAll('#流 .轮[data-序号].壳')].reduce((s, r) => s + (r.textContent || '').length, 0),
  视口里的壳: [...document.querySelectorAll('#流 .轮[data-序号].壳')].filter(r => {
    const b = r.getBoundingClientRect(); return b.bottom > 0 && b.top < window.innerHeight;
  }).length,
  DOM节点: document.getElementsByTagName('*').length
}))()"""), ensure_ascii=False))
拍("10-翻到顶-带空壳")

print("④ 点最老那条(序号 0) → 该把它的内容补回来再跳过去:")
发("Runtime.evaluate", {"expression": "document.querySelectorAll('.史项')[document.querySelectorAll('.史项').length-1].click()"})
time.sleep(2.5)
print("  ", json.dumps(读("""(() => {
  const 轮 = document.querySelector('#流 .轮[data-序号="0"]');
  return {
    正文轮数: document.querySelectorAll('#流 .轮[data-序号]').length,
    找到0轮: !!轮,
    "0轮是空壳吗": 轮 ? 轮.classList.contains('壳') : null,
    "0轮有字": 轮 ? (轮.innerText || '').length : 0,
    它在视口里: 轮 ? (() => { const b = 轮.getBoundingClientRect(); return b.bottom > 0 && b.top < window.innerHeight; })() : false,
    闪着: 轮 ? 轮.classList.contains('跳着') : false,
    高亮的跳点: document.querySelectorAll('.史项.当前').length,
    状态行: document.getElementById('状态行').textContent,
    视口里的壳: [...document.querySelectorAll('#流 .轮[data-序号].壳')].filter(r => {
      const b = r.getBoundingClientRect(); return b.bottom > 0 && b.top < window.innerHeight;
    }).length
  };
})()"""), ensure_ascii=False))
拍("11-跳到最老那轮")

if 端口 != "8791":
    print("\n(设置页那几步会真写设置 —— 指向临时端口, 跳过; 要验就对着 8791 跑)")
    连.close()
    raise SystemExit(0)

print("⑤ 设置页读数(★ 设置页已改分节: 左栏 `.设钮` 一节一节切, 不点进去读不到):")
发("Runtime.evaluate", {"expression": "document.getElementById('设置钮').click()"})
time.sleep(1.8)
print("  节钮全表:", json.dumps(读("[...document.querySelectorAll('.设钮')].map(b => b.textContent)"), ensure_ascii=False))
print("  接口节:", json.dumps(读("""(() => ({
  接口行: [...document.querySelectorAll('.设表行')].filter(r => r.dataset.组).map(r => ({
    组: r.dataset.组,
    端点: r.querySelector('.端点').value,
    模型: r.querySelector('.模型').value,
    密钥占位: r.querySelector('.密钥').placeholder
  })),
  保存钮: document.querySelector('.保钮') ? document.querySelector('.保钮').textContent : '无'
}))()"""), ensure_ascii=False))
发("Runtime.evaluate", {"expression": "[...document.querySelectorAll('.设钮')].find(b => b.textContent === '开关').click()"})
time.sleep(1.2)
print("  开关节:", json.dumps(读("""(() => ({
  开关: [...document.querySelectorAll('.开关行')].map(l => l.dataset.名 + '=' + l.querySelector('input').checked),
  节题: [...document.querySelectorAll('.设节题')].map(t => t.textContent)
}))()"""), ensure_ascii=False))
拍("12-设置页")

print("⑥ 在页面上真点一个开关再保存(外援自动触发 关→开, 验完自动拨回去):")
发("Runtime.evaluate", {"expression": """(() => {
  const 行 = [...document.querySelectorAll('.开关行')].find(l => l.dataset.名 === '外援自动触发');
  行.querySelector('input').click();
  document.querySelector('.保钮').click();
  return '已点';
})()"""})
time.sleep(2.5)
print("  ", json.dumps(读("""(() => ({
  果: [...document.querySelectorAll('.设果 .行')].map(s => s.textContent),
  开关现在: [...document.querySelectorAll('.开关行')].map(l => l.dataset.名 + '=' + l.querySelector('input').checked)
}))()"""), ensure_ascii=False))
拍("13-保存之后")

print("⑦ 收尾(把测试拨的开关拨回来, 别留脏):")
print("  ", json.dumps(读异步("""(async () => {
  await fetch('/api/设置', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ 开关: { '外援自动触发': false } })
  });
  return '已拨回';
})()"""), ensure_ascii=False))
print("⑧ 存档里到底有没有过程(直接问接口, 不看界面):")
print("  ", json.dumps(读异步("""(async () => {
  const 回 = await (await fetch('/api/历史/段?起=0&数=10')).json();
  const 段 = 回.段 || [];
  return {
    总轮数: 回.总,
    段轮数: 段.length,
    过程字段齐: 段.every(t => Array.isArray(t.过程)),
    各轮步数: 段.map(t => (t.过程 || []).length),
    窗口头一轮的步骤: (段.length ? (段[0].过程 || []) : []).map(s => s.kind + ':' + String(s.text).slice(0, 30))
  };
})()"""), ensure_ascii=False))
拍("14-存档里的过程")

连.close()

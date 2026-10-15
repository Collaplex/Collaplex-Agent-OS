#!/usr/bin/env python3
"""验设置页的「Skill」节 —— 走 CDP(headless chrome 9333)。

验什么:
  ① 名册真读出来: 每个 skill（盘上有几个就列几个，现 10 个）各自的开/关
  ② 关掉一个 -> 落盘(读 config/sub_agent.json 核) + 界面跟着变
  ③ ★ 关掉的那个真的从检索里消失了(sub_agent.search_skills 实测, 不是只看配置)
  ④ 搜索走通, 且结果里不含关掉的
  ⑤ 打开回来, 状态复原
  ⑥ 全程无 JS 报错;  最后截图

★ 第 ③ 步是这个页面的命门: 开关只写配置不生效 = 画了个假按钮。
  所以那边不靠界面自述, 直接拿 python 调 sub_agent.search_skills 要结果。

用法: ./.venv/bin/python web/tests/check_skills_page.py <url> <输出png> [宽] [高] [试的词]
前置: headless chrome 9333 起着
"""
from __future__ import annotations

import base64
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, cast

import websocket  # type: ignore[reportMissingImports]

URL = sys.argv[1]
OUT = sys.argv[2]
W = int(sys.argv[3]) if len(sys.argv) > 3 else 1440
H = int(sys.argv[4]) if len(sys.argv) > 4 else 1400
试词 = sys.argv[5] if len(sys.argv) > 5 else "把 PDF 转成 markdown"

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import sub_agent  # noqa: E402

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


def 配置里的开关() -> dict[str, Any]:
    路径 = ROOT / "config" / "sub_agent.json"
    原文: dict[str, Any] = json.loads(路径.read_text(encoding="utf-8"))
    段 = 原文.get("skills")
    return dict(cast(dict[str, Any], 段)) if isinstance(段, dict) else {}


def 检索里的名字(词: str) -> list[str]:
    配置 = sub_agent.load_config()
    return [str(c["name"]) for c in sub_agent.search_skills(词, dict(配置["skill_search"]))]


发("Emulation.setDeviceMetricsOverride", {"width": W, "height": H, "deviceScaleFactor": 1, "mobile": False})
发("Page.enable")
发("Runtime.enable")
发("Page.navigate", {"url": URL})
time.sleep(3.0)
求值("document.getElementById('设置钮').click()")
time.sleep(2.5)

print("① 名册:", 求值(
    "(()=>{const rs=[...document.querySelectorAll('.技行')];"
    "return rs.length+' 行: '+rs.map(r=>r.querySelector('.技名').textContent+'='+(r.querySelector('input').checked?'开':'关')).join(' ')})()"
))
print("   概览:", 求值("(()=>{const e=[...document.querySelectorAll('.库概')].pop();return e?e.textContent:''})()"))

# 关掉第一个
第一 = 求值("(()=>{const r=document.querySelector('.技行');return r?r.querySelector('.技名').textContent:''})()")
print(f"② 点关 {第一}:", 求值(
    "(()=>{const r=document.querySelector('.技行');const c=r.querySelector('input');"
    "if(c.checked)c.click();return '点了'})()"
))
time.sleep(2.2)
print("   配置里:", {k: v for k, v in 配置里的开关().items() if v is False} or "（没有 false）")
print("③ ★ 检索里还有它吗（词=%r）:" % 试词, 检索里的名字(试词))
print("   关掉的集合:", sorted(sub_agent.关掉的技能()))

# 搜一次（★ 按节定位: .库刷 在数据库节里也有, 不能用 [length-1] 抓最后一个）
求值(
    "(()=>{const s=[...document.querySelectorAll('.设节')].find(x=>x.querySelector('.设节题').textContent==='Skill');"
    "const b=s.querySelector('.库框.宽');if(b)b.value=" + json.dumps(试词) + ";return b?'ok':'没找到搜索框'})()"
)
求值(
    "(()=>{const s=[...document.querySelectorAll('.设节')].find(x=>x.querySelector('.设节题').textContent==='Skill');"
    "const bs=s.querySelectorAll('.库刷');if(bs.length)bs[bs.length-1].click();return '点了'+bs.length+'颗'})()"
)
讯 = ""
for _ in range(60):
    讯 = 求值(
        "(()=>{const s=[...document.querySelectorAll('.设节')].find(x=>x.querySelector('.设节题').textContent==='Skill');"
        "const e=s.querySelector('.库果讯');return e?e.textContent:''})()"
    ) or ""
    if 讯 and "在搜" not in 讯:
        break
    time.sleep(0.5)
print("④ 搜索:", 讯)
print("   命中:", 求值(
    "(()=>{const s=[...document.querySelectorAll('.设节')].find(x=>x.querySelector('.设节题').textContent==='Skill');"
    "return [...s.querySelectorAll('.库果头')].map(e=>e.textContent).join(' | ')})()"
))
print("⑤ 已关行样式:", 求值(
    "(()=>{const r=document.querySelector('.技行');return r?r.className:'?'})()"
))

# 打开回来
求值("(()=>{const r=document.querySelector('.技行');const c=r.querySelector('input');if(!c.checked)c.click();return 'ok'})()")
time.sleep(2.2)
print("⑥ 复原后配置:", {k: v for k, v in 配置里的开关().items() if v is False} or "（全开）")
print("   检索里:", 检索里的名字(试词))
print("⑦ JS 报错:", 求值("JSON.stringify(window.__err||[])"))

求值(
    "(()=>{const e=[...document.querySelectorAll('.设节题')].find(x=>x.textContent==='Skill');"
    "if(!e)return '没找到 Skill 节';e.scrollIntoView({block:'start'});window.scrollBy(0,-70);return 'ok'})()"
)
time.sleep(0.7)
shot = 发("Page.captureScreenshot", {"format": "png"})
数据 = shot.get("result", {}).get("data")
if isinstance(数据, str):
    with open(OUT, "wb") as f:
        f.write(base64.b64decode(数据))
    print(f"已存 {OUT}")
ws.close()

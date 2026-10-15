#!/usr/bin/env python3
"""任务编排 skill —— 审计图生成器（页1：原稿复刻 + 逐项判定；页2：缺口 / 复用 / 落库改造）

跑法: ./.venv/bin/python diagrams/gen_任务编排skill审计.py
导出: drawio -x -f png --no-sandbox -s 2 -o diagrams/任务编排skill-审计-pN-XXX.png --page-index N diagrams/任务编排skill-审计.drawio
★ 原稿 diagrams/任务编排skill.drawio 一个字不动。
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent

# ── 样式 ────────────────────────────────────────────────────────────────
块 = "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=12;"
判 = "rhombus;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;fontSize=12;"
主边 = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
        "exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;"
        "fontSize=11;fontColor=#333333;")
左回边 = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
          "exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;"
          "dashed=1;strokeColor=#cc0000;fontColor=#cc0000;fontSize=11;")
右回边 = 左回边.replace("exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;",
                        "exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=1;entryY=0.5;")
顶注 = "text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;fontSize=13;fontStyle=1;"
小注 = "text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;fontSize=10;fontColor=#666666;"
格头 = "rounded=0;whiteSpace=wrap;html=1;fillColor=#f0f0f0;strokeColor=#999999;fontSize=11;fontStyle=1;align=left;spacingLeft=6;"
格 = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#cccccc;fontSize=11;align=left;spacingLeft=6;spacingTop=2;"
格红 = 格.replace("fillColor=#ffffff", "fillColor=#fde7e7")
格黄 = 格.replace("fillColor=#ffffff", "fillColor=#fdf3d8")
格绿 = 格.replace("fillColor=#ffffff", "fillColor=#e5f5e5")

_cells: list[str] = []
_uids: set[str] = set()


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def node(i: str, text: str, x: float, y: float, w: float, h: float, kind: str = 块) -> None:
    assert i not in _uids, f"重复 id: {i}"
    _uids.add(i)
    _cells.append(
        f'<mxCell id="{i}" value="{esc(text)}" style="{kind}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>')


def edge(i: str, s: str, d: str, kind: str = 主边, label: str = "") -> None:
    assert i not in _uids, f"重复 id: {i}"
    _uids.add(i)
    _cells.append(
        f'<mxCell id="{i}" value="{esc(label)}" style="{kind}" edge="1" parent="1" '
        f'source="{s}" target="{d}"><mxGeometry relative="1" as="geometry" /></mxCell>')


def page(did: str, name: str, pw: int, ph: int) -> str:
    body = "\n".join("      " + c for c in _cells)
    xml = ('  <diagram name="%s" id="%s">\n'
           '    <mxGraphModel dx="1000" dy="800" grid="0" pageWidth="%d" pageHeight="%d">\n'
           '      <root>\n        <mxCell id="0" />\n        <mxCell id="1" parent="0" />\n'
           '%s\n      </root>\n    </mxGraphModel>\n  </diagram>')
    _cells.clear()
    _uids.clear()
    return xml % (esc(name), did, pw, ph, body)


# ── 页1：左边原稿复刻（同坐标同连线同标注），右边逐项判定台账 ──────────────
def build_p1() -> str:
    节点 = [
        ("调用", 354, 40), ("循环开始", 354, 150), ("获取任务单条", 354, 240),
        ("是否结束编排", 354, 330), ("生成任务清单", 354, 450), ("载入清单", 354, 545),
        ("执行序列", 354, 640), ("按顺序载入未完成的任务一条", 354, 740),
        ("确认是否完成", 354, 830), ("是否全部完成", 354, 930), ("返回结果", 354, 1040),
    ]
    for 名, x, y in 节点:
        node("n_" + str(y), 名, x, y, 150, 60)
    edge("e1", "n_40", "n_150")
    edge("e2", "n_150", "n_240")
    edge("e3", "n_240", "n_330")
    edge("e4", "n_330", "n_150", 左回边, "no")
    edge("e5", "n_330", "n_450", 主边, "yes")
    edge("e6", "n_450", "n_545")
    edge("e7", "n_545", "n_640")
    edge("e8", "n_640", "n_740")
    edge("e9", "n_740", "n_830")
    edge("e10", "n_830", "n_740", 左回边, "no")
    edge("e11", "n_830", "n_930", 主边, "yes")
    edge("e12", "n_930", "n_640", 右回边, "no")
    edge("e13", "n_930", "n_1040", 主边, "yes")

    node("t1", "左边 = 你的原稿（坐标 / 连线 / 标注原样）　右边 = 逐项判定", 0, 6, 630, 26, 顶注)

    # 台账三列
    列 = [(640, 230, "你的设计"), (875, 300, "我给的定法（判据 / 参数）"), (1180, 230, "为什么这么定")]
    for x, w, 名 in 列:
        node(f"h_{x}", 名, x, 0, w, 26, 格头)
    rows = [
        ("是否结束编排：谁判「攒够了」", "模型说够 或 到 20 条上限，谁先到算谁", "没判据就是靠自觉", 格黄),
        ("确认是否完成：谁判这一步好了", "主 agent 判（干活的模型不许自判自己）", "老板已拍；exec 只交回判据+真实产出", 格绿),
        ("no 回环（回上一条）", "单条重试上限 3 次，超了标「卡住」并停", "事不过三；静默跳下一条最危险", 格黄),
        ("生成清单后再没有回环", "加「要不要重策划」回环，上限 3 次", "上一代 stage_agent 有 RETRY_PLAN(≤3)", 格黄),
        ("清单落哪 / 什么字段", "冷库另开一张表 orchestra（见页2）", "库落盘才能被清洗管线接上", 格黄),
        ("这一轮跑完还是跨轮跑", "阻塞式：一轮里推完，进度实时可见", "老板已拍；形状照 Hermes 待办面板", 格绿),
        ("一轮只起一个 exec 任务", "要接通：「每步做完把主 agent 叫回来」", "main.py:795 continue 一出这轮就完", 格红),
        ("一步到底谁去干", "一步 = 一次 exec 任务（一声明跑几条命令）", "护住「一个一个来方便审计」", 格黄),
        ("返回结果返回什么", "清单全文 + 小结 + 卡住的单列", "看账不看叙述", 格黄),
        ("单对话能起几次 exec", "50 次（新增对话级计数）", "老板已拍；现状只有单任务 max_rounds 4", 格黄),
        ("跑一半断电了怎么办", "在飞库记账 + hash 幂等，双保险（见页2）", "现在的续干是隐式的，没账", 格黄),
    ]
    y = 40
    for 一, 二, 三, 样 in rows:
        node(f"r{y}a", 一, 640, y, 230, 54, 样)
        node(f"r{y}b", 二, 875, y, 300, 54, 样)
        node(f"r{y}c", 三, 1180, y, 230, 54, 样)
        y += 60
    node("收口", "红 = 必须动结构（本轮就改）· 黄 = 已定档参数（不认可划掉）· 绿 = 老板已拍", 640, y + 8, 770, 26, 小注)
    return page("p1", "1-你的稿+逐项判定", 1440, 1180)


# ── 页2：缺口 / 能复用 / 要新建 / 落库改造 ────────────────────────────────
def build_p2() -> str:
    node("t", "任务编排 skill —— 缺口、能复用、要新建、落库改造（2026-10-09）", 40, 10, 1000, 26, 顶注)
    x1, w1, x2, w2, x3, w3 = 40, 300, 355, 430, 800, 300
    y = 50

    def 段(题: str, 注: str = "") -> None:
        nonlocal y
        node(f"s{y}", 题 + (f"　—— {注}" if 注 else ""), x1, y, 1060, 30, 格头)
        y += 34

    def 行(a: str, b: str, c: str, 样: str = 格) -> None:
        nonlocal y
        node(f"a{y}", a, x1, y, w1, 52, 样)
        node(f"b{y}", b, x2, y, w2, 52, 样)
        node(f"c{y}", c, x3, y, w3, 52, 样)
        y += 58

    def 三列头() -> None:
        nonlocal y
        node(f"h{y}", "项", x1, y, w1, 26, 格头)
        node(f"h{y}b", "定法 / 现状（实测）", x2, y, w2, 26, 格头)
        node(f"h{y}c", "为什么 / 证据", x3, y, w3, 26, 格头)
        y += 30

    段("A. 照字面做会踩坑（本轮要动的结构）")
    三列头()
    行("确认是否完成没有判据归属", "已拍：主 agent 判；干活的模型不许自判自己", "自评 = 永远说「还没好」→ no 回环出不来", 格绿)
    行("no 回环没有上限", "单条重试 3 次，超了标「卡住」并停", "同一条会无限撞；停比静默跳过安全", 格黄)
    行("一次性生成清单后没有回环", "加「要不要重策划」，上限 3 次", "跑到第 3 步发现拆错就没救了", 格黄)
    行("一轮只允许起一个 exec 任务", "现在 main.py:795 continue，exec 干完这轮就结束", "7 步的清单照现在这套推不下去", 格红)
    行("清单 + 在飞事件没有落盘去处", "冷库另开两张表（见 C）", "断电丢单、清洗管线也看不见它", 格红)

    段("B. 之前搞过的，能复用（别另造）")
    三列头()
    行("原文备份", "PG rag_chunks 的 tier 1：24244 行 / 1105 个来源", "样例 ('实验-20260928-01','对话','用户')", 格绿)
    行("清洗后（对话层）", "同表 tier 2：21919 行 / 467 来源", "来自 corpus/hermes-history/*.md", 格绿)
    行("清洗后（精炼层）", "同表 tier 3：1957 行（知识 1690 / 概述 267）", "冷库那一档", 格绿)
    行("断点续干（隐式）", "refine.py:328 sha256(text)[:16] 按片去重", "重跑不重洗，但没游标、不记账", 格绿)
    行("心跳 / 洗不了的账 / 清洗看守", "refine-心跳.json · refine-待重洗.json · activity.json", "cron 一分钟一趟，看它还在不在跑", 格绿)
    行("原子写 / 进程隔离", "skill/timer/scripts/引擎.py:134-154", "抽成公用件，编排与定时共用", 格绿)

    段("C. 要新建的（四件）")
    三列头()
    行("运行内存库（在飞事件）", "新表 pipeline_flight：id / 来源 / 对话id / 段序号 / 状态 / 重试 / 起止 / 产物hash", "库里现在没有这张，断电后只能重扫", 格红)
    行("清单表", "新表 orchestra：id / 对话id / 序号 / 说明 / 做法 / 判据 / 状态 / 重试 / 产出 / 起止", "放冷库 → 清洗管线接得上", 格黄)
    行("对话级 exec 计数", "上限 50（跟对话走，落盘）", "现状只有单任务 max_rounds 4", 格黄)
    行("编排 → 清洗管线", "编排产出落成语料文件（原文备份），refine 扫描加一个源", "refine 现在只扫 corpus/hermes-history/", 格黄)

    段("D. 落库改造：定时任务一起改（老板：反正一起干了）")
    三列头()
    行("定时任务的表现在是 json 文件", "state/timers-<进程键>.json → PG 表 timers（进程键当一列）", "两个进程各一份的语义保持，改成 where 进程键", 格红)
    行("测试怎么改", "验定时.py 的沙盒从「临时目录」换成「沙盒 schema / 表前缀」", "测试不许碰生产表", 格红)
    行("同步什么", "定时任务.drawio（图里写着 state/timers-*.json）+ SKILL.md + metadata + README + CHANGELOG", "改代码不更文档会被抓", 格黄)
    行("断点续干给定时也开", "重挂时从库里读，过期条目标「补的」", "跟现在同语义，只是换个存放处", 格绿)

    return page("p2", "2-缺口-复用-落库", 1140, y + 40)


def main() -> None:
    p1, p2 = build_p1(), build_p2()
    out = HERE / "任务编排skill-审计.drawio"
    out.write_text('<mxfile host="app.diagrams.net">\n' + p1 + "\n" + p2 + "\n</mxfile>", encoding="utf-8")

    # 校验：逐页 断链 / 重复 id / 计数
    root = ET.parse(out).getroot()
    for d in root.findall("diagram"):
        cells = d.findall(".//mxCell")
        ids = [c.get("id") for c in cells if c.get("vertex") == "1" or c.get("edge") == "1"]
        assert len(set(ids)) == len(ids), f"{d.get('name')} 有重复 id"
        vs = {c.get("id") for c in cells if c.get("vertex") == "1"}
        bad = [(c.get("id"), c.get("source"), c.get("target")) for c in cells
               if c.get("edge") == "1" and (c.get("source") not in vs or c.get("target") not in vs)]
        v = sum(1 for c in cells if c.get("vertex") == "1")
        e = sum(1 for c in cells if c.get("edge") == "1")
        print(f"{d.get('name')}: 节点 {v} / 连线 {e} / 断链 {len(bad)}")
        assert not bad, f"断链: {bad}"
    print("写出", out)


if __name__ == "__main__":
    main()

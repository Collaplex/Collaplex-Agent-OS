# -*- coding: utf-8 -*-
"""生成 审计-设计对照.drawio（2 页）

页1：你的设计（原样复刻）+ 逐项审计（绿=照做 / 黄=做偏 / 红=没做）
页2：我实际实现的（五层骨架 + 旋钮片结构）+ 与你的图的差异标注

跑法：python3 审计-设计对照.py && drawio -x -f png --no-sandbox -o out.png --page-index 1 审计-设计对照.drawio
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

输出 = Path(__file__).parent / "审计-设计对照.drawio"


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("\n", "&#10;"))


def page(did: str, name: str, pw: int, ph: int, cells: list[str]) -> str:
    body = "\n".join("      " + c for c in cells)
    return ('  <diagram name="%s" id="%s">\n'
            '    <mxGraphModel dx="1200" dy="900" grid="0" pageWidth="%d" pageHeight="%d">\n'
            '      <root>\n        <mxCell id="0" />\n        <mxCell id="1" parent="0" />\n'
            '%s\n      </root>\n    </mxGraphModel>\n  </diagram>' % (esc(name), did, pw, ph, body))


def node(i: str, text: str, x: int, y: int, w: int, h: int, style: str) -> str:
    return ('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
            '<mxGeometry x="%d" y="%d" width="%d" height="%d" as="geometry" /></mxCell>'
            % (i, esc(text), style, x, y, w, h))


def edge(i: str, s: str, t: str, style: str, label: str = "") -> str:
    v = ' value="%s"' % esc(label) if label else ""
    return ('<mxCell id="%s"%s style="%s" edge="1" parent="1" source="%s" target="%s">'
            '<mxGeometry relative="1" as="geometry" /></mxCell>' % (i, v, style, s, t))


# 样式
模块 = "rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontStyle=1;fontSize=13;"
模块2 = "rounded=0;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;fontStyle=1;fontSize=13;"
绿 = "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=11;align=left;spacingLeft=6;"
黄 = "rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=11;align=left;spacingLeft=6;"
红 = "rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;fontSize=11;align=left;spacingLeft=6;"
标题 = "text;html=1;align=left;verticalAlign=middle;fontSize=16;fontStyle=1;fillColor=none;strokeColor=none;"
小字 = "text;html=1;align=left;verticalAlign=middle;fontSize=11;fontColor=#666666;fillColor=none;strokeColor=none;"
注 = "rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#999999;fontSize=11;align=left;spacingLeft=6;"
边 = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
     "exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;fontSize=11;")
边左 = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;"
       "entryX=0;entryY=0.5;entryDx=0;entryDy=0;fontSize=11;dashed=1;strokeColor=#b85450;fontColor=#b85450;")
边直 = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;exitX=0;exitY=0.75;exitDx=0;exitDy=0;"
       "entryX=0;entryY=0.25;entryDx=0;entryDy=0;fontSize=11;strokeColor=#9673a6;fontColor=#9673a6;")


def build_p1() -> str:
    c: list[str] = []
    c.append(node("t", "① 你的设计（diagrams/设计.drawio）＋ 我这边逐项审计（已按 10-07 原话修正读法）", 30, 20, 1000, 30, 标题))
    # —— 左：原样复刻他的四个模块与五条边
    c.append(node("s", "感受器", 60, 90, 120, 60, 模块))
    c.append(node("n", "cnn集群网络", 60, 230, 120, 60, 模块))
    c.append(node("e", "效应器", 60, 370, 120, 60, 模块))
    c.append(node("h", "激素调控", 230, 230, 110, 60, 模块2))
    c.append(edge("e1", "s", "n", 边, "①"))
    c.append(edge("e2", "n", "e", 边, "②"))
    c.append(edge("e3", "e", "s", ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;exitX=0;exitY=0.5;exitDx=0;"
                                   "exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;fontSize=11;"
                                   "strokeColor=#16a34a;fontColor=#16a34a;"), "③ 回路＝训练过程"))
    c.append(edge("e4", "s", "e", 边直, "④ 直连"))
    c.append(edge("e5", "h", "n", ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;exitX=0;exitY=0.5;exitDx=0;"
                                   "exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;fontSize=11;dashed=1;"
                                   "strokeColor=#9673a6;fontColor=#9673a6;"), "⑤ 调制"))
    c.append(node("a1", "感受器多少神经元连 cnn 集群「不知道，怎么连不知道，全靠训练」",
                  30, 150, 330, 50, 红))
    c.append(node("a2", "效应器多少神经元连 cnn 集群「不知道，怎么连不知道，全靠训练」",
                  30, 430, 330, 50, 红))
    c.append(node("a3", "★ 回路（效应器→感受器）不是数据流边，<b>它本身就是训练过程</b>："
                        "输出回灌成输入，一圈一圈地学（赫布，不是反向传播）；"
                        "CNN 只有一个、像单个神经元；预布线先把线撒到非常多；激素调节该调节的",
                  25, 505, 345, 90, 绿))

    # —— 右：逐项审计（一行一项，三列）
    x0, x1, x2, w0, w1, w2 = 400, 700, 900, 290, 190, 320
    c.append(node("h0", "你的设计（要什么）", x0, 90, w0, 30, 标题))
    c.append(node("h1", "我的实现（做了什么）", x1, 90, w1, 30, 标题))
    c.append(node("h2", "判定", x2, 90, w2, 30, 标题))
    rows: list[tuple[str, str, str, str]] = [
        ("① 回路（效应器→感受器）= 训练过程本身", "v1/v2 当成数据流边（迭代到稳定）→ 输入信息被压平", "🔴 读错＋实现错；已改真环境", 红),
        ("② CNN 只有一个，像单个神经元", "v1 做成 N 个可训身份键；v3 改成 1 个 1D 卷积（4 参数）共享", "🟢 已对齐（v3）", 绿),
        ("③ 预布线：训练开始先说撒到非常多", "v3 只有 32×13 = 416 条", "🟡 方向对，规模不够", 黄),
        ("④ 正常赫布学习（无反向传播）", "v3 生效：33.3% → 50.0%（不学那臂恒 33.3%）", "🟢 机制通了", 绿),
        ("⑤ 激素调节该调节的", "预算 0.02 未触发（改动量本来就小于预算）", "🟡 待扫小预算才有作用", 黄),
        ("感受器/效应器神经元数量靠训练", "感受器 32 维手工特征、效应器 13 族（数量仍是我定的）", "🔴 还没做到", 红),
        ("「感受器继续输入」", "v3 落实：环境反馈每步回灌成下次输入", "🟢 已对齐（v3）", 绿),
        ("三层模块存在 = 你讲的预布线", "已搭：反馈总线/情境快照/可塑图/效应器循环/赫布婴儿", "🟢 有，但名字是我起的", 绿),
    ]
    y = 130
    for i, (a, b, d, st) in enumerate(rows):
        c.append(node(f"r{i}a", a, x0, y, w0, 46, 注))
        c.append(node(f"r{i}b", b, x1, y, w1, 46, 注))
        c.append(node(f"r{i}c", d, x2, y, w2, 46, st))
        y += 52
    c.append(node("sum", "一句话：你的图讲的是「结构（连谁、用几个神经元）也靠训练长出来」；"
                         "我做的是「结构我设计好、只训权重」——两回事。",
                  400, y + 10, 800, 44, 红))
    return page("p1", "1-审计对照", 1180, max(700, y + 90), c)


def build_p2() -> str:
    c: list[str] = []
    c.append(node("t", "② 我实际实现的（现在是这个样子）", 30, 20, 900, 30, 标题))
    # 五层骨架
    c.append(node("g", "已搭的五层骨架（实验/行为旋钮-20261007/）", 30, 70, 560, 30, 标题))
    layers = [
        ("① 环境反馈总线", "2343 步 / 294 轮（每条命令→结构化事件）"),
        ("② 情境快照", "任务＋上一步动作＋上一步反馈＋已被拦几次"),
        ("③ 可塑图层", "边权随奖励变（判据贡献版：基线 39.9 → 只加强 47.2%）"),
        ("④ 旋钮（CNN）", "轮级行为 均衡 62.8%（桥一跳那档）"),
        ("⑤ 效应器循环", "婴儿循环：冷启动 33%→75%；预布线首轮 100%"),
    ]
    y = 110
    for i, (a, b) in enumerate(layers):
        c.append(node(f"L{i}", f"<b>{a}</b><br>{b}", 30, y, 560, 58, 注))
        y += 66
    c.append(node("pre", "＋ 预布线.py：手写「任务类 → 本命做法」反射弧（零数据）", 30, y + 6, 560, 40, 绿))

    # 旋钮片结构
    c.append(node("k", "④ 旋钮片（我设计的结构 ← 问题在这）", 630, 70, 520, 30, 标题))
    c.append(node("k1", "感受器<br>情境向量 1024 维（固定）", 640, 110, 240, 60, 红))
    c.append(node("k2", "N 个旋钮<br>身份键可训 ＋ 共享算子 ＋ 相邻一跳", 640, 210, 240, 70, 红))
    c.append(node("k3", "效应器<br>15 个命令族（固定）", 640, 320, 240, 60, 红))
    c.append(edge("k1e", "k1", "k2", 边))
    c.append(edge("k2e", "k2", "k3", 边))
    c.append(node("k4", "参数量：N=1→1.0万，N=128→14万（身份键占六成六）<br>"
                         "★ 参数量取决于单体大小＋是否共享，与旋钮个数几乎无关",
                  900, 110, 250, 90, 注))
    c.append(node("k5", "缺失（对比你的图）：<br>"
                         "🔴 感受器/效应器的神经元数量是我定死的<br>"
                         "🔴 连接拓扑是我设计的（不是训练出来的）<br>"
                         "🔴 没有 效应器→感受器 回路<br>"
                         "🔴 没有 激素调控 那一层",
                  900, 215, 250, 165, 红))

    # 结果与结论
    c.append(node("r", "这一版的学习结果（2343 步全量，纯 CPU／0 元）", 30, 480, 560, 30, 标题))
    c.append(node("r1", "轮级行为（动手/先问/直接答）　均衡 <b>62.8%</b>　🟢 可学", 30, 515, 560, 40, 绿))
    c.append(node("r2", "步级命令（它实际用了什么命令）　均衡 8.7~10%　🔴 不可学", 30, 563, 560, 40, 红))
    c.append(node("r3", "步级结果（这一步会不会被拦）　均衡 41~42%　🔴 不可学", 30, 611, 560, 40, 红))
    c.append(node("r4", "层错位：「会不会被拦」不是情境的函数，是<b>命令自己的函数</b>（语法闸查危险词），"
                         "所以拿情境预测它必然失败 → 旋钮该学<b>轮级行为</b>，不是步级命令/结果",
                  30, 661, 1120, 50, 黄))
    c.append(node("r5", "赫布婴儿（按你的图接进真环境）：不学 33.3%（恒）｜赫布 <b>33.3%→50.0%</b>｜"
                         "赫布＋激素 与赫布相同（预算 0.02 未触发）　⇒ 机制通了，规模还小、激素待扫",
                  30, 719, 1120, 44, 绿))
    return page("p2", "2-我实现的", 1180, 760, c)


xml = ('<mxfile host="app.diagrams.net">\n' + build_p1() + "\n" + build_p2() + "\n</mxfile>\n")
输出.write_text(xml, encoding="utf-8")

# —— 校验：逐页断链 + 重复 id + 计数
root = ET.parse(输出).getroot()
for d in root.findall("diagram"):
    cells = d.findall(".//mxCell")
    vids = [c.get("id") for c in cells if c.get("edge") != "1" and c.get("id") not in ("0", "1")]
    assert len(set(vids)) == len(vids), f"{d.get('name')} 有重复 id"
    bad: list[tuple[str | None, str, str | None]] = []
    for c in cells:
        if c.get("edge") == "1":
            for k in ("source", "target"):
                if c.get(k) not in vids:
                    bad.append((c.get("id"), k, c.get(k)))
    assert not bad, f"{d.get('name')} 断链 {bad}"
    n名 = sum(1 for c in cells if c.get("edge") != "1" and c.get("id") not in ("0", "1"))
    n边 = sum(1 for c in cells if c.get("edge") == "1")
    print(f"  页 {d.get('name')}: 节点 {n名} / 连线 {n边} / 断链 0 / 重复 id 0")
print(f"  写出 {输出}")

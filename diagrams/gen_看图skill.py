#!/usr/bin/env python3
"""生成 diagrams/看图skill.drawio —— 看图 skill 的架构图 (3 页)。

配套: diagrams/看图skill-架构.md (文字稿)
对标: diagrams/gen_联网搜索skill_补全版.py (同款写法与校验)

用法: .venv/bin/python diagrams/gen_看图skill.py
跑完自己校验: XML 能解析 / 断链 0 / 重复 id 0 / 每页节点·连线计数。
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
OUT = HERE / "看图skill.drawio"

# ── 形状 ─────────────────────────────────────────────────────────
KEEP = "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;"    # 蓝=现成件
ADD = "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;"     # 绿=新建
FIX = "rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;"     # 红=要改的
DIA = "rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;"
NOTE = ("text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
        "align=left;verticalAlign=top;fontSize=11;")
BOX = ("rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#666666;"
       "fontSize=11;align=left;verticalAlign=top;spacingLeft=8;spacingTop=6;")
HEAD = "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontStyle=1;"

# ── 边样式 ───────────────────────────────────────────────────────
MAIN = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
        "exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;")
SIDE_R = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
          "exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;")
SIDE_L = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
          "exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;")
RED = SIDE_R + "dashed=1;strokeColor=#cc0000;fontColor=#cc0000;"
DASH = MAIN + "dashed=1;strokeColor=#666666;"


def esc(text: str) -> str:
    """整个 value 一次过完 —— 里面的 HTML 片段也一起转义; 换行走 &#10; (裸换行会被压成空格)."""
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;")
                .replace("\n", "&#10;"))


def tiny(text: str) -> str:
    """节点里挂一行"对应实现"小字."""
    return f'<br><font style="font-size:9px" color="#666666">{text}</font>'


def node(nid: str, text: str, x: int, y: int, w: int, h: int,
         style: str, impl: str = "") -> str:
    body = text + (tiny(impl) if impl else "")
    return (f'<mxCell id="{nid}" value="{esc(body)}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')


def edge(eid: str, src: str, dst: str, style: str = MAIN, label: str = "") -> str:
    lab = f' value="{esc(label)}"' if label else ""
    return (f'<mxCell id="{eid}"{lab} style="{style}" edge="1" parent="1" '
            f'source="{src}" target="{dst}"><mxGeometry relative="1" as="geometry"/></mxCell>')


def page(did: str, name: str, pw: int, ph: int, cells: list[str]) -> str:
    body = "\n".join("      " + c for c in cells)
    return ('  <diagram name="%s" id="%s">\n'
            '    <mxGraphModel dx="1000" dy="800" grid="0" pageWidth="%d" pageHeight="%d">\n'
            '      <root>\n        <mxCell id="0" />\n        <mxCell id="1" parent="0" />\n'
            '%s\n      </root>\n    </mxGraphModel>\n  </diagram>'
            % (esc(name), did, pw, ph, body))


# ═══ 页 1: 它管什么 / 跟两家的分界 ═══════════════════════════════
def p1() -> str:
    c: list[str] = []
    n, e = node, edge

    c.append(n("p1_t", "看图 skill · 它管什么", 20, 8, 900, 30, NOTE))
    c.append(n("p1_r", "rag — 自家的事", 60, 60, 260, 70, KEEP, "项目代码 / 配置 / 语料"))
    c.append(n("p1_s", "search — 外面的事（页面上写的字）", 370, 60, 260, 70, KEEP,
               "HTML → 正文段落; 空壳页只回截图"))
    c.append(n("p1_v", "vision — 图里画的东西", 680, 60, 260, 70, ADD,
               "一张本地图片 → 文字; 不留库"))

    c.append(n("p1_q", "答案在哪？", 430, 175, 200, 56, DIA))
    c.append(e("p1a", "p1_q", "p1_r", SIDE_L, "在我家项目里"))
    c.append(e("p1b", "p1_q", "p1_s", MAIN, "在页面的字里"))
    c.append(e("p1c", "p1_q", "p1_v", SIDE_R, "只在图上"))

    c.append(n("p1_j",
               "接的是 search 留在那儿的一节：\n"
               "联网搜索 §1 主链有支路「汇总 --图片--> 返回结果（直接回）」，§4 又写「抓到了但清洗后没内容 → 只回截图」。\n"
               "图能回到手上，但全项目没有一处会读它 —— search 的 SKILL.md 只能把 shot_path 给出去。交给谁？这一节就是 vision。",
               60, 265, 880, 90, BOX, "diagrams/联网搜索skill-架构.md §1 / §4"))

    c.append(n("p1_k1",
               "硬约束一：图只在要用的时候看一眼\n"
               "· 不预读、不批量读、不因为顺手去读\n"
               "· search 取回来一张截图，不自动触发读图；要不要看由当时那件事决定",
               60, 380, 430, 110, FIX, "SKILL.md 触发条件: 该看 / 不该看"))
    c.append(n("p1_k2",
               "硬约束二：图不寄存\n"
               "· 不进会话历史、不进任何库、不落第二份\n"
               "· 那一次请求发出去，回来的是文字；图还在它原本躺着的盘上，哪儿也没多",
               520, 380, 430, 110, FIX, "见 §1 主链第 3/4 步"))
    c.append(n("p1_n",
               "为什么这样定：上下文是子 agent 的活，图这种大块的东西一旦进去就洗不干净（噪声税）。"
               "vision 只做一件事 —— 替当时那件事看一眼，把看到的写成字交出去。",
               60, 505, 880, 50, NOTE))

    return page("p1", "1-它管什么", 1000, 580, c)


# ═══ 页 2: 主链 5 步 + 两条路 ════════════════════════════════════
def p2() -> str:
    c: list[str] = []
    n, e = node, edge
    CX, CW, CH = 330, 230, 58

    c.append(n("p2_t", "看图 skill · 主链（5 步）＋ 两条路", 20, 8, 900, 30, NOTE))
    c.append(n("p2_1", "命令路由", CX, 60, CW, CH, KEEP, "main.py: 动作表 → see / status / retrieve"))
    c.append(n("p2_2", "拿图（在不在 / 后缀 / 大小）", CX, 150, CW, CH, ADD,
               "vision_core.check_image: 不通过 → 一句人话, 退出码 1"))
    c.append(n("p2_3", "看一眼 · 主路（云端视觉）", CX, 240, CW, CH, ADD,
               "see.py: .env 的 OPENAI_*（现在 mimo-v2.6-flash）"))
    c.append(n("p2_4", "看一眼 · 兜底（本地 qwen3-vl-8b）", CX, 330, CW, CH, ADD,
               "8790; ★起它必须带 --mmproj（视觉塔, 放 CPU 算）"))
    c.append(n("p2_5", "交出去（文字 ＋ 一行账）", CX, 470, CW, CH, ADD,
               "stdout 文字; logs/vision/ 记谁读的/耗时/图多大"))

    c.append(e("p2a", "p2_1", "p2_2"))
    c.append(e("p2b", "p2_2", "p2_3"))
    c.append(e("p2c", "p2_3", "p2_4", MAIN, "报错 / 超时 / 回来是空的"))
    c.append(e("p2d", "p2_4", "p2_5"))
    c.append(e("p2e", "p2_3", "p2_5", SIDE_R, "成了（主路好的时候不切兜底）"))

    c.append(n("p2_x1", "两条都不通 → 照实说", 640, 330, 260, 58, FIX,
               "「两条路都不通 —— 图里有什么, 我不知道 (绝不编)」; 退出码 1"))
    c.append(e("p2f", "p2_4", "p2_x1", RED, "还是不通"))
    c.append(n("p2_x2", "闸到顶 → 明说", 640, 150, 260, 58, FIX,
               "单轮 20 张（防钻牛角尖）; 退出码 2"))
    c.append(e("p2g", "p2_2", "p2_x2", RED, "看太多张了"))

    c.append(n("p2_n1",
               "第 3、4 步里那张图只活在这一次请求里：base64 进请求体，发出去，回来文字，图就散了。\n"
               "没有第 6 步「存起来」—— 这是刻意的。",
               60, 560, 460, 70, BOX))
    c.append(n("p2_n2",
               "单次一张图（看一眼就是一眼）；要看好几张就发几条命令。\n"
               "谁读的必须说出来（头部标 云端 / 本地）—— 不然出了错分不清是哪条路的账。",
               550, 560, 460, 70, BOX))
    c.append(n("p2_n3",
               "★ 不重试、不静默：拿不到内容就是拿不到，绝不编一段「图里大概写着…」糊过去。",
               60, 650, 950, 45, NOTE))

    return page("p2", "2-主链与两条路", 1060, 720, c)


# ═══ 页 3: 参数 / 闸 / 验收 / 加 skill 三步 ═════════════════════
def p3() -> str:
    c: list[str] = []
    n = node

    c.append(n("p3_t", "看图 skill · 参数 / 闸 / 验收 / 加它要做的三步", 20, 8, 980, 30, NOTE))

    c.append(n("p3_h1", "项", 40, 60, 220, 40, HEAD))
    c.append(n("p3_h2", "值", 270, 60, 200, 40, HEAD))
    c.append(n("p3_h3", "为什么", 480, 60, 560, 40, HEAD))
    行 = [
        ("单图大小上限", "8MB", "比 search 的单页 5MB 松一点（截图本来就大）, 但不能没闸"),
        ("允许后缀", ".jpg .jpeg .png .webp .gif .bmp", "视觉模型认的就这几样"),
        ("单轮次数上限", "100 次", "防发疯（跟 search 一个档; 2026-10-09 老板定: 单次对话上限 100）"),
        ("max_tokens", "1024", "描述一张图够了; 太小会被思考吃光"),
        ("超时", "180 秒", "跟外援同档"),
        ("落盘", "logs/vision/", "一行账（谁读的 / 耗时 / 图多大）＋ 一份产出 .md"),
    ]
    y = 110
    for a, b, d in 行:
        c.append(n(f"p3_r{y}_a", a, 40, y, 220, 48, BOX))
        c.append(n(f"p3_r{y}_b", b, 270, y, 200, 48, BOX))
        c.append(n(f"p3_r{y}_c", d, 480, y, 560, 48, BOX))
        y += 56
    c.append(n("p3_gate",
               "闸放程序侧（命令路由那一关硬拦）—— 跟 search 同款: 挂 SKILL.md 侧是软约束, 拦不住发疯。\n"
               "max_per_round 100 · round_gap_seconds 1800（停手超 30 分钟自动开新一轮）· state cache/budget.json",
               40, y + 8, 1000, 60, ADD, "vision_core.budget()"))

    y2 = y + 90
    c.append(n("p3_vh1", "编号", 40, y2, 70, 40, HEAD))
    c.append(n("p3_vh2", "验什么", 120, y2, 300, 40, HEAD))
    c.append(n("p3_vh3", "判据 / 实测", 430, y2, 610, 40, HEAD))
    验 = [
        ("V1", "主路能读", "拿真截图问「这页写的什么」→ 答对（实测认出截图是浙工院官网首页）"),
        ("V2", "兜底能读", "★实测: 加了 --mmproj 后本地也读出来了（38.2s/张, 视觉塔在 CPU 上算）"),
        ("V3", "兜底没带 mmproj", "★实测原话: HTTP 500 image input is not supported —— 不静默当成功"),
        ("V4", "图不在 / 后缀不认 / 超上限", "★实测三条都是一句人话, 退出码 1"),
        ("V5", "两条路都不通", "★实测: 「两条路都不通 —— 图里有什么, 我不知道 (绝不编)」"),
        ("V6", "空图 / 纯色图", "★实测: 全白 → 「图上没有文字, 整张图是空白的」; 纯色 → 报出颜色"),
        ("V7", "回归", "★实测: 自检 24/24, rag 检索不受影响"),
        ("V8", "命令库能被检索到", "★实测: skill 索引 10 条(含 vision)、命令库索引 2 条, find 能命中"),
    ]
    yy = y2 + 50
    for tag, what, crit in 验:
        c.append(n(f"p3_{tag}_a", tag, 40, yy, 70, 48, BOX))
        c.append(n(f"p3_{tag}_b", what, 120, yy, 300, 48, BOX))
        c.append(n(f"p3_{tag}_c", crit, 430, yy, 610, 48, BOX))
        yy += 56

    c.append(n("p3_steps",
               "加一个 skill 要做的三步（没有注册表）\n"
               "① 建命令库索引: .venv/bin/python skill/vision/scripts/retrieve.py index\n"
               "② 重扫 skill 索引: .venv/bin/python skill/skill_search/main.py index（扫各 SKILL.md frontmatter）\n"
               "③ 自检清单加它: selfcheck.py 的 wanted = (...) 加上 vision\n"
               "外加一处前置改动: start_models.sh 主模型那行加 --mmproj（mmproj-Qwen3-VL-8B-Instruct-F16.gguf 1.16G 已在盘上）",
               40, yy + 10, 1000, 130, BOX, "不加 mmproj, 兜底就是假的"))

    return page("p3", "3-参数闸与验收", 1080, yy + 160, c)


def main() -> None:
    xml = ('<mxfile host="app.diagrams.net">\n'
           + "\n".join([p1(), p2(), p3()])
           + "\n</mxfile>")
    OUT.write_text(xml, encoding="utf-8")

    root = ET.fromstring(xml)
    ok = True
    for d in root.findall("diagram"):
        name = d.get("name") or "?"
        cells = d.findall(".//mxCell")
        verts = [c for c in cells if c.get("edge") != "1" and c.get("id") not in ("0", "1")]
        edges = [c for c in cells if c.get("edge") == "1"]
        vids = [str(c.get("id")) for c in verts]
        dup = len(vids) - len(set(vids))
        broken = [c.get("id") for c in edges
                  if c.get("source") not in vids or c.get("target") not in vids]
        print(f"  {name:16s} 节点 {len(verts):2d}  连线 {len(edges):2d}  "
              f"重复id {dup}  断链 {len(broken)}")
        if dup or broken:
            ok = False
            print(f"     ✗ 重复: {[v for v in set(vids) if vids.count(v) > 1]} / 断链: {broken}")
    print(f"  {'✓ 校验通过' if ok else '✗ 校验没过'} -> {OUT}")


if __name__ == "__main__":
    main()

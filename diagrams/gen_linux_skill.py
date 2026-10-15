#!/usr/bin/env python3
"""linux-skill 审计版蓝图生成器 —— 在老板原稿(linux-skill.drawio)基础上补四处.

产出: linux-skill-v2-审计版.drawio  (一页)

相对原稿的改动, 按颜色分:
  蓝 = 原稿保留    红 = 必改 (照原稿接会走不通)
  黄 = 建议        绿 = 新增产物 / 新增步骤
每格都标了对应实现 (函数 / 文件), 照着落地就行.
"""

import os
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "linux-skill-v2-审计版.drawio")

# ---------- 样式 ----------
KEEP = "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;"
FIX = "rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;"
SUG = "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;"
NEW = "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;"
NOTE = ("text;html=1;align=left;verticalAlign=top;fontSize=11;fillColor=#f5f5f5;"
        "strokeColor=#999999;spacingLeft=6;")

DOWN = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
        "exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;")
RIGHT_IN = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
            "exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;")
# 自愈: 从主链右侧出去, 从「检索命令库」右侧回来(走主链右边的独立通道)
HEAL = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
        "exitX=1;exitY=0.25;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;"
        "dashed=1;strokeColor=#d79b00;fontColor=#d79b00;")
# 回主 agent: 从右列顶部出去, 从主 agent 右侧回来
RESEND = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
          "exitX=0.5;exitY=0;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;"
          "dashed=1;strokeColor=#b85450;fontColor=#b85450;")
# 其它失败: 从 M11 右侧偏下出去(跟自愈那条错开), 水平进右列
OTHER = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
         "exitX=1;exitY=0.75;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;"
         "dashed=1;strokeColor=#b85450;fontColor=#b85450;")

FONT = ('&lt;br&gt;&lt;font style=&quot;font-size:9px&quot; color=&quot;#666666&quot;&gt;'
        '%s&lt;/font&gt;')


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def cell(nid: str, text: str, x: int, y: int, w: int, h: int, style: str, ref: str = "") -> str:
    """一个方格; ref = 对应实现(函数/文件), 小字灰字挂在文案下面."""
    body = esc(text).replace("\n", "&lt;br&gt;")
    if ref:
        body += FONT % esc(ref)
    return ('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
            '<mxGeometry x="%d" y="%d" width="%d" height="%d" as="geometry"/></mxCell>'
            % (nid, body, style, x, y, w, h))


def note(nid: str, text: str, x: int, y: int, w: int, h: int) -> str:
    return ('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
            '<mxGeometry x="%d" y="%d" width="%d" height="%d" as="geometry"/></mxCell>'
            % (nid, esc(text).replace("\n", "&lt;br&gt;"), NOTE, x, y, w, h))


def edge(eid: str, src: str, dst: str, style: str = DOWN, label: str = "") -> str:
    lab = ' value="%s"' % esc(label) if label else ' value=""'
    return ('<mxCell id="%s"%s style="%s" edge="1" parent="1" source="%s" target="%s">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>' % (eid, lab, style, src, dst))


X_MAIN, W_MAIN = 520, 280
X_LEFT, W_LEFT = 110, 300
X_RIGHT, W_RIGHT = 1010, 380
Y0, STEP, H = 60, 92, 62

cells: list[str] = []
edges: list[str] = []


def my(i: int) -> int:
    return Y0 + i * STEP


# ---- 左列: 现有链路的前两关(原稿没画) ----
cells.append(cell("L1", "用户提问", X_LEFT, 60, W_LEFT, 50, KEEP))
cells.append(cell(
    "L2", "judge 判断「缺能力」？\n现在把「要动这台机器」判成不缺 → need=false，整条链走不到",
    X_LEFT, 140, W_LEFT, 76, FIX, "config/skills/judge.md　★必改：补一条「要动这台机器 = 缺能力」"))
cells.append(cell(
    "L3", "search_skills 挑 skill\n清单里只有 seek / rag / skill_search，挑不出 → 放弃支链",
    X_LEFT, 246, W_LEFT, 76, FIX, "main.py: find_skill_for / pick_skill　★必改：命令库要能被检索到"))

# ---- 主链 ----
cells.append(cell("M1", "主 agent：指定 skill + 声明要干的活",
                  X_MAIN, my(0), W_MAIN, H, KEEP, "main.py: pick_skill → 声明"))
cells.append(cell("M2", "下达 exec agent（提示词 = 命中的 SKILL.md）",
                  X_MAIN, my(1), W_MAIN, H, KEEP, "main.py → exec_agent.run_task"))
cells.append(cell("M3", "exec 命中 skill → 看 SKILL.md",
                  X_MAIN, my(2), W_MAIN, H, KEEP, "exec_agent.run_task(skill_path)"))
cells.append(cell("M4", "① 检索命令库（拿声明当查询）",
                  X_MAIN, my(3), W_MAIN, H, NEW, "新增　skill/linux/commands-index.json"))
cells.append(cell("M5", "② 取回相似条目：意图 → 命令 → 解释",
                  X_MAIN, my(4), W_MAIN, H, NEW, "新增　一片一条，不抄 man"))
cells.append(cell("M6", "③ 查看用法：参数 / 输出怎么读 / 本机实情 / 坑",
                  X_MAIN, my(5), W_MAIN, H, NEW, "新增"))
cells.append(cell("M7", "④ 危险闸：只读优先；写操作要声明里显式说",
                  X_MAIN, my(6), W_MAIN, H, SUG, "config/agent.json: exec.blocked_fragments（已有，接上）"))
cells.append(cell("M8", "⑤ 发送命令（模型出命令 JSON）",
                  X_MAIN, my(7), W_MAIN, H, KEEP, "exec_agent"))
cells.append(cell("M9", "⑥ 解释器执行（超时 180s）",
                  X_MAIN, my(8), W_MAIN, H, KEEP, "config/agent.json: exec.timeout_seconds"))
cells.append(cell("M10", "⑦ 返回数据（stdout + 退出码）",
                  X_MAIN, my(9), W_MAIN, H, KEEP, "exec_agent 回灌给模型"))
cells.append(cell(
    "M11", "⑧ 成功要过两道闸，都过才算成功\n① 程序：退出码 0\n② 模型：结果符合主 agent 声明的意图\n（127 / 2 / 126 及语法错 → 拼错类，自愈）",
    X_MAIN, my(10), W_MAIN, 132, FIX, "★退出码=程序判；对不对得上声明=模型判"))
cells.append(cell("M12", "⑨ 成功：摘要 + 关键行 + 完整输出落文件",
                  X_MAIN, my(11) + 66, W_MAIN, H, NEW, "新增　完整输出落 skill/linux/logs/"))
cells.append(cell("M13", "⑩ 回二层热库 → 下一轮子 agent 检索得到",
                  X_MAIN, my(12) + 66, W_MAIN, H, NEW, "sub_agent.save_to_tier2　★原稿缺这条成功回边"))

for a, b in (("M1", "M2"), ("M2", "M3"), ("M3", "M4"), ("M4", "M5"), ("M5", "M6"),
             ("M6", "M7"), ("M7", "M8"), ("M8", "M9"), ("M9", "M10"), ("M10", "M11")):
    edges.append(edge("e_%s_%s" % (a, b), a, b))

edges.append(edge("e_l1", "L1", "L2"))
edges.append(edge("e_l2", "L2", "L3"))
edges.append(edge("e_l3", "L3", "M1", RIGHT_IN, "缺能力 → 进左链"))
edges.append(edge("e_ok", "M11", "M12", DOWN, "成功"))
edges.append(edge("e_done", "M12", "M13"))
# 自愈: 走主链右侧的独立通道, 回到「检索命令库」(回归点是检索, 不是看用法)
edges.append(edge("e_heal", "M11", "M4", HEAL, "拼错类 → 自愈，限 3 次"))

# ---- 右列: 失败的第二条出路 ----
cells.append(cell(
    "R2", "⑫ 其它失败（权限 / 环境不满足 / 跑通但结果不对路）\n回二层热库 + 回主 agent 调整声明：只给 1 次\n还不行 → 向用户说明情况",
    X_RIGHT, my(10) + 16, W_RIGHT, 86, FIX, "原稿第 23 格　★现在 exec 跑完就交差，没有回主 agent 的通道，要新开"))
edges.append(edge("e_other", "M11", "R2", OTHER, "其它失败"))
edges.append(edge("e_resend", "R2", "M1", RESEND, "重新声明（限 1 次）"))

# ---- 右列上方: 附注(新增产物与做法) ----
cells.append(note("GT", "附注 · 新增产物与做法（不属于主流程）", X_RIGHT, 20, W_RIGHT, 26))
GREEN_BOXES = [
    ("G1", "新增产物 skill/linux/\nSKILL.md（规范）· metadata.json（声明式）\ncommands/*.md（一片一条）· commands-index.json",
     "跟 rag / skill_search 同款结构"),
    ("G2", "命令库怎么建\nrag 的 embed.json 加一层 tiers → 索引落 skill/linux/\n检索复用现成的两路（字符串 + 向量）",
     "零改检索代码（search_with_alias 那套照搬）"),
    ("G3", "命令库怎么长\n跑成功才回填「意图 → 命令」",
     "同「没真跑过命令的产出不入库」那条规矩"),
    ("G4", "热库别塞全量输出\nls 几百行会污染检索",
     "只存摘要 + 关键行 + 文件路径"),
]
for i, (gid, text, ref) in enumerate(GREEN_BOXES):
    cells.append(cell(gid, text, X_RIGHT, 60 + i * 100, W_RIGHT, 88, NEW, ref))
for i in range(len(GREEN_BOXES) - 1):
    edges.append(edge("e_g%d" % i, "G%d" % (i + 1), "G%d" % (i + 2), DOWN))

Y_NOTE = my(13) + 120
cells.append(note("LEG", "颜色：蓝 = 原稿保留　红 = 必改（照原稿接会走不通）　黄 = 建议（能跑但要收口）　绿 = 新增产物 / 新增步骤",
                  110, Y_NOTE, 1280, 26))
cells.append(note("N1", "① 两个重试合成一个总预算：自愈 3 次 + 回主 agent 1 次。分开算 = 3×3 = 9 轮，本地 11 tok/s，用户得等十分钟。",
                  110, Y_NOTE + 34, 1280, 30))
cells.append(note("N2", "② 跨轮闭环（不另画回环）：⑩ 进热库 → 下一轮子 agent recall 命中 → 回到左列「用户提问」。",
                  110, Y_NOTE + 70, 1280, 30))
cells.append(note("N3", "③ 自愈循环只回「检索命令库」不回「查看用法」—— 失败可能是条目取偏了，也可能是用法看错，回后者救不了前者。",
                  110, Y_NOTE + 106, 1280, 30))
cells.append(note("N4", "④ ⑧ 那两道闸分工别混：退出码是程序判（确定性），「结果符不符合指令意思」是模型判（语义）—— 两道都过才算成功，有一道不过就走失败。",
                  110, Y_NOTE + 142, 1280, 30))

XML = ('<mxfile host="app.diagrams.net">\n'
       '  <diagram name="linux-skill 审计版" id="linux-skill-v2">\n'
       '    <mxGraphModel dx="1200" dy="900" grid="0" pageWidth="1450" pageHeight="%d">\n'
       '      <root>\n        <mxCell id="0" />\n        <mxCell id="1" parent="0" />\n'
       '%s\n      </root>\n    </mxGraphModel>\n  </diagram>\n</mxfile>'
       % (Y_NOTE + 200, "\n".join("        " + c for c in cells + edges)))

with open(OUT, "w", encoding="utf-8") as fp:
    fp.write(XML)

# ---------- 自检: 断链 / 重复 id / 计数 ----------
root = ET.parse(OUT).getroot()
all_cells = root.findall(".//mxCell")
verts = [c for c in all_cells if c.get("edge") != "1" and c.get("id") not in ("0", "1")]
vids = [str(c.get("id")) for c in verts]
dup = {i for i in vids if vids.count(i) > 1}
dangling = [(c.get("id"), c.get("source"), c.get("target")) for c in all_cells
            if c.get("edge") == "1"
            and (c.get("source") not in vids or c.get("target") not in vids)]

print("文件: %s" % OUT)
print("节点 %d / 连线 %d" % (len(verts), len(all_cells) - len(verts)))
print("重复 id: %s" % (sorted(dup) if dup else "无"))
print("断链: %s" % (dangling if dangling else "无"))
print("红(必改) %d / 黄(建议) %d / 绿(新增) %d / 蓝(保留) %d"
      % (sum(1 for c in verts if FIX in (c.get("style") or "")),
         sum(1 for c in verts if SUG in (c.get("style") or "")),
         sum(1 for c in verts if NEW in (c.get("style") or "")),
         sum(1 for c in verts if KEEP in (c.get("style") or ""))))

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成品架构图生成器 —— 按「现在真跑着的这套」重绘（输出 成品架构.drawio，共 4 页）

页1 成品总览 · 谁在哪层（入口 / 三个 agent / skill 区（跟盘走）/ 两层记忆 / 四份配置 / 后台与 web）
页2 一轮对话 · 主链 + 两条链（标真实函数：prepare_skill / run_task / save_to_tier2）
页3 记忆与清洗 · 两层热冷库（PG 表 rag_chunks）+ 下水道三步 + 别名路 + 兜底
页4 启动·自检·打包 · cli.py → selfcheck 30 项 → 起模型 → main；pack_bundle → push_gitea

★ 与 diagrams/1.drawio（设计稿）的区别：那份是「Agent 即 OS」大版本，
  这份画的是一行行真在跑的代码（skill 清单跟盘走、库里的数现查，改代码后请重跑本脚本）。
  改图只改本脚本，勿手改 XML。
  跑法：./.venv/bin/python diagrams/gen_product.py
  导 PNG：drawio -x -f png --no-sandbox -o 成品-pN.png --page-index N 成品架构.drawio
          ★ 新版 drawio（≥27.0.2）的 --page-index 从 1 起，不是 0 —— 按 0 起导会整批串位
"""
from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from typing import Any, cast

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "成品架构.drawio")
ROOT = os.path.dirname(HERE)                                            # 项目根
SKILLS_DIR = os.path.join(ROOT, "skill")
sys.path.insert(0, os.path.join(SKILLS_DIR, "rag", "scripts"))          # 借项目自己的 store 认配置


def _读_json(path: str) -> object:
    """读一份 JSON; 读不动返回 None —— 图不该因为一份文件坏了就生成不了。"""
    try:
        with open(path, encoding="utf-8") as fh:
            return cast(object, json.load(fh))
    except (OSError, ValueError):
        return None


def 技能清单() -> list[tuple[str, str]]:
    """扫 skill/*/SKILL.md 的 frontmatter 取 (名字, 一句话) —— 图跟着盘走, 加 skill 不用改脚本。"""
    out: list[tuple[str, str]] = []
    for name in sorted(os.listdir(SKILLS_DIR)):
        doc = os.path.join(SKILLS_DIR, name, "SKILL.md")
        if not os.path.isfile(doc):
            continue
        try:
            with open(doc, encoding="utf-8") as fh:
                正文 = fh.read()
        except OSError:
            continue
        found = re.search(r"^description:\s*(.+)$", 正文, re.M)
        一句 = found.group(1).strip() if found else ""
        for 标点 in ("。", "；", "，", "：", "("):
            一句 = 一句.split(标点)[0]
        out.append((name, 一句[:28]))
    return out


def 库里的数() -> dict[str, str]:
    """现查库里的数: 二层 / 三层 / 别名 —— 查不到就返回空 (图照样生成, 那几格标「读不到」)。"""
    dsn = ""
    env = os.path.join(ROOT, ".env")
    if os.path.isfile(env):
        try:
            with open(env, encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("RAG_PG_DSN="):
                        dsn = line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            dsn = ""
    数: dict[str, int] = {}
    类型: list[str] = []
    if dsn:
        try:
            import psycopg
            with psycopg.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute("select tier, count(*) from rag_chunks group by tier")
                for tier, n in cast(list[tuple[Any, Any]], cur.fetchall()):
                    数[str(tier)] = int(cast(int, n))
                cur.execute("select kind, count(*) from rag_chunks where tier = 3 group by kind")
                for kind, n in cast(list[tuple[Any, Any]], cur.fetchall()):
                    类型.append(f"{kind} {int(cast(int, n))}")
        except Exception:  # noqa: BLE001 - 库没起不该拦着生成图
            数 = {}
    if not 数:
        print('[提醒] 没读到库里的数（psycopg 不在 / 库没起 / .env 里没 RAG_PG_DSN）'
              ' —— 图上那几格写「读不到」，用 ./.venv/bin/python 跑就有')
        return {}
    别名 = 0
    pack = _读_json(os.path.join(SKILLS_DIR, "rag", "scripts", "alias.json"))
    if isinstance(pack, dict):
        rows = cast(dict[str, Any], pack).get("items")
        if isinstance(rows, list):
            别名 = len(cast(list[Any], rows))
    return {
        "二层": str(数.get("2", 0)),
        "三层": str(数.get("3", 0)),
        "别名": str(别名),
        "类型": " / ".join(sorted(类型)) or "无",
    }


读不到: dict[str, str] = {"二层": "读不到", "三层": "读不到", "别名": "读不到", "类型": "读不到"}


def esc(s: str) -> str:
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace('\n', '&#10;'))


# ---------------- 连线样式 ----------------
MAIN = ('edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;'
        'html=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;')
SIDE_L = ('edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;'
          'html=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;')
SIDE_R = ('edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;'
          'html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;')
SIDE_R25 = SIDE_R.replace('exitY=0.5', 'exitY=0.25')      # 同一节点引两条分支时要错开出口高度
SIDE_R75 = SIDE_R.replace('exitY=0.5', 'exitY=0.75')
FAIL = SIDE_R + 'dashed=1;strokeColor=#cc0000;fontColor=#cc0000;'    # 异常往右
FAIL_L = SIDE_L + 'dashed=1;strokeColor=#cc0000;fontColor=#cc0000;'  # 异常往左
LOOP_R = ('edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;'
          'html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;'
          'dashed=1;strokeColor=#4472c4;fontColor=#4472c4;')
LOOP_L = ('edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;'
          'html=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;'
          'dashed=1;strokeColor=#4472c4;fontColor=#4472c4;')
DASH = ('edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;'
        'html=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=0.5;entryY=0.5;entryDx=0;entryDy=0;'
        'dashed=1;strokeColor=#888888;fontColor=#888888;')

# ---------------- 节点样式 ----------------
BOX = 'rounded=0;whiteSpace=wrap;html=1;fontSize=12;'
CODE = 'rounded=0;whiteSpace=wrap;html=1;fontSize=12;fontFamily=Courier New;'
DIAMOND = 'rhombus;whiteSpace=wrap;html=1;fontSize=12;'
CONTAINER = 'swimlane;html=1;startSize=30;fillColor=#f5f5f5;strokeColor=#666666;fontStyle=1;fontSize=12;'
HDR = 'rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontStyle=1;fontSize=13;'
NOTE = ('rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;'
        'align=left;verticalAlign=top;fontSize=11;spacingLeft=8;spacingTop=6;')
IO = 'rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=12;'


def v(nid: str, text: str, x: int, y: int, w: int, h: int, style: str = BOX, parent: str = '1') -> str:
    return (f'<mxCell id="{nid}" parent="{parent}" value="{esc(text)}" style="{style}" vertex="1">'
            f'<mxGeometry height="{h}" width="{w}" x="{x}" y="{y}" as="geometry"/></mxCell>')


def e(eid: str, src: str, dst: str, style: str = MAIN, label: str = '',
      pts: list[tuple[int, int]] | None = None, parent: str = '1') -> str:
    pt = ''
    if pts:
        pt = '<Array as="points">' + ''.join(f'<mxPoint x="{a}" y="{b}"/>' for a, b in pts) + '</Array>'
    lab = f' value="{esc(label)}"' if label else ''
    return (f'<mxCell id="{eid}" edge="1" parent="{parent}" source="{src}" target="{dst}" '
            f'style="{style}"{lab}><mxGeometry relative="1" as="geometry">{pt}</mxGeometry></mxCell>')


def page(did: str, name: str, pw: int, ph: int, cells: list[str]) -> str:
    body = '\n'.join('        ' + c for c in cells)
    return ('  <diagram name="%s" id="%s">\n'
            '    <mxGraphModel dx="900" dy="600" grid="1" gridSize="10" guides="1" tooltips="1" '
            'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="%d" pageHeight="%d" '
            'math="0" shadow="0">\n      <root>\n        <mxCell id="0" />\n'
            '        <mxCell id="1" parent="0" />\n%s\n      </root>\n'
            '    </mxGraphModel>\n  </diagram>') % (esc(name), did, pw, ph, body)


def hint(text: str) -> str:
    """给一格挂一行小字写「对应实现」—— 老板要的是照着图能落地。"""
    return f'<br><font style="font-size:9px" color="#666666">{text}</font>'


def side(text: str) -> str:
    """旁注专用抬头：讲清楚它不属于主流程，免得被当成流程节点。"""
    return f'{text}<br><font style="font-size:9px" color="#999999">（旁注 · 不属于主流程）</font>'


# ============ 页1：成品总览 ============
def build_p1() -> str:
    c: list[str] = []
    库 = 库里的数() or 读不到
    技能 = 技能清单()
    c.append(v('h1', '第三代 Collaplex Agent · 成品总览\n'
               '一条主线 + 两条链：主 agent 判断 / 子 agent 备料 / 执行 agent 动手\n'
               f'数字都取自当前库：二层 {库["二层"]} 片 · 三层 {库["三层"]} 条 · 别名 {库["别名"]} 行 · 命令库 100 条',
               120, 14, 820, 62, HDR))
    # ---- ① 入口层 ----
    c.append(v('EN', '① 入口层（一个命令管住所有启动方式）', 30, 92, 300, 240, CONTAINER))
    c.append(v('en1', 'cli.py · 总入口' + hint('collaplex-agent web / 自检 / 模型 / chat'), 14, 34, 272, 40, CODE, 'EN'))
    c.append(v('en2', 'selfcheck.py · 30 项' + hint('配置 / 模型 API / 依赖 / 库 / 代码 / 结构 / 索引'), 14, 78, 272, 40, CODE, 'EN'))
    c.append(v('en3', 'start_models.sh' + hint('本地模型：主 8790（带视觉塔）· 向量 8199'), 14, 122, 272, 40, CODE, 'EN'))
    c.append(v('en4', 'watchdog.py · 看门狗' + hint('盯 8790 / 8199 / 8791 / PG，挂了拉回来'), 14, 166, 272, 40, CODE, 'EN'))
    # ---- ② agent 层 ----
    c.append(v('AG', '② agent 层（三个入口，各管一摊）', 30, 342, 300, 268, CONTAINER))
    c.append(v('ag1', 'main.py · 主 agent' + hint('StreamingChatAssistant / find_tail_json'), 14, 34, 272, 48, CODE, 'AG'))
    c.append(v('ag2', 'sub_agent.py · 子 agent' + hint('prepare_skill / recall_memory / ContextBudget'), 14, 90, 272, 48, CODE, 'AG'))
    c.append(v('ag3', 'exec_agent.py · 执行 agent' + hint('run_task / blocked_reason / run_command'), 14, 146, 272, 48, CODE, 'AG'))
    c.append(v('ag4', '模型由 .env 定' + hint('主线三支：主模型 / 执行体 / 子 agent（没配就回落主模型）'), 14, 200, 272, 34, BOX, 'AG'))
    # ---- ③ skill 层（清单跟盘走：扫 SKILL.md 的 frontmatter）----
    c.append(v('SK', f'③ skill 区（{len(技能)} 个；SKILL.md 给模型 / metadata.json 给程序）', 30, 620, 300, 324, CONTAINER))
    c.append(v('sk_all', '\n'.join(f'{名} · {一句}' for 名, 一句 in 技能), 14, 34, 272, 256, NOTE, 'SK'))
    # ---- ④ 记忆库 ----
    c.append(v('MEM', '④ 记忆与检索（PG 表 rag_chunks，程序自己管）', 370, 92, 330, 236, CONTAINER))
    c.append(v('m1', 'rag_chunks · 二层热库' + hint(f'{库["二层"]} 片 —— 这一轮的原话，切片后嵌向量'), 14, 34, 302, 44, CODE, 'MEM'))
    c.append(v('m2', 'rag_chunks · 三层冷库' + hint(f'{库["三层"]} 条 = {库["类型"]}'), 14, 78, 302, 44, CODE, 'MEM'))
    c.append(v('m3', 'alias.json · 别名表' + hint(f'{库["别名"]} 行 —— 检索第二路（字符串包含）'), 14, 122, 302, 44, CODE, 'MEM'))
    c.append(v('m4', 'commands-index.json' + hint('5 个库 / 100 条命令的检索索引'), 14, 166, 302, 36, CODE, 'MEM'))
    # ---- ⑤ 配置区 ----
    c.append(v('CF', '⑤ 配置区（不写死在代码里）', 370, 338, 330, 258, CONTAINER))
    c.append(v('c1', 'config/agent.json' + hint('超时 / 轮数 / 黑名单 / 宽目标 / 界面文字'), 14, 34, 302, 38, CODE, 'CF'))
    c.append(v('c2', 'config/sub_agent.json' + hint('检索参数 + 四个角色的提示词'), 14, 72, 302, 38, CODE, 'CF'))
    c.append(v('c3', 'config/think_routing.json' + hint('思考路由：关键词规则 / 各方言 / 默认档'), 14, 110, 302, 38, CODE, 'CF'))
    c.append(v('c4', 'config/outsource_trigger.json' + hint('外援自动触发：三条判据 + 否决词表（默认关）'), 14, 148, 302, 38, CODE, 'CF'))
    c.append(v('c5', 'config/skills/*.md · 9 份' + hint('plan / judge / pick / exec / nudge / wrapup + 三份清洗'), 14, 186, 302, 38, CODE, 'CF'))
    # ---- ⑥ 后台与外围 ----
    c.append(v('BG', '⑥ 后台与外围', 370, 606, 330, 284, CONTAINER))
    c.append(v('bg1', 'refine.py · 清洗管线' + hint('cron 每分钟 + flock；静默 20 分钟才动'), 14, 34, 302, 36, CODE, 'BG'))
    c.append(v('bg2', 'state/ · 心跳与账' + hint('refine-心跳.json / refine-待重洗.json'), 14, 70, 302, 36, CODE, 'BG'))
    c.append(v('bg3', 'web/server.py · :8791' + hint('同一条链，浏览器里说话（判定 / 挑 skill / 递交 exec 调现成函数）'), 14, 106, 302, 36, CODE, 'BG'))
    c.append(v('bg4', '本地兜底.sh' + hint('主路不通 → 自动落本地 8790 那支'), 14, 142, 302, 36, CODE, 'BG'))
    c.append(v('bg5', 'pack_bundle.sh → dist/*.tar.zst' + hint('自带解释器 + 依赖，不建 venv'), 14, 178, 302, 36, CODE, 'BG'))
    c.append(v('bg6', 'push_gitea.sh · 一 skill 一仓' + hint(f'subtree split；{len(技能) + 1} 个公开仓（主仓 + {len(技能)} skill）'), 14, 214, 302, 36, CODE, 'BG'))
    # ---- 右侧两块旁注 ----
    c.append(v('fl', side('这轮怎么串起来') + '\n'
               '用户提问 → main.py 渲染/拦截 → 子 agent 检索 + 拼 skill → 模型 →\n'
               '主 agent 判断（够不够 / 要交办什么）→ 执行 agent 动手 → 产出入二层热库 →\n'
               '静默 20 分钟后被清洗成冷库知识 → 下一轮又能检索到',
               740, 92, 250, 190, NOTE))
    c.append(v('wc', side('谁在哪层') + '\n'
               '· 记忆：程序管（PG 表 rag_chunks，模型不碰）\n'
               '· 判断：模型管（提示词在 config/skills）\n'
               '· 动手：执行 agent 管（护栏在代码里）\n'
               '★ 提示词管不住模型 —— 兜底一律放程序里',
               740, 300, 250, 190, NOTE))
    # ---- 连线 ----
    c.append(e('p1e1', 'EN', 'AG', MAIN, '拉起'))
    c.append(e('p1e2', 'AG', 'SK', MAIN, '拼 / 调'))
    c.append(e('p1e3', 'AG', 'MEM', SIDE_R25, '读写'))
    c.append(e('p1e4', 'MEM', 'CF', MAIN, ''))
    c.append(e('p1e5', 'CF', 'BG', MAIN, ''))
    c.append(e('p1e6', 'BG', 'wc', SIDE_R75, '落盘 / 心跳'))
    return page('p1', '1-成品总览', 1020, 990, c)


# ============ 页2：一轮对话 ============
def build_p2() -> str:
    c: list[str] = []
    c.append(v('h2', '一轮对话 · 主链 + 两条链（函数名就是真在跑的那个）\n'
               '输入：用户提问 ｜ 输出：正文 + 思考过程（+ 执行结果）', 80, 14, 670, 56, HDR))
    c.append(v('s1', '用户提问', 320, 92, 190, 44, IO))
    c.append(v('s2', 'main.py 渲染流式回答' + hint('StreamingChatAssistant / render_stream'), 300, 166, 230, 50, CODE))
    c.append(v('s3', '末尾 json 拦截' + hint('find_tail_json —— 正文与数据分离'), 300, 246, 230, 50, CODE))
    c.append(v('s4', 'sub_agent.prepare_skill 备料' + hint('检索：recall_memory + search_skills'), 285, 326, 260, 56, CODE))
    c.append(v('s4b', '思考路由判定' + hint('decide_think：规则 → 模型 → 默认（保守关）'), 600, 326, 220, 62, BOX))
    c.append(v('s5', '拼 skill 进上下文' + hint('ContextBudget 40% · assemble / degrade'), 300, 412, 230, 50, CODE))
    c.append(v('s6', '模型出回答' + hint('本地 Qwen3-VL-8B（或 MiMo 云）'), 300, 492, 230, 50, CODE))
    c.append(v('d1', '这轮要交办吗?', 290, 572, 250, 84, DIAMOND))
    c.append(v('s7', '执行 agent 动手' + hint('exec_agent.run_task / run_command'), 300, 692, 230, 50, CODE))
    c.append(v('s8', '产出入二层热库' + hint('sub_agent.save_to_tier2 → vector-index'), 290, 772, 250, 50, CODE))
    c.append(v('s9', '本轮结束（回答交给用户）', 295, 852, 240, 46, IO))
    # 右列：执行链（护栏 → 落盘）
    c.append(v('g1', '执行前过护栏' + hint('blocked_reason · 黑名单 / 递归删 / 宽目标'), 600, 660, 220, 60, BOX))
    c.append(v('g2', '复读掐断 / 催促' + hint('looks_degenerate · 轮数≤4 · 催≤2'), 600, 736, 220, 60, BOX))
    c.append(v('g3', '产出落盘' + hint('exec_agent.save_output → logs/exec/'), 600, 812, 220, 50, BOX))
    # 左列：思考过程 + 出错
    c.append(v('t1', '思考过程单独渲染' + hint('ui.reasoning_label = 思考过程'), 55, 492, 210, 60, BOX))
    c.append(v('f1', '这轮没跑成' + hint('explain_model_error —— 说人话'), 55, 620, 210, 60, BOX))
    c.append(v('nta', '★ 主链只做「渲染 + 判断 + 交办」，不自己动手\n'
                '★ 判定那步坏了不许静默消失：拿用户原话兜 + 派最相关候选\n'
                '★ 执行完的产出立刻回二层热库 → 下一轮检索得到\n'
                '★ 思考开关按任务路由（硬规则 → 模型 → 默认）：子 agent 判、主 agent 用\n'
                '★ 「下一轮」＝ 从最上面「用户提问」再来一遍（同一套链）',
                40, 906, 470, 118, NOTE))
    # 连线
    c.append(e('q1', 's1', 's2', MAIN))
    c.append(e('q2', 's2', 's3', MAIN))
    c.append(e('q3', 's3', 's4', MAIN))
    c.append(e('q4', 's4', 's5', MAIN))
    c.append(e('q5', 's5', 's6', MAIN))
    c.append(e('q6', 's6', 'd1', MAIN))
    c.append(e('q7', 'd1', 's7', MAIN, '是 · 交办'))
    c.append(e('q8', 'd1', 's9', SIDE_L, '否 · 直接答'))
    c.append(e('q9', 's7', 'g1', SIDE_R, ''))
    c.append(e('q10', 'g1', 'g2', MAIN, ''))
    c.append(e('q11', 'g2', 'g3', MAIN, ''))
    c.append(e('q12', 'g3', 's8', DASH, ''))
    c.append(e('q13', 's8', 's9', MAIN))
    c.append(e('q14', 's8', 's5', LOOP_L, '下一轮的检索能拿到它', pts=[(35, 797), (35, 437)]))
    c.append(e('q15', 's2', 't1', SIDE_L, '思考过程走这块'))
    c.append(e('q16', 's6', 'f1', SIDE_L, '模型没答上来'))
    c.append(e('q17', 's4', 's4b', SIDE_R, '顺带判这轮开不开思考'))
    c.append(e('q18', 's4b', 's6', DASH, 'extra_body：enable_thinking', pts=[(858, 357), (858, 517)]))
    return page('p2', '2-一轮对话', 880, 1044, c)


# ============ 页3：记忆与清洗 ============
def build_p3() -> str:
    c: list[str] = []
    库 = 库里的数() or 读不到
    c.append(v('h3', '两层记忆与清洗（下水道）\n'
               '热库越积越多 → 必须有下水道；顺序不能变：先落地，才敢清', 80, 14, 670, 56, HDR))
    c.append(v('t2', f'二层 · 热库（PG 表 rag_chunks, tier=2）\n{库["二层"]} 片\n（这一轮对话的原话，切片后嵌向量）',
               300, 96, 240, 76, CODE))
    c.append(v('d1', '静默够了吗?', 300, 196, 240, 84, DIAMOND))
    c.append(v('r1', '清洗三步（refine.py）\n'
               '① 先复制：原样搬冷库（kind=原文，向量直接复用）\n'
               '② 再清洗：三遍小模型抽 概述 / 知识 / 别名\n'
               '③ 清空热库：只清刚洗过的那批，语料不动',
               270, 310, 300, 100, BOX))
    c.append(v('t3', f'三层 · 冷库（同一张表, tier=3）\n{库["三层"]} 条 = {库["类型"]}',
               290, 440, 260, 74, CODE))
    c.append(v('al', f'alias.json · {库["别名"]} 行别名', 290, 536, 260, 44, CODE))
    c.append(v('s1', '检索：两路并走', 300, 610, 240, 50, BOX))
    c.append(v('s2', '按 index 合并去重，保留最高分', 285, 682, 270, 44, BOX))
    c.append(v('s3', '给下一轮用', 320, 756, 200, 44, IO))
    # 左列：两路 + 实测旁注
    c.append(v('p1', '第一路 · 纯向量' + hint('search.py 余弦，阈值 0.40'), 40, 610, 190, 50, BOX))
    c.append(v('p2', '第二路 · 别名命中' + hint('字符串包含 → 该概念的别名池各检索一遍'), 40, 680, 190, 56, BOX))
    c.append(v('ex', side('实测（同一查询，控制变量）') + '\n关别名 0.5178 未命中\n开别名 0.8163 命中（召回「软路由是 x86 小主机」）',
               40, 762, 190, 104, NOTE))
    # 右列：兜底 + 定时链
    c.append(v('f1', side('兜底：洗不动的批次不许算「洗过了」') + '\n'
               '读不到原文 → 拿三层 kind=原文 回填\n'
               '两边都空才记账 state/refine-待重洗.json',
               600, 300, 220, 122, NOTE))
    c.append(v('f2', '心跳' + hint('state/refine-心跳.json —— 每轮打时间戳'), 600, 440, 220, 54, BOX))
    c.append(v('f4', 'cron 每分钟' + hint('flock -n /tmp/collaplex-refine.lock（防叠跑）'), 600, 508, 220, 54, BOX))
    c.append(v('f3', '补跑 / 查账' + hint('--回填 幂等；--待重洗 看账；--干跑 不动数据'), 600, 576, 220, 54, BOX))
    c.append(v('f5', '什么时候动' + hint('idle 1200s（20 分）｜hard_idle 7200s（2 小时兜底）'),
               600, 644, 220, 54, BOX))
    c.append(e('r1', 't2', 'd1', MAIN))
    c.append(e('r2', 'd1', 'r1', MAIN, '是（静默 20 分钟 / 2 小时兜底）'))
    c.append(e('r3', 'r1', 't3', MAIN))
    c.append(e('r4', 't3', 'al', MAIN))
    c.append(e('r5', 'al', 's1', MAIN))
    c.append(e('r6', 'p1', 's1', SIDE_R, '向量'))
    c.append(e('r7', 'p2', 's1', SIDE_R, '别名'))
    c.append(e('r8', 's1', 's2', MAIN))
    c.append(e('r9', 's2', 's3', MAIN))
    c.append(e('r10', 'd1', 'f1', FAIL, '洗不动 → 记账'))
    c.append(e('r11', 'f1', 'f2', MAIN, ''))
    c.append(e('r12', 'f2', 'f4', MAIN, ''))
    c.append(e('r13', 'f4', 'f3', MAIN, '按时叫醒'))
    c.append(e('r14', 'f5', 'd1', LOOP_L, '按这两个数判', pts=[(560, 196)]))
    c.append(e('r15', 't3', 't2', LOOP_R, '每轮继续往热库追加', pts=[(846, 134), (846, 477)]))
    return page('p3', '3-记忆与清洗', 880, 890, c)


# ============ 页4：启动·自检·打包 ============
def build_p4() -> str:
    c: list[str] = []
    c.append(v('h4', '启动 · 自检 · 打包 · 开源（成品形状）\n'
               '自检 30 项全绿才起模型拉主程序；打包走「不编译」路线', 80, 14, 670, 56, HDR))
    c.append(v('s1', 'cli.py · collaplex-agent' + hint('web 起页面(:8791) / 自检 / 模型 / chat —— 底下同一套'), 300, 96, 230, 50, CODE))
    c.append(v('s2', 'selfcheck.py · 30 项', 300, 170, 230, 50, CODE))
    c.append(v('d1', '全绿?', 340, 250, 150, 70, DIAMOND))
    c.append(v('f1', '列出报错项 + 退出码 1' + hint('不拉主程序，先修完再来'), 52, 258, 216, 56, BOX))
    c.append(v('s3', 'start_models.sh' + hint('llama.cpp：主模型 :8790 + 向量 :8199'), 300, 356, 230, 56, CODE))
    c.append(v('s4', 'main.py 起对话', 300, 448, 230, 50, CODE))
    # 右侧：自检怎么查（这两块是 selfcheck.py 干的事）
    c.append(v('g1', '模型 API GET 检查（四组各一发 /models）\n'
               '主模型 · 向量模型 · 执行体 · 子 agent\n'
               '401→Key 不对 ｜ 连不上→服务起了吗\n'
               '执行体 / 子 agent 没配 = 回落主模型那套，不算错',
               592, 150, 268, 116, NOTE))
    c.append(v('g2', '其余检查项\n'
               '配置：.env 键齐 / 四份 json 能读（含思考路由 · 外援触发）\n'
               '依赖：skill 用到的包在不在（子进程 find_spec）\n'
               '库：两层库 / 语料目录 / 别名 / 清洗心跳\n'
               '代码：10 个入口都能编译（三 agent + cli + watchdog + web）\n'
               '结构：skill 目录齐 / 提示词齐 / 索引跟目录对得上',
               592, 288, 268, 140, NOTE))
    # 底部：打包与开源（改完代码才动的第二条链）
    c.append(v('pk', '打包：pack_bundle.sh（项目代码一行不改）\n'
               '① 拿 python-build-standalone install_only 当基座（★ 绝不 strip）\n'
               '② 依赖 pip 装到 runtime/deps（--target），不建 venv\n'
               '③ 项目本体进包（不带 .venv / .env / 日志 / 缓存）\n'
               '④ 写 run.sh + .env.example（只有键名，值留空）\n'
               '⑤ zstd 压包 → dist/collaplex-agent-<日期>.tar.zst（48M，解压 188M）',
               40, 556, 820, 126, NOTE))
    技能 = 技能清单()
    c.append(v('op', f'开源：push_gitea.sh\n'
               'subtree split 把每个 skill 的历史真拆出来\n'
               f'→ {len(技能) + 1} 个公开仓（主仓 + {len(技能)} skill）：\n'
               + ' / '.join(名 for 名, _ in 技能) + '\n'
               '★ 开源前必须扫全历史（.env 曾进过历史）+ 查 Gitea 匿名门',
               40, 706, 400, 120, NOTE))
    c.append(v('nn', side('不编译的理由（当年实测）') + '\n'
               'Nuitka 单文件能编出来（33M / 7 分钟），但原样跑不了：\n'
               '23 处 Path(__file__) 从临时目录找数据 → 报 FileNotFoundError；\n'
               '数据树 / .env / 服务 也编不进去 → 性价比低，改走压缩包',
               470, 706, 390, 100, NOTE))
    c.append(e('x1', 's1', 's2', MAIN))
    c.append(e('x2', 's2', 'd1', MAIN))
    c.append(e('x3', 'd1', 's3', MAIN, '是'))
    c.append(e('x4', 'd1', 'f1', FAIL_L, '否'))
    c.append(e('x5', 's3', 's4', MAIN))
    c.append(e('x6', 's2', 'g1', SIDE_R25, '查模型'))
    c.append(e('x7', 's2', 'g2', SIDE_R75, '查其余'))
    c.append(e('x8', 's4', 'pk', MAIN, '改完代码才动'))
    c.append(e('x9', 'pk', 'op', MAIN, '压完就发'))
    return page('p4', '4-启动·自检·打包', 900, 840, c)


def main() -> None:
    xml = ('<mxfile host="app.diagrams.net">\n' + '\n'.join(
        [build_p1(), build_p2(), build_p3(), build_p4()]) + '\n</mxfile>\n')
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(xml)
    validate(OUT)


def validate(path: str) -> None:
    t = ET.parse(path)
    root = t.getroot()
    diagrams = root.findall('diagram')
    print(f'{os.path.basename(path)}: 共 {len(diagrams)} 页')
    allok = True
    for d in diagrams:
        cells = d.findall('.//mxCell')
        idset = {x.get('id') for x in cells}
        bad = [(x.get('id'), x.get('source'), x.get('target')) for x in cells
               if x.get('edge') == '1' and (x.get('source') not in idset or x.get('target') not in idset)]
        nv = len([x for x in cells if x.get('vertex') == '1'])
        ne = len([x for x in cells if x.get('edge') == '1'])
        vids = [x.get('id') for x in cells if x.get('edge') != '1' and x.get('id') not in ('0', '1')]
        dup = len(set(vids)) != len(vids)
        flag = '断链=无' if not bad else f'断链={bad}'
        print(f'  [{d.get("name")}] {nv}节点 {ne}连线 {flag}' + ('  ★重复id!' if dup else ''))
        if bad or dup:
            allok = False
    assert allok, '校验未通过'


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第三代 Agent OS —— 架构图生成器（输出 1.drawio，共 4 页）

页1 分层总览 / 页2 内核流程(单轮) / 页3 生成器(上下文治理) / 页4 关键决策与契约
生成后自动 ET 断链校验。改图只改本脚本，勿手改 XML。
"""
import os
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "1.drawio")


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
FAIL = SIDE_R + 'dashed=1;strokeColor=#cc0000;fontColor=#cc0000;'
LOOP_L = ('edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;'
          'html=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;'
          'dashed=1;strokeColor=#4472c4;fontColor=#4472c4;')
LOOP_R = ('edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;'
          'html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;'
          'dashed=1;strokeColor=#4472c4;fontColor=#4472c4;')
DASH = ('edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;'
        'html=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=0.5;entryY=0.5;entryDx=0;entryDy=0;'
        'dashed=1;strokeColor=#888888;fontColor=#888888;')
DASH_L2R = ('edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;'
            'html=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;'
            'dashed=1;strokeColor=#888888;fontColor=#888888;')
BIX = SIDE_R + 'startArrow=classic;'

# ---------------- 节点样式 ----------------
BOX = 'rounded=0;whiteSpace=wrap;html=1;'
DIAMOND = 'rhombus;whiteSpace=wrap;html=1;fontSize=12;'
CONTAINER = 'swimlane;html=1;startSize=30;fillColor=#f5f5f5;strokeColor=#666666;fontStyle=1;fontSize=12;'
HDR = 'rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontStyle=1;fontSize=13;'
NOTE = ('rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;'
        'align=left;verticalAlign=top;fontSize=11;spacingLeft=8;spacingTop=6;')
CELL_H = 'rounded=0;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;fontSize=12;fontStyle=1;'
ROW = 'rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=middle;fontSize=11;spacingLeft=8;'
KEY = 'rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=middle;fontSize=11;spacingLeft=8;fillColor=#ffe6cc;'


def v(nid: str, text: str, x: int, y: int, w: int, h: int,
      style: str = BOX, parent: str = '1') -> str:
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


# ============ 页1：分层总览 ============
def build_p1() -> str:
    c: list[str] = []
    c.append(v('h1', '第三代 Agent OS · 分层总览（★ = v2 新增：protocol.py / budget.py）\n'
               'CPU=模型 ｜ RAM=上下文 ｜ 磁盘=SQLite+向量库\n'
               '内核=生成器+状态+权限 ｜ 进程=主线/二线/三线 ｜ 设备=Skill/工具/会话',
               100, 16, 650, 60, HDR))
    # 容器
    c.append(v('BOOT', '① Boot 引导层', 33, 86, 540, 84, CONTAINER))
    c.append(v('KER', '② Kernel 内核层', 33, 184, 540, 244, CONTAINER))
    c.append(v('WRK', '③ Workers 进程层', 33, 442, 540, 84, CONTAINER))
    c.append(v('DRV', '④ Drivers 驱动层', 33, 540, 540, 134, CONTAINER))
    c.append(v('SES', '⑤ Sessions 会话层', 33, 688, 540, 84, CONTAINER))
    c.append(v('MEM', '⑥ Memory 存储层', 670, 184, 200, 202, CONTAINER))
    # Boot 内
    c.append(v('b1', 'config.py\n配置 / 密钥', 16, 36, 161, 38, BOX, 'BOOT'))
    c.append(v('b2', 'selfcheck.py\n自检 模型/DB/向量/网络', 189, 36, 161, 38, BOX, 'BOOT'))
    c.append(v('b3', 'registry.py\n驱动注册表', 362, 36, 161, 38, BOX, 'BOOT'))
    # Kernel 内 2x4
    kk = [('k1', 'core.py\n内核编排'), ('k2', 'generator.py\n生成器(心脏)'),
          ('k3', 'permission.py\n权限模型'), ('k4', 'protocol.py ★\n输出协议解析'),
          ('k5', 'state.py\n状态(事务)'), ('k6', 'timeline.py\n时间线'),
          ('k7', 'scheduler.py\n任务调度'), ('k8', 'budget.py ★\ntoken 预算')]
    for i, (nid, txt) in enumerate(kk):
        x = 16 + (i % 2) * 252
        y = 36 + (i // 2) * 52
        c.append(v(nid, txt, x, y, 240, 40, BOX, 'KER'))
    # Workers 内
    ww = [('w1', 'main_worker\n主线:推理+生成'), ('w2', 'secondary\n二线:筛选+校验'),
          ('w3', 'tertiary\n三线:路由+清洗')]
    for i, (nid, txt) in enumerate(ww):
        c.append(v(nid, txt, 16 + i * 173, 36, 161, 38, BOX, 'WRK'))
    # Drivers 内
    dd = [('d1', 'llm/\n3B·9B·API'), ('d2', 'retrieval/\nRAG·Skill检索'), ('d3', 'tools/\nSSH·ComfyUI·计算')]
    for i, (nid, txt) in enumerate(dd):
        c.append(v(nid, txt, 16 + i * 173, 36, 161, 38, BOX, 'DRV'))
    c.append(v('d4', 'skill_loader\n索引 + 全文', 16, 88, 161, 36, BOX, 'DRV'))
    c.append(v('d5', 'base.py\n驱动契约(超时/错误)', 189, 88, 161, 36, BOX, 'DRV'))
    # Sessions 内
    ss = [('s1', 'manager.py\n会话池'), ('s2', 'SSH 持久会话'), ('s3', 'ComfyUI 持久会话')]
    for i, (nid, txt) in enumerate(ss):
        c.append(v(nid, txt, 16 + i * 173, 36, 161, 38, BOX, 'SES'))
    # Memory 内
    c.append(v('m1', 'store.py\nSQLite (WAL)', 16, 36, 166, 44, BOX, 'MEM'))
    c.append(v('m2', 'vector.py\nChroma / LanceDB', 16, 92, 166, 44, BOX, 'MEM'))
    c.append(v('m3', 'archive.py\n冷归档(不摘要)', 16, 148, 166, 44, BOX, 'MEM'))
    # 连线
    c.append(e('p1e1', 'BOOT', 'KER', MAIN, '拉起'))
    c.append(e('p1e2', 'KER', 'WRK', MAIN, '调度'))
    c.append(e('p1e3', 'WRK', 'DRV', MAIN, '调用'))
    c.append(e('p1e4', 'DRV', 'SES', MAIN, '持久会话'))
    c.append(e('p1e5', 'KER', 'MEM', BIX, '状态读写'))
    return page('p1', '1-分层总览', 920, 800, c)


# ============ 页2：内核流程(单轮) ============
def build_p2() -> str:
    c: list[str] = []
    c.append(v('h2', '内核流程 · 单轮生命周期（turn）\n'
               '输入: 用户问题 | 输出: 正文 + 状态更新 +（可选）工具结果', 88, 16, 650, 54, HDR))
    c.append(v('s1', '读入用户问题', 323, 90, 180, 50))
    c.append(v('s2', '生成器组装上下文\n(权限 / 位置 / 预算)', 323, 180, 180, 50))
    c.append(v('s3', '调主线 (API 大模型)', 323, 270, 180, 50))
    c.append(v('s4', '解析输出协议\n(正文 + 尾块 JSON)', 323, 360, 180, 50))
    c.append(v('d1', '有 needs 声明?', 308, 450, 210, 80, DIAMOND))
    c.append(v('d2', '状态 delta\n校验通过?', 308, 590, 210, 80, DIAMOND))
    c.append(v('s5', 'apply_delta\n(单事务写入)', 323, 720, 180, 50))
    c.append(v('s6', '追加时间线', 323, 810, 180, 50))
    c.append(v('s7', '输出正文\n(前端只渲染正文)', 323, 900, 180, 50))
    # 左列：needs 分支
    c.append(v('t1', '三线路由\n(LoRA 选工具)', 55, 465, 185, 50))
    c.append(v('t2', '二线筛选 + 校验', 55, 555, 185, 50))
    c.append(v('t3', '注入结果\n(重组装)', 55, 645, 185, 50))
    # 右列：失败
    c.append(v('r1', '拒绝 + 记日志\n(状态原样不动)', 600, 590, 185, 50))
    # 后台线程
    c.append(v('nt', '★ 后台线程\n（与主链并行、不阻塞主线）\n'
               '· 预取：提前检索下一轮\n'
               '· 冷归档：超限即归档\n　（不摘要、不烧 token）\n'
               '· 会话 keepalive\n　SSH / ComfyUI 保活', 40, 760, 250, 170, NOTE))
    # 连线
    c.append(e('q1', 's1', 's2', MAIN))
    c.append(e('q2', 's2', 's3', MAIN))
    c.append(e('q3', 's3', 's4', MAIN))
    c.append(e('q4', 's4', 'd1', MAIN))
    c.append(e('q5', 'd1', 't1', SIDE_L, '是'))
    c.append(e('q6', 't1', 't2', MAIN))
    c.append(e('q7', 't2', 't3', MAIN))
    c.append(e('q8', 't3', 's2', LOOP_L, '重组装后再推理', pts=[(25, 670), (25, 205)]))
    c.append(e('q9', 'd1', 'd2', MAIN, '否'))
    c.append(e('q10', 'd2', 's5', MAIN, '是'))
    c.append(e('q11', 'd2', 'r1', FAIL, '否'))
    c.append(e('q12', 's5', 's6', MAIN))
    c.append(e('q13', 's6', 's7', MAIN))
    return page('p2', '2-内核流程(单轮)', 827, 1000, c)


# ============ 页3：生成器 ============
def build_p3() -> str:
    c: list[str] = []
    c.append(v('h3', '生成器 · 上下文治理引擎\n'
               '决定：什么内容能进 / 以什么权限 / 放什么位置 / 占多少预算', 88, 16, 650, 54, HDR))
    c.append(v('g1', '输入：状态 / 时间线 / RAG / Skill / 问题', 303, 90, 220, 50))
    c.append(v('g2', '① 权限分级：只读 / 可写 / 注入 / 可选', 303, 180, 220, 50))
    c.append(v('g3', '② 位置排序（缓存友好）\n前(只读) → 中(动态) → 后(问题)', 293, 270, 240, 50))
    c.append(v('g4', '③ 预算：可用 = 总窗口 − 输出预留 − 只读区', 273, 360, 280, 50))
    c.append(v('d1', '当前块放得下?', 308, 450, 210, 80, DIAMOND))
    c.append(v('g5', '④ 选中并入 prompt', 323, 580, 180, 50))
    c.append(v('g6', '降级\n全文→索引 / RAG→Top1', 600, 450, 190, 60))
    c.append(v('g7', '按位置拼接 (前 | 中 | 后)', 303, 670, 220, 50))
    c.append(v('g8', '输出 prompt 字符串', 303, 760, 220, 50))
    c.append(v('nt3', '★ 逐块评估：放不下就降级，绝不直接丢弃\n'
               '★ 只读区恒置最前 → KV 前缀永久命中\n'
               '★ 权限四级：模型无权改只读区（改则整块拒绝）', 273, 860, 480, 80, NOTE))
    c.append(e('r1', 'g1', 'g2', MAIN))
    c.append(e('r2', 'g2', 'g3', MAIN))
    c.append(e('r3', 'g3', 'g4', MAIN))
    c.append(e('r4', 'g4', 'd1', MAIN))
    c.append(e('r5', 'd1', 'g5', MAIN, '是'))
    c.append(e('r6', 'd1', 'g6', FAIL, '否'))
    c.append(e('r7', 'g6', 'g5', DASH_L2R, '降级后仍入选'))
    c.append(e('r8', 'g5', 'g7', MAIN))
    c.append(e('r9', 'g7', 'g8', MAIN))
    c.append(e('r10', 'g5', 'd1', LOOP_R, '还有下一块'))
    return page('p3', '3-生成器(上下文治理)', 827, 960, c)


# ============ 页4：关键决策与契约 ============
def build_p4() -> str:
    c: list[str] = []
    c.append(v('h4', '关键设计决策与契约（v2 完善）\n🔴 = 必须先定的三处；其余为已定基线', 88, 16, 650, 54, HDR))
    xs = (30, 220, 590)
    ws = (180, 360, 210)
    c.append(v('th1', '决策项', xs[0], 90, ws[0], 36, CELL_H))
    c.append(v('th2', '选择', xs[1], 90, ws[1], 36, CELL_H))
    c.append(v('th3', '理由 / 约束', xs[2], 90, ws[2], 36, CELL_H))
    rows = [
        ('并发模型 🔴', '单进程 + asyncio；所有阻塞驱动用 to_thread 包装', '驱动库全同步阻塞，直接 await 会卡死事件循环'),
        ('输出协议 🔴', '正文 Markdown + 末尾唯一标记块 JSON(delta/needs)', '展示/数据分离；标记唯一防误判；约束解码保合法'),
        ('事务边界 🔴', '先全量校验 → 单事务写入 → 失败整体回滚', '防半应用脏数据（未提交语句会被下次 commit 带出）'),
        ('状态存储', 'SQLite（WAL，单写连接）', '跨平台 / 事务安全 / 零配置'),
        ('向量库', 'ChromaDB 或 LanceDB', '纯 Python、本地、无需独立服务'),
        ('权限模型', '四级：只读 / 可写 / 注入 / 可选', '防止模型污染核心指令'),
        ('位置策略', '只读区恒置最前', 'KV 前缀永久命中；动态区靠后重算代价最小'),
        ('预算管理', '硬约束 + 优先级降级', '窗口绝不溢出；放不下降级而非丢弃'),
        ('压缩策略', '程序归档，模型不参与', '零压缩税、不滚雪球'),
        ('路由策略', '三线 LoRA 专用路由', '主线不试错，错误不进主线上下文'),
        ('会话管理', '持久会话池（像 fd 长期持有）', '省重复环境描述 token，操作连续'),
        ('平台策略', '内核纯逻辑，驱动按平台适配', '内核跨平台；工具驱动需按平台重写'),
        ('token 计数', '真实 tokenizer（模型自带 / tiktoken）', '硬编码估算必偏 → 溢出或浪费'),
        ('Skill 数据源', 'SQLite 为权威，index.json 仅导入种子', '单一数据源，防状态散落多处'),
    ]
    y = 126
    for i, (a, b, d) in enumerate(rows):
        st_a = KEY if '🔴' in a else ROW
        c.append(v(f'a{i}', a, xs[0], y, ws[0], 44, st_a))
        c.append(v(f'b{i}', b, xs[1], y, ws[1], 44, ROW))
        c.append(v(f'c{i}', d, xs[2], y, ws[2], 44, ROW))
        y += 44
    return page('p4', '4-关键决策与契约', 827, y + 30, c)


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
    print(f'{path}: 共 {len(diagrams)} 页')
    allok = True
    for d in diagrams:
        cells = d.findall('.//mxCell')
        ids = {x.get('id') for x in cells}
        bad = [(x.get('id'), x.get('source'), x.get('target')) for x in cells
               if x.get('edge') == '1' and (x.get('source') not in ids or x.get('target') not in ids)]
        nv = len([x for x in cells if x.get('vertex') == '1'])
        ne = len([x for x in cells if x.get('edge') == '1'])
        dup = len(ids) != len(cells)
        flag = '断链=无' if not bad else f'断链={bad}'
        print(f'  [{d.get("name")}] {nv}节点 {ne}连线 {flag}' + ('  ★重复id!' if dup else ''))
        if bad or dup:
            allok = False
    assert allok, '校验未通过'


if __name__ == '__main__':
    main()
#!/usr/bin/env python3
"""生成 联网搜索skill-v2-补全版.drawio —— 在老板原稿上补全架构.

原稿: diagrams/联网搜索skill.drawio        (不动, 只读)
产出: diagrams/联网搜索skill-v2-补全版.drawio (4 页)

用法: .venv/bin/python diagrams/gen_联网搜索skill_补全版.py
跑完自己校验: XML 能解析 / 断链 0 / 重复 id 0 / 每页节点·连线计数。
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
OUT = HERE / "联网搜索skill-v2-补全版.drawio"

# ── 形状 ─────────────────────────────────────────────────────────
KEEP = "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;"   # 蓝=原稿保留
ADD = "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;"    # 绿=新增
FIX = "rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;"    # 红=必改
SUG = "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;"    # 黄=建议
DIA = "rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;"
NOTE = ("text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
        "align=left;verticalAlign=top;fontSize=11;")
BOX = ("rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#666666;"
       "fontSize=11;align=left;verticalAlign=top;spacingLeft=8;spacingTop=6;")
TABLE = ("rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#6c8ebf;"
         "align=left;verticalAlign=top;spacingLeft=10;spacingTop=8;fontSize=11;")
HEAD = "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontStyle=1;"

# ── 边样式 ───────────────────────────────────────────────────────
MAIN = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
        "exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;")
SIDE_R = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
          "exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;")
SIDE_L = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
          "exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;")
# 从上出、进右侧: 回环专用 —— 走主链上方, 别跟左侧分叉挤在一起
UP = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
      "exitX=0.5;exitY=0;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;")
# 从下出、进左侧: 长距离绕行专用 —— 走左走廊, 不横穿中间那一列
DOWN_L = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
          "exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;")
RED = SIDE_R + "dashed=1;strokeColor=#cc0000;fontColor=#cc0000;"
DASH = MAIN + "dashed=1;strokeColor=#666666;"


def esc(text: str) -> str:
    """整个 value 一次过完 —— 里面的 HTML 片段也一起转义(否则属性提前闭合).

    换行统一走 \\n -> &#10;: 属性值里的裸换行会被 XML 解析器压成空格。
    """
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


# ═══ 页 1: 主链补全版 ═══════════════════════════════════════════════
def p1() -> str:
    c: list[str] = []
    n, e = node, edge
    CX, CW, CH = 430, 210, 58

    c.append(n("p1_t", "联网搜索 skill · 主链补全版（原稿不动，本图是补全后的形状）",
               20, 8, 900, 30, NOTE))
    c.append(n("p1_1", "调用", CX, 60, CW, CH, KEEP, "skill/search/SKILL.md"))
    c.append(n("p1_2", "命令路由", CX, 150, CW, CH, KEEP, "main.py: 动作表 → scripts/run.py"))
    c.append(n("p1_3", "★闸门  单轮 ≤100 次 ＋ 体积上限", CX, 240, CW, CH, ADD,
               "run.py: 先过闸, 不通过直接回原因"))
    c.append(n("p1_4", "真浏览器抓取（bing ＋ 百度）", CX, 330, CW, CH, FIX,
               "scripts/browser.py: 防爬虫识别＝用真浏览器; 常驻 + 闲置看门狗"))
    c.append(n("p1_5", "错误分类", CX, 420, CW, CH, ADD, "browser.py: 见第 3 页失败四类"))
    c.append(n("p1_6", "程序清洗（HTML → 标题 ＋ 正文段落）", CX, 510, CW, CH, KEEP,
               "scripts/article.py（已写好, 直接复用）"))
    c.append(n("p1_7", "清洗后还有东西吗？", CX, 600, 210, 84, DIA, "低于阈值 → 只回截图"))
    c.append(n("p1_8", "切片", CX, 730, CW, CH, KEEP, "借 rag 的 chunker.py, 不另写"))
    c.append(n("p1_9", "去重（URL 归一 ＋ 正文指纹）", CX, 820, CW, CH, ADD,
               "store.py: 跨来源也去重; 命中有则更新不新增"))
    c.append(n("p1_10", "入热库", CX, 910, CW, CH, ADD, "表 search_hot（第 2 页）；热是一份, 不分来源"))
    c.append(n("p1_11", "检索 —— 只搜热的", CX, 1000, CW, CH, KEEP, "借 rag 的向量＋倒排那两路"))
    c.append(n("p1_12", "返回结果（原文片段 ＋ 链接 ＋ 截图）", CX, 1090, CW, CH, KEEP,
               "run.py: 打印, 不改写不总结"))

    c.append(e("p1a", "p1_1", "p1_2"))
    c.append(e("p1b", "p1_2", "p1_3"))
    c.append(e("p1c", "p1_3", "p1_4"))
    c.append(e("p1d", "p1_4", "p1_5"))
    c.append(e("p1e", "p1_5", "p1_6"))
    c.append(e("p1f", "p1_6", "p1_7"))
    c.append(e("p1g", "p1_7", "p1_8", MAIN, "是"))
    c.append(e("p1h", "p1_8", "p1_9"))
    c.append(e("p1i", "p1_9", "p1_10"))
    c.append(e("p1j", "p1_10", "p1_11"))
    c.append(e("p1k", "p1_11", "p1_12"))

    c.append(n("p1_shot", "只回截图（不硬塞空正文）", 700, 612, 200, 60, ADD,
               "browser.py 已经截过, 直接给路径"))
    c.append(e("p1l", "p1_7", "p1_shot", SIDE_R, "否"))
    c.append(e("p1m", "p1_shot", "p1_12", SIDE_L, ""))

    # 左: 浏览器渲染支路（原稿那条）
    c.append(n("p1_r1", "浏览器渲染", 90, 330, 170, CH, KEEP, "同一套浏览器件"))
    c.append(n("p1_r2", "出图（浏览器截图）", 0, 430, 170, CH, KEEP,
               "复用 ~/tools/cdp-shot/cdp_shot.py"))
    c.append(n("p1_r3", "获取 html", 190, 430, 170, CH, KEEP, "web/tests/截网页.py 同源"))
    c.append(n("p1_r4", "汇总", 90, 530, 170, CH, KEEP, ""))
    c.append(e("p1n", "p1_2", "p1_r1", SIDE_L, "渲染"))
    c.append(e("p1o", "p1_r1", "p1_r2"))
    c.append(e("p1p", "p1_r1", "p1_r3"))
    c.append(e("p1q", "p1_r2", "p1_r4"))
    c.append(e("p1r", "p1_r3", "p1_r4"))
    c.append(e("p1s", "p1_r4", "p1_6", SIDE_R, "html"))
    c.append(e("p1t", "p1_r4", "p1_12", DOWN_L, "图片"))

    # 右: skill.md 侧 ＋ 图例
    c.append(n("p1_s1", "skill.md 侧", 760, 60, 190, CH, KEEP, "教模型怎么判该去哪个站"))
    c.append(n("p1_s2", "判断需要哪个网页", 760, 150, 190, CH, KEEP, "模型侧判断"))
    c.append(n("p1_s3", "「模型还要继续用就再发命令，上限单轮 100 次」", 760, 250, 250, 90, FIX,
               "★原稿挂在模型侧＝软约束; 已挪到程序侧闸门硬拦"))
    c.append(e("p1u", "p1_s1", "p1_s2"))
    c.append(e("p1v", "p1_s2", "p1_1", UP, "发命令"))
    c.append(e("p1w", "p1_s2", "p1_s3", SIDE_R, ""))

    c.append(n("p1_lg",
               "上色说明\n"
               "蓝 ＝ 原稿保留（形状不变）\n"
               "红 ＝ 必改（2 处）\n"
               "绿 ＝ 新增（补全）\n"
               "黄 ＝ 建议\n\n"
               "原稿: diagrams/联网搜索skill.drawio",
               760, 400, 250, 170, BOX))
    c.append(n("p1_nt",
               "★ 必改 2 处：①「启动无头浏览器 ＋ 获取国内bing加百度搜索」两格合并成一格「真浏览器抓取」，"
               "因为上浏览器的目的就是防爬虫识别，不是为了搜索本身；② 100 次上限挪到程序侧闸门 —— "
               "挂在模型侧拦不住发疯的模型。★ 新增：闸门 / 错误分类 / 只回截图 / 去重 / 入热库 / 检索面收窄到热库。",
               20, 1180, 1020, 80, NOTE))
    return page("p1", "1-主链补全版", 1060, 1280, c)


# ═══ 页 2: 数据面 ══════════════════════════════════════════════════
def p2() -> str:
    c: list[str] = []
    n, e = node, edge
    c.append(n("p2_t", "数据面：热库（检索面）＋ 语料库（新表·长期）", 20, 8, 900, 30, NOTE))

    c.append(n("p2_1", "抓取产物（标题 ＋ 正文 ＋ 截图路径 ＋ 状态码）", 560, 70, 280, 56, KEEP))
    c.append(n("p2_2", "去重键：URL 归一 ＋ 正文指纹", 560, 160, 280, 56, ADD,
               "同一条从 bing 和百度各来一次 → 只算一条"))
    c.append(n("p2_3", "入热库", 560, 250, 280, 56, ADD))
    c.append(e("p2a", "p2_1", "p2_2"))
    c.append(e("p2b", "p2_2", "p2_3"))

    c.append(n("p2_h", "热库（表 search_hot）", 380, 350, 430, 280, TABLE,
               "列: id / url / 域名 / 来源(bing·百度·直连·渲染) / 标题 / hash / idx / text\n"
               "        / embedding vector(1024) / 抓取时间 / 状态码 / 截图路径 / 热到什么时候\n"
               "索引: unique(url 归一, hash) · hnsw(embedding)\n"
               "★ 形状与 rag_chunks 对齐 —— 向量与检索算法整套复用 rag\n"
               "★ 热是一份：不分来源，来源只是列（bing/百度/直连/渲染）\n"
               "★ 截图跟 TTL 一起清（热库里的没了，截图也删）\n"
               "★ 检索只查这里（热的才进检索面）"))
    c.append(n("p2_c", "语料库（新表 search_corpus · 供后续人复用）", 880, 350, 460, 280, TABLE,
               "列: 与热库同 ＋ 首次抓到 / 最后抓到 / 命中次数\n"
               "去重: 长期唯一（URL 归一 ＋ 正文指纹）\n"
               "留存: 90 天 或 2GB，先到先清最老（我定的档，可改）\n"
               "★ 就是你说的「专门放搜索引擎语料的库」——人也能直接查"))
    c.append(e("p2c", "p2_3", "p2_h"))

    c.append(n("p2_4", "下沉任务（TTL 到期）", 480, 690, 200, 56, ADD, "cron 定时, 去重后并入"))
    c.append(n("p2_5", "检索（只搜热的）", 480, 810, 200, 56, KEEP))
    c.append(e("p2d", "p2_h", "p2_4", MAIN, "热到 24h"))
    c.append(e("p2e", "p2_4", "p2_c", SIDE_R, "并入"))
    c.append(e("p2f", "p2_h", "p2_5", SIDE_L, "查这里"))
    c.append(e("p2g", "p2_c", "p2_5", DASH, "不进检索面"))

    c.append(n("p2_p", "参数（旁注 · 不属于主流程）", 40, 350, 280, 260, BOX,
               "热窗口 TTL      24 小时\n"
               "语料库留存      90 天 / 2GB\n"
               "单轮命令上限    100 次\n"
               "单页字节上限    5MB\n"
               "单次（一条命令）20MB\n"
               "落盘总量上限    2GB（LRU 清最老）\n\n"
               "以上都是我先定的档，\n你说改哪个就改哪个"))
    c.append(n("p2_nt",
               "★ 为什么分两层：你说「检索只搜热的」——那就必须有个热的地方，"
               "而语料库要长期留着给人复用，两者的寿命不一样（24 小时 vs 90 天），"
               "挤在一张表里就没法各自定 TTL。★ 抓取先入热库；TTL 到期由下沉任务并入语料库，"
               "热库里清掉 —— 跟项目里「二层热库 → refine 下沉冷库」是同一套路子。",
               20, 910, 1360, 70, NOTE))
    return page("p2", "2-数据面", 1400, 1000, c)


# ═══ 页 3: 失败与兜底 ══════════════════════════════════════════════
def p3() -> str:
    c: list[str] = []
    n, e = node, edge
    c.append(n("p3_t", "失败语义与兜底（你定的口径：不是 HTTPS 错、也不是超时，就回具体报错）",
               20, 8, 960, 30, NOTE))
    c.append(n("p3_1", "抓取（真浏览器）", 380, 70, 240, 56, KEEP))
    c.append(n("p3_2", "响应超时？", 380, 160, 240, 80, DIA))
    c.append(n("p3_3", "HTTPS / 证书错？", 380, 280, 240, 80, DIA))
    c.append(n("p3_4", "响应正常吗？（2xx）", 380, 400, 240, 84, DIA,
               "404 / 域名不存在 / 站点拒绝 都走否"))
    c.append(n("p3_5", "程序清洗（HTML → 正文段落）", 380, 530, 240, 56, KEEP))
    c.append(n("p3_6", "清洗后有内容吗？", 380, 620, 240, 84, DIA))
    c.append(n("p3_7", "切片 → 入热库", 380, 750, 240, 56, KEEP))

    c.append(n("p3_a", "回「响应超时」＋ URL", 760, 172, 280, 56, ADD, "这类没有更具体的原因"))
    c.append(n("p3_b", "回「HTTPS 错误」＋ URL", 760, 292, 280, 56, ADD,
               "同上, 这两类自成一类"))
    c.append(n("p3_c", "回具体报错：404 / 站点不存在 / 站点拒绝", 760, 414, 280, 76, ADD,
               "例: HTTP 404 查无此页 · 域名不存在: xxx.com"))
    c.append(n("p3_d", "只回截图", 760, 634, 280, 56, ADD, "清洗出来没东西就别硬塞空正文"))

    c.append(e("p3a", "p3_1", "p3_2"))
    c.append(e("p3b", "p3_2", "p3_3", MAIN, "否"))
    c.append(e("p3c", "p3_3", "p3_4", MAIN, "否"))
    c.append(e("p3d", "p3_4", "p3_5", MAIN, "是"))
    c.append(e("p3e", "p3_5", "p3_6"))
    c.append(e("p3f", "p3_6", "p3_7", MAIN, "是"))
    c.append(e("p3g", "p3_2", "p3_a", RED, "是"))
    c.append(e("p3h", "p3_3", "p3_b", RED, "是"))
    c.append(e("p3i", "p3_4", "p3_c", RED, "否"))
    c.append(e("p3j", "p3_6", "p3_d", RED, "否"))

    c.append(n("p3_z1", "闸门 ＋ 浏览器看门狗（程序侧硬拦）", 60, 170, 260, 105, ADD,
               "单轮 >100 次 → 拦\n体积超上限 → 拦\n浏览器闲置超时 → 杀\n被拦 / 被杀都回一句人话, 不静默"))
    c.append(e("p3k", "p3_z1", "p3_1", SIDE_R, "放行"))
    c.append(n("p3_z2", "失败一律回原因，不重试不静默", 60, 305, 260, 110, SUG,
               "取不到 / 清洗空 / 切片空 / 入库失败\n四种都直接回一句带原因的话"))

    c.append(n("p3_nt",
               "★ 四类出口：①响应超时 ②HTTPS 错误 ③具体报错（404 / 站点不存在 / 站点拒绝）"
               "④正常但清洗后没内容 → 只回截图。前两类自成一类（本身就说不出更具体的），"
               "第三类才叫「具体报错」——它是从抓取这一关出来的，不是从清洗。"
               "★ 兜底闸：100 次是防模型发疯的次数闸，体积闸是防打爆磁盘（本机 NVMe 曾只剩 11G）。",
               20, 850, 1020, 90, NOTE))
    return page("p3", "3-失败与兜底", 1100, 980, c)


# ═══ 页 4: 验证清单 ════════════════════════════════════════════════
def p4() -> str:
    rows: list[tuple[str, str, str]] = [
        ("V1", "无头浏览器抓 bing 一页", "拿到 ≥8 条（标题 ＋ 链接）"),
        ("V2", "百度那一路", "留着 —— 待会专门做实验再定去留"),
        ("V3", "防识别（用真浏览器）", "对拦 HTTP 抓取的站，浏览器能拿到 html"),
        ("V4", "404 / 域名不存在", "回具体报错文本（带码或域名）"),
        ("V5", "打不通的站 / 超时", "回「响应超时」，不是崩栈"),
        ("V6", "html 空壳页", "只回截图路径，不硬塞空正文"),
        ("V7", "去重", "同一 URL 从 bing 和百度各来一次 → 热库只 1 条"),
        ("V8", "TTL 与下沉", "热窗口调 1 分钟 → 到期后并入语料库、热库清空"),
        ("V9", "检索只搜热的", "语料库里造一条 → 检索搜不到它"),
        ("V10", "100 次闸", "连发 101 条命令 → 第 101 条被拦并回一句人话"),
        ("V11", "截图复用", "复用 cdp_shot.py 出图，图非空且能打开"),
        ("V12", "浏览器看门狗", "闲置超时后进程真退出（ps 查不到），下次用时再拉起"),
        ("V13", "回归", "原来的 rag 检索与自检 24/24 不受影响"),
    ]
    c: list[str] = []
    n = node
    c.append(n("p4_t", "验证清单（每条都带判据；先抽样验收再全量）", 20, 8, 900, 30, NOTE))
    c.append(n("p4_h1", "编号", 40, 60, 70, 40, HEAD))
    c.append(n("p4_h2", "验什么", 120, 60, 340, 40, HEAD))
    c.append(n("p4_h3", "判据", 470, 60, 560, 40, HEAD))
    y = 110
    for tag, what, crit in rows:
        c.append(n(f"p4_{tag}_a", tag, 40, y, 70, 52, BOX))
        c.append(n(f"p4_{tag}_b", what, 120, y, 340, 52, BOX))
        c.append(n(f"p4_{tag}_c", crit, 470, y, 560, 52, BOX))
        y += 60
    c.append(n("p4_nt",
               "★ 已有现成件可直接过：bing 解析（serp.py 已真跑通）、正文清洗（article.py）、"
               "截图（~/tools/cdp-shot/cdp_shot.py）、真浏览器 ＋ 去重 ＋ 入库"
               "（~/tools/vis-crawler/crawl_marathon_mt.py，Playwright 那套现成的）。"
               "V2 百度留着，待会专门做实验再定去留。",
               20, y + 10, 1010, 60, NOTE))
    return page("p4", "4-验证清单", 1060, y + 100, c)


def main() -> None:
    xml = ('<mxfile host="app.diagrams.net">\n'
           + "\n".join([p1(), p2(), p3(), p4()])
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

#!/usr/bin/env python3
"""生成 diagrams/定时任务.drawio —— 定时任务 skill 的设计图(2 页)。

页 1「链路」      : 老板手绘底稿(2026-10-09, 原样备份在 diagrams/定时任务.原稿-备份.drawio) + 后续新增
页 2「定档与判据」: 审计后补的那套决定, 一条一行(项 / 定法 / 为什么)

★ 以后改这张图 = 改这个脚本重跑, 别手改 .drawio(会被下次重跑覆盖)。
★ 文案里写**原始 HTML**(<br> / <font>), 由 esc() 统一转义一次 —— 别预先写成 &lt;br&gt;, 会二次转义。
★ 改完必跑: 断链 0 / 重复 id 0 / 每页计数, 再导 PNG 逐页看图(脚本绿 != 图能看)。

用法: .venv/bin/python diagrams/gen_定时任务.py
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
OUT = HERE / "定时任务.drawio"

# ── 形状 ─────────────────────────────────────────────────────────
KEEP = "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;"      # 蓝 = 原稿保留
ADD = "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;"       # 绿 = 后续新增
NOTE = ("rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#999999;"
        "dashed=1;fontSize=11;align=left;verticalAlign=top;spacingLeft=8;spacingTop=6;")
项框 = ("rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;"
       "fontStyle=1;fontSize=11;align=left;verticalAlign=middle;spacingLeft=8;")
法框 = ("rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#999999;"
       "fontSize=11;align=left;verticalAlign=middle;spacingLeft=8;")
据框 = ("rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#cccccc;"
       "fontSize=10;fontColor=#555555;align=left;verticalAlign=middle;spacingLeft=8;")
表头框 = ("rounded=0;whiteSpace=wrap;html=1;fillColor=#eeeeee;strokeColor=#999999;"
        "fontStyle=1;fontSize=11;align=left;verticalAlign=middle;spacingLeft=8;")

# ── 边样式 ───────────────────────────────────────────────────────
MAIN = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
        "exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;")
SIDE_R_HI = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
             "exitX=1;exitY=0.4;exitDx=0;exitDy=0;entryX=0;entryY=0.3;entryDx=0;entryDy=0;")
SIDE_R_LO = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
             "exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.78;entryDx=0;entryDy=0;")
SIDE_L_MID = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
              "dashed=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=1;entryY=0.35;entryDx=0;entryDy=0;")
SIDE_R_TICK = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
               "dashed=1;exitX=1;exitY=0.9;exitDx=0;exitDy=0;entryX=0;entryY=0.3;entryDx=0;entryDy=0;")


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def node(nid: str, text: str, x: int, y: int, w: int, h: int, style: str) -> str:
    return ('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
            '<mxGeometry x="%d" y="%d" width="%d" height="%d" as="geometry"/></mxCell>'
            % (nid, esc(text), esc(style), x, y, w, h))


def edge(eid: str, src: str, dst: str, style: str, label: str = "") -> str:
    标 = ' value="%s"' % esc(label) if label else ""
    return ('<mxCell id="%s"%s style="%s" edge="1" parent="1" source="%s" target="%s">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
            % (eid, 标, esc(style), src, dst))


def page(name: str, did: str, pw: int, ph: int, cells: list[str]) -> str:
    体 = "\n".join("            " + c for c in cells)
    return ('    <diagram name="%s" id="%s">\n'
            '        <mxGraphModel dx="1056" dy="627" grid="1" gridSize="10" guides="1" tooltips="1"'
            ' connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="%d" pageHeight="%d"'
            ' math="0" shadow="0">\n'
            '            <root>\n'
            '                <mxCell id="0"/>\n'
            '                <mxCell id="1" parent="0"/>\n'
            '%s\n'
            '            </root>\n'
            '        </mxGraphModel>\n'
            '    </diagram>' % (esc(name), did, pw, ph, 体))


def build_p1() -> list[str]:
    """页 1: 链路。原稿七颗一字不改; 新增 落盘 / 撤销·列表 / 旁注 / 图例, 线程上补时钟与看门狗判据注记。"""
    cells = [
        node("n_call", "调用", 356, 40, 120, 60, KEEP),
        node("n_wait", "等待多长时间后开始或者结束动作", 110, 175, 210, 70, KEEP),
        node("n_when", "什么时间开始或者结束动作", 400, 175, 210, 70, KEEP),
        node("n_thread", "定时器线程<br><font style=\"font-size:9px\">★ 倒计时走单调钟 / 闹钟走墙钟<br>"
                         "★ 睡眠唤醒后补一次<br>★ 空 + 空闲 60 秒才关</font>", 320, 300, 190, 90, KEEP),
        node("n_dog", "看门狗：定时器里没有任务了就关掉", 60, 280, 220, 70, KEEP),
        node("n_do", "执行动作<br><font style=\"font-size:9px\">＝ 提醒主 agent（不替它干业务）</font>",
             330, 470, 170, 70, KEEP),
        node("n_back", "返回结果", 330, 600, 170, 60, KEEP),
        # ── 后续新增 ──
        node("n_store",
             "落盘：定时器表（state/timers.json）<br>线程登记 / 取消就写它<br>"
             "<font style=\"font-size:9px\">★ 跨重启：启动时读回来重挂<br>"
             "★ 过期条目补一次，并说明是补的<br>★ 自检里查它（能读且非空）</font>",
             60, 400, 220, 110, ADD),
        node("n_undo",
             "撤销 / 列表<br><font style=\"font-size:9px\">入口的另两个动作：<br>"
             "按 id 或「最近那条」撤掉；看现在挂着几条<br>"
             "★ 同一件事在设置页也有一节（看 / 撤）</font>", 570, 300, 210, 100, ADD),
        node("n_tick",
             "过程步骤里读秒<br><font style=\"font-size:9px\">阻塞式等的时候：<br>"
             "「过程」面板里一格原地读秒<br>（不每秒新起一格）</font>", 570, 430, 210, 90, ADD),
        node("n_note",
             "旁注 · 不属于主流程<br>————————————<br>"
             "阻塞 / 非阻塞，由主 agent 声明：<br>"
             "［阻塞式］就在这一轮对话里等<br>"
             "　硬上限 <b>180 分钟</b>；超了程序判条件不足 →<br>"
             "　子 agent 把可选参数提醒给主 agent<br>"
             "［非阻塞式］主 agent 先走，到点回来提醒它<br>"
             "　（排队，等它下一轮开场注入，不插话）<br>"
             "两种都走同一条定时器线程。",
             60, 540, 250, 220, NOTE),
        node("n_legend", "蓝＝原稿保留　绿＝后续新增", 60, 30, 220, 40, NOTE),
    ]
    edges = [
        edge("e_call_wait", "n_call", "n_wait", MAIN),
        edge("e_call_when", "n_call", "n_when", MAIN),
        edge("e_wait_thread", "n_wait", "n_thread", MAIN),
        edge("e_when_thread", "n_when", "n_thread", MAIN),
        edge("e_thread_do", "n_thread", "n_do", MAIN, "到点"),
        edge("e_do_back", "n_do", "n_back", MAIN),
        edge("e_dog_thread", "n_dog", "n_thread", SIDE_R_HI),
        # 双向: 登记/取消时线程写它, 重启时从它读回来重挂
        edge("e_store_thread", "n_store", "n_thread", SIDE_R_LO + "startArrow=classic;"),
        # 双向: 撤掉 / 查一眼 —— 跟左边的落盘对称走右侧
        edge("e_undo_thread", "n_undo", "n_thread", SIDE_L_MID + "startArrow=classic;", "撤 / 查"),
        # 阻塞式等的时候, 往「过程」面板读秒
        edge("e_tick_thread", "n_thread", "n_tick", SIDE_R_TICK, "阻塞式：等的时候"),
    ]
    return cells + edges


# 页 2 台账: (项, 定法, 为什么)
台账: list[tuple[str, str, str]] = [
    ("倒计时的钟", "倒计时走单调钟；闹钟走墙钟；睡眠唤醒后补一次",
     "仓里全是 time.time()，墙钟被 NTP 跳变 / 休眠一带就把时长算飞"),
    ("谁写落盘", "落冷库 PG 表 timers：按进程键分行（web / cli 各一行，一条 upsert 原子）",
     "仓里没有原子写 helper，web 与 CLI 会同时开着"),
    ("「开始或者结束」", "两种都做：一次性提醒；窗口两端（成对登记、成对撤销、可跨天）",
     "只做一次性，就把「结束」那端丢了"),
    ("错过的点", "补一次，并说明这是补的", "不补 = 静默丢任务"),
    ("送达时机", "排队，等主 agent 下一次醒来开场注入", "它正忙的时候不插话"),
    ("阻塞时的读秒", "等的时候在「过程步骤」里读秒：同一格原地改写；存档只留「开始等 / 等到了」两条",
     "逐秒新起一格 = 3 小时一万格，面板和存档都被灌爆（前端 收() 现在只有 think/reply 会续写）"),
    ("条件不足的判据", "程序判四项：时间 / 提醒什么 / 阻塞还是非阻塞 / 是否 ≤180",
     "判据不写死，子 agent 会自由发挥"),
    ("动作面", "登记（闹钟·倒计时）/ 撤销（按 id 或最近那条）/ 列表",
     "只有登记，第一天就会撞上「说错了要撤」"),
    ("设置页 · 定时任务", "设置页左导航加一节「定时任务」：看挂着几条 / 撤掉某条（写操作走 POST，同 /api/关闭）",
     "跟「撤销 / 列表」是同一件事的两个面，不能只做在对话里"),
    ("并发上限", "默认 20 条；同一时刻多条到点按登记先后", "防主 agent 乱挂一堆"),
    ("看门狗判据", "空 + 空闲 60 秒才关；挂在现有 watchdog.py 底下",
     "空即关会起停抖动；别起第三个同名件"),
    ("落盘表结构", "id / 类型 / 到点 / 阻塞标记 / 提醒什么 / 谁声明 / 状态",
     "已完成谁清：owner 清，不然表只涨不消"),
    ("提醒格式", "「⏰ 你定的闹钟到了：<原话>」", "不钉死，主 agent 每次自由发挥"),
    ("假时钟", "留可注入的时间源（环境变量或参数）", "没有它，回归和自检碰不到这个 skill"),
    ("自检项", "timers.json 能读且非空；回归里跑通 登记 → 到点 → 提醒", "时间类最难验"),
    ("边界：不是 crontab", "进程内的、会话语义的一次性闹钟；进程不在就不响",
     "别跟清洗那条系统 crontab 混"),
    ("边界：不碰不可逆", "到点只提醒；真动手由主 agent 收提醒后再挑别的 skill",
     "跟启动页「点第二下才动手」对齐"),
    ("阻塞硬上限", "180 分钟；超了程序判条件不足 → 子 agent 提醒可选参数", "已定（2026-10-09）"),
]


def build_p2() -> list[str]:
    """页 2: 定档与判据台账 —— 一行三格(项 / 定法 / 为什么), rows 循环, 不手排坐标。"""
    cells = [
        node("p2_t", "定时任务 skill · 定档与判据（2026-10-09 审计后补）<br>"
                     "<font style=\"font-size:9px\">页 1 是链路；这一页是没画进链路里的决定，一条一行。"
                     "参数类（上限 20 条 / 空闲 60 秒 / 过期补一次 / 排队 / 单调钟）按授权定档。</font>",
             40, 30, 750, 60, NOTE),
        node("p2_h1", "项", 40, 96, 160, 34, 表头框),
        node("p2_h2", "定法（判据 / 参数）", 210, 96, 330, 34, 表头框),
        node("p2_h3", "为什么这么定", 550, 96, 240, 34, 表头框),
    ]
    y = 136
    for i, (项, 法, 为) in enumerate(台账):
        cells.append(node(f"p2_i{i}", 项, 40, y, 160, 50, 项框))
        cells.append(node(f"p2_f{i}", 法, 210, y, 330, 50, 法框))
        cells.append(node(f"p2_w{i}", 为, 550, y, 240, 50, 据框))
        y += 54
    return cells


def 自检(路径: Path) -> list[tuple[str, int, int]]:
    """逐页: 断链 / 重复 id / 节点·连线计数。光 exit 0 不算数。"""
    根 = ET.parse(路径).getroot()
    报纸: list[tuple[str, int, int]] = []
    for d in 根.findall("diagram"):
        cells = list(d.iter("mxCell"))
        vids: list[str] = [str(c.get("id")) for c in cells
                           if c.get("edge") != "1" and c.get("id") not in ("0", "1")]
        if len(set(vids)) != len(vids):
            重 = sorted({i for i in vids if vids.count(i) > 1})
            raise SystemExit(f"重复 id: {重}")
        节点集 = set(vids)
        边数 = 0
        for c in cells:
            if c.get("edge") != "1":
                continue
            源, 目标 = c.get("source"), c.get("target")
            if 源 or 目标:                      # 浮动折线没有 source/target, 跳过
                if 源 not in 节点集 or 目标 not in 节点集:
                    raise SystemExit(f"断链: {c.get('id')} {源} → {目标}")
                边数 += 1
        报纸.append((str(d.get("name")), len(vids), 边数))
    return 报纸


def main() -> None:
    xml = ('<mxfile host="app.diagrams.net">\n'
           + page("1-链路", "定时任务-链路", 827, 1169, build_p1()) + "\n"
           + page("2-定档与判据", "定时任务-定档判据", 827, 1169, build_p2()) + "\n"
           + "</mxfile>\n")
    OUT.write_text(xml, encoding="utf-8")
    for 名, 节点数, 边数 in 自检(OUT):
        print(f"  {名}: 节点 {节点数} · 连线 {边数}")
    print(f"写了 {OUT.name} · 断链 0 · 重复 id 0")


if __name__ == "__main__":
    main()

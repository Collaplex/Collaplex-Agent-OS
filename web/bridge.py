"""网页版的一条问答链 —— 只做搬运, 不重复实现业务规则。

判定(子 agent)/ 挑 skill / 递交 exec agent / 入库, 全部调 main.py 与 sub_agent.py
的现成函数; 这里只干两件事:

  ① 把回调式 on_event 转成可流式迭代的事件流(阻塞的活用工作线程跑, 主线程边收边吐);
  ② 主 agent 的流式增量**扣掉末尾那段 ```json 任务标记**再往界面送(那是给程序看的)。

★ 网页版与命令行必须走同一条链 —— 这里多写一句业务规则, 两边就会分叉。
"""

from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import exec_agent
import main as cli

_ROOT = Path(__file__).resolve().parent.parent        # 项目根
_RAG_SCRIPTS = _ROOT / "skill" / "rag" / "scripts"
if str(_RAG_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_RAG_SCRIPTS))

import store  # noqa: E402  (同项目模块, 得先补 sys.path)
import search  # noqa: E402  (语义检索那一套: resolve_model / build_retriever / search_with_alias)
import native_marks  # noqa: E402  (各家原生标记: 草稿流进正文区之前挡一道)
import outsource_hook
import sub_agent

if str(_ROOT) not in sys.path:                        # 根目录的接缝件(timers.py)
    sys.path.insert(0, str(_ROOT))
import manifest as 清单
import timers as 定时  # noqa: E402
import jobs as 作业  # noqa: E402 - 长活的账(过程里要把在跑/跑完报出来)

事件 = dict[str, Any]
历史表 = list[dict[str, str]]


def 该报吗(条: dict[str, Any], 已报: set[tuple[str, str]], 头一遍: bool) -> bool:
    """这一格作业要不要往「过程」里吐 —— 顺便把「看过」记进 已报。

    ★ 头一遍(每轮开场那一眼)只放「在跑」的过去: 账是**跨轮跨进程**留着的, 不这么挡,
      上一轮(甚至昨天)就跑完的活会在每轮开场被念一遍 —— 秒数是终值不会动, 看着像硬编码
      (2026-10-09 老板抓出「◉ 跑完 · 抓 B 站列表(12 秒) · 退出码 0 · 12 秒 怎么就定着了」)。
    ★ 记账要连"不报的"一起记, 否则下一遍它又冒出来。
    """
    键 = (str(条.get("号")), str(条.get("状态")))
    if 键 in 已报:
        return False
    已报.add(键)
    if 头一遍 and str(条.get("状态")) != "在跑":
        return False
    return True


class 事件泵:
    """回调式 on_event → 队列。阻塞的工作函数跑在工作线程里往这里塞事件。"""

    def __init__(self) -> None:
        self.队列: queue.Queue[tuple[str, str] | None] = queue.Queue()

    def __call__(self, kind: str, text: str) -> None:
        self.队列.put((kind, text))

    def 收尾(self) -> None:
        self.队列.put(None)

    def 取(self) -> tuple[str, str] | None:
        return self.队列.get()


def 看作业流(吐: Callable[[str, str], None], 停: threading.Event,
             账源: Callable[[], list[dict[str, Any]]], 每遍秒: float = 2.0) -> None:
    """作业账 → 「过程」里那几行: 每 每遍秒 对一次账, 起活 / 跑完各吐一行。

    ★ 为什么要有它(2026-10-09 老板定): 长活的状态属于「过程」, 跟这一轮的动作排在一起 ——
      不能起完就没影、也不能等到下一轮才看得见。跑完的那次交付仍由 取待办() 在下一轮
      开场带回来(这里只管看得见)。
    ★★ 开场那一遍只吐「在跑」的(老板抓出「◉ 跑完 · 抓 B 站列表(12 秒) · 退出码 0 · 12 秒
      怎么就定着了」): 账是跨轮跨进程留着的, 直接一扫, 上一轮(甚至昨天)就跑完的活会在每轮
      开场被当成「刚刚发生」念一遍 —— 秒数是终值不会动, 看着像硬编码。判据在 该报吗。
    ★ 拆成模块级函数是为了能真跑一次回归(tests/test_job_notes.py), 不是纯装饰。
    """
    已报: set[tuple[str, str]] = set()
    头一遍 = True
    while 头一遍 or not 停.wait(每遍秒):
        try:
            for 条 in 账源():
                if not 该报吗(条, 已报, 头一遍):
                    continue
                状态 = str(条.get("状态"))
                说 = 条.get("说明") or 条.get("命令") or "这件活"
                if 状态 == "在跑":
                    吐("note", f"◈ 起活 · {说}")
                else:
                    码 = 条.get("退出码")
                    尾 = f" · 退出码 {码}" if 码 is not None else ""
                    吐("note", f"◉ {状态} · {说}{尾} · {条.get('跑了')}")
        except Exception:                              # noqa: BLE001 - 看作业坏了不该影响主活
            pass
        头一遍 = False                             # ★ 放在循环尾: 这一遍里 头一遍 还得是真


def 边跑边报(工作: Callable[[], None], 泵: 事件泵) -> Iterator[tuple[str, str]]:
    """把阻塞的活丢线程, 主线程边收事件边往外吐; 活里的异常原样抛回调用方。

    ★ 线程里的异常必须取回来 —— 否则它只会死在那个线程里, 界面看着像卡住。
    """
    异常盒: list[BaseException] = []
    停 = threading.Event()

    def 壳() -> None:
        try:
            工作()
        except BaseException as 错:  # noqa: BLE001 - 一律转成事件, 不让工作线程把进程带崩
            异常盒.append(错)
        finally:
            停.set()                                   # ★ 先让看作业那条收手, 再放收尾哨
            泵.收尾()

    线程 = threading.Thread(target=壳, daemon=True)
    线程.start()
    看 = threading.Thread(target=看作业流, args=(泵, 停, 作业.列), daemon=True)
    看.start()
    while True:
        条 = 泵.取()
        if 条 is None:
            break
        yield 条
    线程.join(timeout=15)
    if 异常盒:
        raise 异常盒[0]


# 长得**整行**就是围栏的那一行(``` / ```json) —— 只有它要扣着, 见下面 可见尾巴
围栏行 = re.compile(r"^`{1,3}[A-Za-z0-9_-]*$")


class 可见尾巴:
    """流式时这一笔能吐到哪 —— 判据与 main.render_stream 逐字对齐。

    ★ 别拿"这行里有反引号"当判据(main.py 里明确写了这条): 回答一出现代码块,
      整段会被一路扣着不吐, 表现就是"实时输出没了"、最后一次性糊出来。
      只扣**整行长得像围栏**的那一行; 它后面一旦接了有内容的普通行, 立刻补吐。
    """

    def __init__(self) -> None:
        self.已吐 = 0
        self.挂起 = 0

    def 增量(self, 全文: str) -> str:
        藏起点 = cli.find_tail_json(全文)
        截止 = len(全文) if 藏起点 is None else 藏起点
        头 = 全文[:截止]
        行首 = 头.rfind("\n") + 1
        行 = 头[行首:]
        if 围栏行.match(行.strip()):
            self.挂起 = min(self.挂起, 行首) if self.挂起 else 行首
        elif self.挂起 and 行.strip():
            self.挂起 = 0
        安全 = self.挂起 or 截止
        if 安全 > self.已吐:
            片段 = 全文[self.已吐:安全]
            self.已吐 = 安全
            return 片段
        return ""

    def 收尾(self, 全文: str) -> str:
        """流完了: 把扣着的最后一行补上(除非它是那段 json 的一部分)。"""
        藏起点 = cli.find_tail_json(全文)
        截至 = len(全文) if 藏起点 is None else min(藏起点, len(全文))
        if 截至 > self.已吐:
            片段 = 全文[self.已吐:截至]
            self.已吐 = 截至
            return 片段
        return ""


def 掐掉尾部JSON(文本: str) -> str:
    """收尾: 把末尾那段 ```json 整块切掉, 只留给人看的正文。

    ★ 整段都被围栏吞掉时**不返回空串** —— 走 cli.捞正文 的兜底(2026-10-11):
      空串会让收尾那句 `if 正文.strip(): 记一轮(...)` 不成立, 这一轮就凭空消失。
    """
    return cli.捞正文(文本)[0]


def 流式自答(
    client: Any, model: str, 提示词: str, 问: str, extra_body: dict[str, Any]
) -> Iterator[事件]:
    """主 agent 自己答这一轮 —— 边生成边往界面吐增量(与命令行同一套参数)。"""
    开始 = perf_counter()
    完整 = ""
    可见 = 可见尾巴()
    用量: Any = None
    首个字时刻: list[float] = []

    流 = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": 提示词},
            {"role": "user", "content": 问},
        ],
        stream=True,
        stream_options={"include_usage": True},
        extra_body=extra_body or None,
    )

    for chunk in 流:
        if chunk.usage is not None:
            用量 = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        推理 = getattr(delta, "reasoning_content", None)
        if 推理:
            if not 首个字时刻:
                首个字时刻.append(perf_counter())
            yield {"kind": "think", "text": str(推理)}
        if not delta.content:
            continue
        if not 首个字时刻:
            首个字时刻.append(perf_counter())
        完整 += delta.content
        片段 = 可见.增量(完整)
        if 片段:
            yield {"kind": "answer", "text": 片段}

    尾巴 = 可见.收尾(完整)
    if 尾巴:
        yield {"kind": "answer", "text": 尾巴}
    干净, 说明 = cli.捞正文(完整)
    yield {"kind": "final", "text": 干净}
    # ★ 走了兜底就得说一声 —— 界面上得看得出"这轮模型没按规矩写正文"(2026-10-11)
    #   ★ 但"真一个字没吐"那条由 server 的 error 事件统一交代, 这里别重复说一遍
    if 说明 and 完整.strip():
        yield {"kind": "note", "text": 说明}
    收尾时刻 = perf_counter()
    用时 = 收尾时刻 - (首个字时刻[0] if 首个字时刻 else 开始)
    yield {"kind": "usage", "usage": cli.get_response_stats(用量, 用时), "全文": 完整}


def 一轮(问: str, 历史: 历史表, 配置: dict[str, Any],
        是提醒: bool = False) -> Iterator[事件]:
    """跑一轮完整问答, 把过程与答案边发生边吐成事件。

    ★ 是提醒=True: 这一轮是「定时到点把主 agent 叫醒」的那一轮(不是老板在说话) —— 只用它防自套娃。
    """
    开始 = perf_counter()
    # 定时: 给这一轮打记号(认「哪条定时是这一轮登记的」); 到点的提醒先并进这一轮的开场
    本轮记号 = 定时.开一轮()
    待办的提醒 = 定时.取待办()
    if 待办的提醒:
        # ★ 作业结果自己带 [作业] 牌子(形如 "[作业] 重洗语料（跑完·退出码 0，跑了 12 分）"),
        #   再套一层 "[定时] 到点了：" 会变成 "[定时] 到点了：[作业] …" —— 谁的东西谁挂牌。
        头 = "" if 待办的提醒.startswith("[作业]") else "[定时] 到点了："
        yield {"kind": "note", "text": f"{头}{待办的提醒}"}
        问 = f"{待办的提醒}\n（上面是你定的定时到点了，先办它；下面才是老板刚说的）\n{问}"
    yield {"kind": "stage", "text": "正在初始化…"}

    # ── 拦截: 问题先经子 agent(分析 / 检索记忆 / 按标准拼成 skill) ──
    泵 = 事件泵()
    盒子: dict[str, Any] = {}

    def 召回() -> None:
        盒子["prepared"] = sub_agent.prepare_skill(问, on_event=泵, 历史=历史)

    try:
        for kind, text in 边跑边报(召回, 泵):
            yield {"kind": kind, "text": text}
    except Exception as 错:
        yield {"kind": "error", "text": cli.explain_model_error(错)}
        yield {"kind": "note", "text": "子 agent 未接通，本轮回落主 agent 自行作答"}
        prepared: dict[str, Any] = cli.fallback_prepare()
    else:
        prepared = cast(dict[str, Any], 盒子.get("prepared") or cli.fallback_prepare())
    yield {"kind": "note", "text": cli.describe_intercept(prepared)}

    # ── 左链: 缺 skill -> 检索 -> 声明 -> 递交 exec agent ──
    检索词 = cli.retrieval_term(prepared, 问)
    if 检索词:
        if 检索词 == 问:
            yield {"kind": "note", "text": "主 agent 判定步骤无结论，以原话检索 skill"}
        try:
            picked = cli.find_skill_for(问, 检索词, 上下文=sub_agent.recent_turns_text(历史))
        except Exception as 错:
            # ★ 挑 skill 这一步也是调模型 —— 端点挂了不能让它把整条 SSE 带崩(实测会抛出 traceback,
            #   浏览器那边只看见流断在半路)。按"接不上就退"处理: 说清, 然后回落主 agent 作答。
            yield {"kind": "error", "text": cli.explain_model_error(错)}
            yield {"kind": "note", "text": "挑 skill 步骤未接通 —— 本轮回落主 agent 自行作答"}
            picked = None
        if picked is not None:
            声明 = str(picked["声明"])
            yield {"kind": "declaration", "text": 声明}
            yield {"kind": "note", "text": f"递交 exec agent（提示词 = {picked['name']}）"}
            briefing = sub_agent.command_library_briefing(str(picked["source"]), 问)
            if briefing:
                yield {"kind": "note", "text": "命令库：程序已预先检索条目，随任务注入 exec"}
            上下文 = sub_agent.memory_briefing(
                cast(list[dict[str, Any]], prepared.get("记忆") or [])
            )
            if 上下文:
                briefing = 上下文 + briefing
                yield {"kind": "note", "text": f"记忆: 随任务贴给 exec（{prepared['hits']} 条）"}
            执行泵 = 事件泵()
            执行盒: dict[str, Any] = {}

            def 干活() -> None:
                执行盒["res"] = exec_agent.run_task(
                    声明 + briefing,
                    skill_path=str(picked["skill_file"]),
                    on_event=执行泵,
                )

            try:
                # ★ exec 边想边说的那些话就是答案的草稿 —— 送去正文区边流边渲染, 最后那个 final
                #   会把草稿换成定稿。但模型吐的原文里夹着工具调用标记(<调用>…</调用> / DSML /
                #   官方模板那族), 直接流过去就是"一串原始md"(2026-10-09 老板两次点名) ——
                #   过一道 StreamFilter: 片片段段喂, 只吐人话, 协议块整块扣住。
                草稿滤 = native_marks.StreamFilter()
                # ★ 草稿也要扣住末尾那段 json 不打(与 流式自答 同一套判据 —— 可见尾巴):
                #   exec 这条支路原来把协议尾巴当正文一路吐出去(2026-10-11 真机测试抓到)。
                可见 = 可见尾巴()
                净草稿 = ""
                for kind, text in 边跑边报(干活, 执行泵):
                    yield {"kind": kind, "text": text}
                    if kind == "reply":
                        出 = 草稿滤.feed(text)
                        if 出:
                            净草稿 += 出
                            段 = 可见.增量(净草稿)
                            if 段:
                                yield {"kind": "answer", "text": 段}
                尾巴 = 草稿滤.flush()
                if 尾巴:
                    净草稿 += 尾巴
                    段 = 可见.增量(净草稿)
                    if 段:
                        yield {"kind": "answer", "text": 段}
                收尾段 = 可见.收尾(净草稿)
                if 收尾段:
                    yield {"kind": "answer", "text": 收尾段}
            except Exception as 错:
                yield {"kind": "error", "text": cli.explain_model_error(错)}
                return
            结果 = cast(dict[str, Any], 执行盒["res"])
            真跑过 = bool(结果["calls"])
            if 真跑过:
                yield {"kind": "note", "text": "已真跑命令 —— 记账任务投递后台，写入二层库"}
            else:
                yield {"kind": "note", "text": "未真跑命令，产出不计 —— 不入库"}
            # ★ 定稿也要过解析层(与 流式自答 同一条路): 交给 exec 的活, 它回的那份汇总里
            #   同样带末尾 json 标记 —— 原来原样端出去, 界面上糊一大块 json、存档里也存着
            #   (2026-10-11 真机集成测试抓到)。
            定稿, 说明 = cli.捞正文(str(结果["answer"]))
            if 说明:
                yield {"kind": "note", "text": 说明}
            # ★ 答案级引用核对(纯正则, 不调模型): 答案里的百分比/容量/核数/温度, 必须能在
            #   本轮命令的真输出里找到 —— 治"编新数"(跑着真命令却写出对不上的数, 2026-10-15
            #   本地 8B 答"根 12.3G / 87%"而真输出是 279G / 58%)。只提示, 绝不改答案:
            #   求和/换算出来的数天然不在单条输出里, 会被一并列出来当"待核"。
            try:
                对不上 = exec_agent.查没根据的数字(定稿, exec_agent.读本轮输出(结果))
            except Exception as 错:            # 核对本身绝不许把这一轮带崩
                print(f"[核对] 跳过(自身出错): {type(错).__name__}")
                对不上 = []
            if 对不上:
                例 = "、".join(对不上[:6])
                print(f"[核对] 引用对不上 {len(对不上)} 个: {例}")
                yield {"kind": "note",
                       "text": f"⚠ 引用核对：{len(对不上)} 个数字没在本轮命令输出里出现"
                               f"（{例}）—— 以命令输出为准，这些数别采信"}
            yield {"kind": "final", "text": 定稿}
            历史.append({"问": 问, "答": 定稿})
            历史[:] = 历史[-4:]

            # ★ 阻塞式定时（「就在这等着」）: 就在这一条流里等, 每秒吐一格 tick ——
            #   前端把同一格原地改写(逐秒新起一格 = 几小时上万格, 面板和存档都灌爆)。
            阻塞的 = 定时.本轮的阻塞条目(本轮记号)
            if 阻塞的:
                yield {"kind": "note",
                       "text": f"定时: 阻塞式 {len(阻塞的)} 条 —— 就在这一轮里等，每秒读秒"}
                for 条 in 阻塞的:
                    if 定时.重新计时(条):
                        yield {"kind": "note", "text": "定时：倒计时自「开始等待」时刻重新起算"}
                    等泵 = 事件泵()

                    def 等着() -> None:
                        定时.等阻塞(
                            条, lambda 剩: 等泵("tick", f"还剩 {定时.剩余说法(剩)} …")
                        )

                    for kind, text in 边跑边报(等着, 等泵):
                        yield {"kind": kind, "text": text}
                # 到点的那条这会儿已是「到点待注入」: 马上再跑一轮, 把主 agent 叫醒
                到点话 = 定时.取待办()
                if 到点话 and not 是提醒:
                    yield {"kind": "note", "text": f"[定时] 到点了（这一轮开场先办它）：{到点话}"}
                    yield from 一轮(到点话, 历史, 配置, 是提醒=True)
                    return

            yield {"kind": "done", "text": "", "用时": round(perf_counter() - 开始, 1)}
            if 真跑过:
                后台入库(
                    问,
                    定稿,
                    配置,
                    声明=声明,
                    文件=cast(list[str], 结果.get("output_files") or []),
                )
            return

    # ── 外援自动触发(程序判, 不许模型自己说"拿不准") ──
    prepared["左链检索不到"] = bool(检索词)
    慢 = round(perf_counter() - 开始, 1)
    try:
        摇人 = outsource_hook.decide(问, prepared, 慢)
    except Exception as 错:
        yield {"kind": "note", "text": f"外援判据没跑起来: {错}"}
        摇人 = {"摇": False}
    if 摇人.get("摇"):
        yield {"kind": "note", "text": f"外援自动触发（{摇人['因为']}）"}
        try:
            摇来的 = outsource_hook.run(
                问, prepared, 慢, say=lambda 话: None
            )
        except Exception as 错:
            yield {"kind": "error", "text": cli.explain_model_error(错)}
            摇来的 = {"材料": "", "因为": "外援这趟出错了"}
        材料 = str(摇来的.get("材料") or "")
        if 材料:
            prepared["skill"] = f"{prepared['skill']}\n\n{材料}"
            yield {
                "kind": "note",
                "text": (
                    f"外援 {摇来的['级别']} 回来了（{摇来的['家']} · "
                    f"{float(摇来的['金额']):.5f} 元）→ 贴给主 agent 当参考"
                ),
            }
        else:
            yield {"kind": "note", "text": f"外援没接上: {摇来的.get('因为')}"}

    # ── 回落: 主 agent 自己答 ──
    try:
        client, model = sub_agent.build_client()
        路由 = sub_agent.load_routing()
        思考体, 思考注 = sub_agent.thinking_params(
            str(client.base_url), model, bool(prepared.get("think")), 路由
        )
    except Exception as 错:
        yield {"kind": "error", "text": cli.explain_model_error(错)}
        return
    yield {
        "kind": "note",
        "text": (
            f"思考 {'开' if prepared.get('think') else '关'}"
            f"（{prepared.get('think_source')}: {prepared.get('think_reason')}）| {思考注}"
        ),
    }

    全文 = ""
    try:
        for 事件条 in 流式自答(client, model, str(prepared["skill"]), 问, 思考体):
            if 事件条["kind"] == "usage":
                全文 = str(事件条.pop("全文"))
                yield {"kind": "note", "text": 统计一行(事件条["usage"])}
                yield 事件条
                break
            yield 事件条
    except Exception as 错:
        yield {"kind": "error", "text": cli.explain_model_error(错)}
        return

    干净 = 掐掉尾部JSON(全文)
    sub_agent.note_activity(cli.read_task_flag(全文), 问)
    历史.append({"问": 问, "答": 干净})
    历史[:] = 历史[-4:]
    yield {"kind": "done", "text": "", "用时": round(perf_counter() - 开始, 1)}
    后台入库(问, 干净, 配置, 来源="主 agent 自答（未经执行体验证）")


def 清单全单() -> dict[str, Any]:
    """还挂着的所有编排清单（输入框上面那个面板用）。"""
    return 清单.全单()


def 清单收工(对话id: str) -> int:
    """撤掉某个对话的清单 —— 面板自己消失。"""
    return 清单.收工(对话id)


def 作业列表() -> dict[str, Any]:
    """web 里那排作业卡要的数据 —— 起过的活 + 状态/退出码/日志尾(读不到就空着, 不要把设置页带崩)。"""
    import jobs as 作业

    try:
        return {"活": 作业.列()}
    except Exception as 错:                           # noqa: BLE001 - 账坏了不该把面板带崩
        return {"活": [], "说明": f"读作业账失败: {错}"}


def 定时列表() -> dict[str, Any]:
    """挂着/最近到点的定时(设置页那一节用). 只读. 表按进程分, 这里读的是 web 那张."""
    条目们 = 定时.列出()
    挂着的 = [条 for 条 in 条目们 if 条.get("状态") == "挂着"]
    return {
        "表": 定时.表(),
        "行键": 定时.行键(),
        "线程活着": 定时.线程活着(),
        "挂着": [
            {
                "id": 条.get("id"),
                "类型": 条.get("类型"),
                "到点": 条.get("到点"),
                "到点说法": 定时.到点说法(条),
                "提醒": 条.get("提醒"),
                "阻塞": bool(条.get("阻塞")),
            }
            for 条 in 挂着的
        ],
        "总数": len(挂着的),
        "全部条数": len(条目们),
    }


def 定时撤(编号: str = "", 最近: bool = False) -> dict[str, Any]:
    """撤掉一条定时(设置页那个「撤」按钮). 写操作, 只走 POST."""
    目标, 说明 = 定时.撤销(编号 or None, 最近=最近)
    return {"好": 目标 is not None, "说明": 说明}


def 后台入库(
    问: str,
    产出: str,
    配置: dict[str, Any],
    来源: str = "执行产出",
    声明: str = "",
    文件: list[str] | None = None,
) -> None:
    """入库丢后台线程跑 —— 嵌入服务被清洗那支占着时能等好几分钟, 不让界面陪着等。

    ★ 这一轮已经把答案给用户了; 入库是记账, 慢不该拖住对话。
    """

    def 干() -> None:
        try:
            落 = sub_agent.save_to_tier2(
                问,
                产出,
                dict(配置["rag"]),
                declaration=声明,
                output_files=文件,
                来源=来源,
            )
            print(f"[web] 后台入库: {落}", flush=True)
        except Exception as 错:  # 记账失手不该影响已经答完的这轮
            print(f"[web] 后台入库失败: {错}", flush=True)

    threading.Thread(target=干, daemon=True).start()


def 统计一行(用量: dict[str, Any]) -> str:
    """把用量讲成一行人话(与命令行的口径一致)。"""
    速度 = 用量.get("tokens_per_second")
    if 速度 is None:
        return "Token 用量或生成速度不可用（接口没返回 usage）"
    return (
        f"输入 {用量.get('prompt_tokens')}, 输出 {用量.get('completion_tokens')}, "
        f"合计 {用量.get('total_tokens')}; 生成速度 {float(速度):.2f} tokens/s"
    )


def 服务状态() -> dict[str, Any]:
    """给页面顶部用: 模型端点通不通、叫哪个模型。"""
    try:
        client, model = sub_agent.build_client()
        通, 说明 = sub_agent.check_endpoint(client, model)
    except Exception as 错:
        return {"通": False, "模型": "", "说明": str(错)}
    return {"通": bool(通), "模型": model, "说明": 说明}


def 读JSON(路径: Path) -> dict[str, Any]:
    """读个项目内的 json; 读不到就给空 dict —— 设置页不能因为一个文件坏了整页打不开。"""
    try:
        return cast(dict[str, Any], json.loads(路径.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


def 读开关(路径: Path, 键: str = "开关") -> object:
    """开关显示成三态: True/False 由界面画成开/关, 配置里压根没写就说"没写"(不要把缺项当"关")。

    键可以是点路径(如 sub_agent.json 的 skill_retrieval.enabled) —— 有些开关是嵌着放的。
    """
    节点: Any = 读JSON(路径)
    for 层 in 键.split("."):
        if not isinstance(节点, dict) or 层 not in 节点:
            return "没写"
        节点 = cast(dict[str, Any], 节点[层])
    return 节点 if isinstance(节点, (bool, str)) else "没写"


接口组: list[dict[str, str]] = [
    {"名": "主线", "前缀": "OPENAI", "说明": "主 agent 回答 + 子 agent 分析与判断"},
    {"名": "子agent", "前缀": "SUBAGENT", "说明": "分析要查什么 / 判断缺不缺 skill"},
    {"名": "执行体", "前缀": "EXEC", "说明": "exec agent 真跑命令那一支"},
    {"名": "向量模型", "前缀": "EMBEDDING", "说明": "检索用的嵌入服务（:8199）"},
]
开关表: dict[str, tuple[str, str]] = {
    "左链 skill 检索": ("config/sub_agent.json", "skill_retrieval.enabled"),
    "外援自动触发": ("config/outsource_trigger.json", "开关"),
    "外援(手动摇)": ("skill/outsource/resources/outsource.json", "开关"),
    "交叉验证(mtp)": ("skill/mtp/resources/mtp.json", "开关"),
    "思考路由默认档": ("config/think_routing.json", "默认开关"),
}
说明表: dict[str, str] = {
    "左链 skill 检索": "问题先经子 agent 判定 skill 是否缺失并检索 —— 关闭后仅主 agent 自行作答",
    "外援自动触发": "左链未接住时，程序按判据决定是否调用云端（默认关闭）",
    "外援(手动摇)": "外援 skill 自身的预算开关 —— 关闭时，命令亦无法调用",
    "交叉验证(mtp)": "同一问题问多家，答案并排作为参考材料",
    "思考路由默认档": "关键词与子 agent 均未表态时，主 agent 本轮是否启用长思考",
}
ENV_PATH = Path(sub_agent.HERE) / ".env"


def 掩码(值: str) -> str:
    """密钥只回尾 4 位 —— 页面永远拿不到全量, 也就没法把全量写回文件。"""
    return "" if not 值 else "····" + 值[-4:]


def 接口现状() -> list[dict[str, Any]]:
    组们: list[dict[str, Any]] = []
    for 组 in 接口组:
        前缀 = 组["前缀"]
        值 = {名: os.getenv(f"{前缀}_{名}", "") for 名 in ("BASE_URL", "MODEL", "API_KEY")}
        在用 = bool(值["BASE_URL"] or 值["MODEL"])
        组们.append({
            "名": 组["名"],
            "端点": 值["BASE_URL"],
            "模型": 值["MODEL"],
            "密钥": 掩码(值["API_KEY"]),
            "在用": 在用,
            "说明": 组["说明"] + ("" if 在用 or 前缀 == "OPENAI" else " —— 现在是空的"),
            "能改": True,
        })
    return 组们


def 备份env() -> Path:
    """改 .env 之前先留一份 —— 老板的凭据文件, 改坏了必须能退回去。"""
    备份目录 = Path(sub_agent.HERE) / "state" / "env-backup"
    备份目录.mkdir(parents=True, exist_ok=True)
    到 = 备份目录 / f"{datetime_now()}.env"
    if ENV_PATH.is_file():
        到.write_text(ENV_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return 到


def datetime_now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d-%H%M%S")


def 改env(改动: dict[str, str | None]) -> list[str]:
    """按行改 .env: 活行改值 / 注释行放开 / 没有的键追加。值传 None = 注释掉(回到"没配"形态)。

    ★ 只动点名的那几行 —— 别的注释、分段、顺序原样留着(这是老板手写的文件)。
    """
    if not ENV_PATH.is_file():
        raise FileNotFoundError(f".env 不在: {ENV_PATH}")
    行们 = ENV_PATH.read_text(encoding="utf-8").splitlines()
    做了: list[str] = []
    for 键, 值 in 改动.items():
        模式 = re.compile(rf"^\s*#?\s*{re.escape(键)}\s*=")
        命中 = [i for i, 行 in enumerate(行们) if 模式.match(行)]
        if 命中:
            位 = 命中[-1]
            旧行 = 行们[位]
            if 值 is None:
                行们[位] = "# " + 旧行.lstrip("# ").strip()
                os.environ.pop(键, None)
                做了.append(f"{键} → 清空(跟随上一级)")
            else:
                行们[位] = f"{键}={值}"
                os.environ[键] = 值
                做了.append(f"{键} → {掩码(值) if 'KEY' in 键 else 值}")
        elif 值 is not None:
            行们.append(f"{键}={值}")
            os.environ[键] = 值
            做了.append(f"{键} → 新加一行")
    ENV_PATH.write_text("\n".join(行们) + "\n", encoding="utf-8")
    return 做了


def 改JSON开关(相对路径: str, 点路径: str, 值: bool) -> None:
    """改配置里的一个开关。

    ★ 只替换那个布尔字面量, 其余字节原样不动 —— 这些配置是老板手写排版的(数组压在一行),
      整份 json.dumps 重写会把他的排版全冲成多行。只有定位不到唯一一处时才退回重写。
    """
    路径 = Path(sub_agent.HERE) / 相对路径
    原文 = 路径.read_text(encoding="utf-8")
    数据 = 读JSON(路径)
    if not 数据:
        raise ValueError(f"配置读不出来: {相对路径}")
    层们 = 点路径.split(".")
    节点: Any = 数据
    for 层 in 层们:
        if not isinstance(节点, dict) or 层 not in 节点:
            raise KeyError(f"{相对路径} 里没有 {点路径}")
        节点 = cast(dict[str, Any], 节点[层])
    新字面 = "true" if 值 else "false"
    模式 = re.compile(rf'^(\s*"{re.escape(层们[-1])}"\s*:\s*)(true|false)(,?)\s*$', re.MULTILINE)
    命中 = 模式.findall(原文)
    if len(命中) == 1:
        路径.write_text(模式.sub(lambda 取: 取.group(1) + 新字面 + 取.group(3), 原文), encoding="utf-8")
        return
    # 兜底: 名字不唯一(嵌套里重名)或压根没写 → 按点路径写入, 整份重写
    节点写: dict[str, Any] = 数据
    for 层 in 层们[:-1]:
        下 = 节点写.get(层)
        if not isinstance(下, dict):
            raise KeyError(f"{相对路径} 里没有 {层}")
        节点写 = cast(dict[str, Any], 下)
    节点写[层们[-1]] = 值
    路径.write_text(json.dumps(数据, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rag配置() -> dict[str, Any]:
    """读 rag 的 resources/embed.json(判断走 JSON 还是 PG)."""
    落点 = _ROOT / "skill" / "rag" / "resources" / "embed.json"
    try:
        data: Any = json.loads(落点.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cast(dict[str, Any], data) if isinstance(data, dict) else {}


def 索引条数(路径: Path) -> int:
    """数索引条数. 走 PG 后端时直接从库查(那时没有 JSON 文件)."""
    tier = {"vector-index.json": "2", "memory-index.json": "3"}.get(路径.name)
    if tier is not None:
        配置 = _rag配置()
        if store.is_pg(配置):
            try:
                with store.connect(配置) as conn:
                    return store.count(conn, 配置, tier)
            except Exception:
                return 0
    条目 = 读JSON(路径).get("items")
    if not isinstance(条目, list):
        return 0
    return len(cast(list[object], 条目))


def 库概览() -> dict[str, Any]:
    """三层各多少条、各来源多少条 —— 设置页「数据库」节打头那块。"""
    try:
        配置 = _rag配置()
        with store.connect(配置) as conn:
            return store.概览(conn, 配置)
    except Exception as 错:  # noqa: BLE001 - 读库失败也不该把整页弄崩
        return {"每层": {}, "共": 0, "来源": [], "说明": f"读库失败: {错}"}


def 库里翻(
    层: str = "1", 偏移: int = 0, 每页: int = 50, 关键词: str = "", 来源: str = ""
) -> dict[str, Any]:
    """表格一页(不带向量)。命令行看的是同一张表, 这里不另立一份真相。"""
    try:
        配置 = _rag配置()
        with store.connect(配置) as conn:
            return store.翻页(conn, 配置, 层, 偏移, 每页, 关键词, 来源)
    except Exception as 错:  # noqa: BLE001
        return {"行": [], "共": 0, "偏移": int(偏移), "每页": int(每页), "说明": f"读库失败: {错}"}


def 库里搜(词: str, 层: str = "1", 数: int = 20) -> dict[str, Any]:
    """语义为主 + 关键词兜底(老板定)。

    语义路走 search.py 那一整套(嵌入 -> pgvector HNSW), 连别名表一起用, 要求 8199 在跑;
    关键词路是 SQL ILIKE, 零依赖。

    ★ 只有"语义路整条不可用"(服务没起/超时/异常)才落兜底 —— 命中 0 条**不算失败**:
      那是语义层在回答"没有", 不该被字面匹配覆盖。
    """
    纯 = 词.strip()
    if not 纯:
        return {"词": 纯, "层": 层, "走": "空查询", "命中": []}
    try:
        配置 = _rag配置()
        模型 = search.resolve_model()
        检索器, 层名, 总数, 说明 = search.build_retriever(配置, 层)
        结果, 别名 = search.search_with_alias(纯, 配置, 模型, 检索器, max(int(数), 1))
        return {
            "词": 纯, "层": 层, "层名": 层名, "走": 说明, "该层共": int(总数),
            "别名": 别名, "命中": 结果,
        }
    except Exception as 错:  # noqa: BLE001 - 语义路塌了就落兜底, 不是把页面弄崩
        try:
            配置 = _rag配置()
            with store.connect(配置) as conn:
                结果 = store.按词搜(conn, 配置, 层, 纯, max(int(数), 1))
            return {"词": 纯, "层": 层, "走": f"关键词兜底(语义路不可用: {错})", "命中": 结果}
        except Exception as 兜错:  # noqa: BLE001
            return {"词": 纯, "层": 层, "走": f"两条路都失败: {兜错}", "命中": []}


def _讲讲(目录: Path) -> str:
    """从 SKILL.md 的 frontmatter 摘一句 description（页面一行放得下就行）。"""
    文件 = 目录 / "SKILL.md"
    if not 文件.is_file():
        return ""
    for 行 in 文件.read_text(encoding="utf-8").splitlines()[:20]:
        if 行.startswith("description:"):
            值 = 行.split(":", 1)[1].strip().strip("\"'")
            return 值.split("。")[0][:72]
    return ""


def 技能表() -> dict[str, Any]:
    """skill 名册：名字 + 开关 + 一句话说明 —— 设置页「Skill」节打头用（盘上有几个就列几个）。"""
    try:
        配置 = sub_agent.load_config()
        开关原 = 配置.get("skills")
        开关: dict[str, Any] = cast(dict[str, Any], 开关原) if isinstance(开关原, dict) else {}
        行们: list[dict[str, Any]] = []
        for 目录 in sorted((_ROOT / "skill").glob("*/")):
            名 = 目录.name
            行们.append({
                "name": 名,
                "on": 开关.get(名, True) is not False,
                "说明": _讲讲(目录),
            })
        return {"技能": 行们, "关掉的": sorted(sub_agent.关掉的技能())}
    except Exception as 错:  # noqa: BLE001 - 页面不能因为读配置失败整页打不开
        return {"技能": [], "说明": f"读配置失败: {错}"}


def 技能搜词(词: str) -> dict[str, Any]:
    """拿一句话找该用哪个 skill —— 走 agent 自己那条检索（sub_agent.search_skills）。

    ★ 刻意不另写一套：页面上搜出来的，与 agent 真实挑 skill 时看到的是同一份结果。
      要改算法就改那条，别在这儿分叉。
    """
    纯 = 词.strip()
    if not 纯:
        return {"词": 纯, "命中": []}
    try:
        配置 = sub_agent.load_config()
        候选 = sub_agent.search_skills(纯, dict(配置["skill_search"]))
        return {
            "词": 纯,
            "命中": [
                {
                    "name": 条["name"],
                    "说明": 条["description"],
                    "score": 条["score"],
                    "来源": str(条["source"]),
                }
                for 条 in 候选
            ],
            "关掉的": sorted(sub_agent.关掉的技能()),
        }
    except Exception as 错:  # noqa: BLE001
        return {"词": 纯, "命中": [], "说明": f"检索失败: {错}"}


def 技能开关(名: str, 开: bool) -> dict[str, Any]:
    """开关一个 skill —— 写进 config/sub_agent.json 的 `skills` 段。

    ★ 写的是整段（不是就地补一行）：配置给人看，顺序稳定才好看 diff。
    ★ 原子替换（写临时文件再 rename）：写一半被打断会留半截 JSON，agent 直接读不了。
    """
    合法 = sorted(p.name for p in (_ROOT / "skill").glob("*/"))
    if 名 not in 合法:
        return {"好": False, "说明": f"没有这个 skill: {名}"}
    路径 = _ROOT / "config" / "sub_agent.json"
    原文 = json.loads(路径.read_text(encoding="utf-8"))
    段原 = 原文.get("skills")
    段: dict[str, Any] = dict(cast(dict[str, Any], 段原)) if isinstance(段原, dict) else {}
    for 一个 in 合法:  # 缺的补上（老配置没有这段时，一次写全）
        段.setdefault(一个, True)
    段[名] = bool(开)
    原文["skills"] = {k: 段[k] for k in sorted(段)}
    临时 = 路径.with_name(路径.name + ".写中")
    临时.write_text(json.dumps(原文, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    临时.replace(路径)
    return {"好": True, "名": 名, "开": bool(开), "关掉的": sorted(sub_agent.关掉的技能())}


# ────────────────────────── 日志 ──────────────────────────
# 分类按"谁产生的"分, 不按文件名 —— 老板要的是"一眼知道该看哪一类"。
# (显示名, 文件/目录名, 说明, 什么时候才会有)
# ★ 第四栏是给「还没有」配的实话 —— 只写"还没有"会被读成"没接线"（老板 2026-10-12）。
#   按这台机器有没有那套能力给不同的说法：Windows 包不装本地主模型、看门狗正常启动不挂、
#   清洗要走 Linux 侧 cron 管线 —— 这些在这台机器上**本来就不会产生**，得说明白。
def _有没有本地主模型() -> bool:
    try:
        import sub_agent  # noqa: PLC0415

        return (Path(sub_agent.HERE) / "vendor" / "llama.cpp" / "build" / "bin" / "llama-server").is_file()
    except Exception:  # noqa: BLE001
        return False


def 日志表内容() -> list[tuple[str, str, str, str]]:
    有主模型 = _有没有本地主模型()
    是Windows = os.name == "nt"
    return [
        ("主模型", "chat.log", "llama.cpp 主模型(:8790) 的推理输出与请求记录",
         "「以本地模型启动」起来后才产生" if 有主模型 else "这台机器没装本地主模型 —— 不会有"),
        ("向量模型", "embed.log", "嵌入服务(:8199) 的请求记录",
         "启动链会把它拉起来 —— 起来后就有"),
        ("看门狗", "watchdog.log", "四个服务谁挂拉谁的记录",
         "启动链会把它挂上 —— 盯主模型/向量/web/PG，谁挂拉谁"),
        ("清洗", "refine.log", "热层下沉到经验层的清洗记录",
         "启动链会把它挂上 —— 到点自己下沉一轮" if not 是Windows
         else "由启动链挂的「看守」进程写 —— 这台机器（Windows 包）没有 Linux 侧 cron 那条路"),
        ("网页", "web.log", "看门狗拉起的 web 服务自己的输出",
         "web 服务一跑就有"),
        ("启动", "启动.log", "启动链逐步记录（依次启动 PG / 模型 · 检查单 · 自检 · 看门狗）",
         "每次启动都会写"),
        ("执行记录", "exec", "exec agent 真跑过的命令的完整输出（一条命令一个文件）",
         "让它真跑过命令才有"),
        ("外援记账", "outsource", "每摇一次外援的流水（家 / 金额 / 秒 / 题）",
         "摇过外援才有"),
        ("交叉验证", "mtp", "多家答同一题的并排记录",
         "跑过交叉验证才有"),
    ]


日志表: list[tuple[str, str, str, str]] = 日志表内容()


def _时刻(时间戳: float) -> str:
    """unix 时间 → `月-日 时:分:秒`（日志页要看"最后什么时候写的"）。"""
    return time.strftime("%m-%d %H:%M:%S", time.localtime(时间戳))


# ★ 同一类日志在不同平台可能落在不同文件名上（Windows 包里 web 的输出由启动器落 panel.log，
#   Linux 走看门狗时才是 web.log）—— 别名表让两边都能看见（2026-10-12 实测）。
日志别名: dict[str, tuple[str, ...]] = {
    "web.log": ("web.log", "panel.log"),
}


def _挑日志路径(目: str) -> Path:
    """日志可能在两个地方 —— 应用自己写的在 app/logs，启动器/向量服务写的在安装目录/logs。

    ★ Windows 包里是劈开的（embed.log / panel.log 在安装目录下、启动.log 在 app/logs），
      只认一个根就会出现「九类日志里八类显示还没有」—— 2026-10-12 实测。
    """
    候选 = 日志别名.get(目, (目,))
    for 名 in 候选:
        for 甲 in (_ROOT / "logs" / 名, _ROOT.parent / "logs" / 名):
            if 甲.exists():
                return 甲
    return _ROOT / "logs" / 候选[0]


def 日志分类() -> dict[str, Any]:
    """设置页「日志」节：有哪些日志、各多大、最后什么时候写的。

    ★ 文件不存在也照样列出来（标"还没有"）—— 否则点进来看到一片空白,
      反而不知道本来该有什么。
    """
    出: list[dict[str, Any]] = []
    for 名, 目, 说明, 何时 in 日志表:
        甲 = _挑日志路径(目)
        if 甲.is_dir():
            件 = sorted(
                (p for p in 甲.glob("*") if p.is_file()),
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            出.append({
                "名": 名, "说明": 说明, "何时": 何时, "目录": 目, "有": bool(件),
                "个数": len(件), "字节": sum(p.stat().st_size for p in 件),
                "改于": _时刻(件[0].stat().st_mtime) if 件 else "—",
            })
        else:
            st = 甲.stat() if 甲.is_file() else None
            出.append({
                "名": 名, "说明": 说明, "何时": 何时, "目录": "", "有": st is not None,
                "个数": 1 if st else 0, "字节": st.st_size if st else 0,
                "改于": _时刻(st.st_mtime) if st else "—",
            })
    return {"类": 出}


def 读日志(名: str, 行数: int = 300) -> dict[str, Any]:
    """取某一类日志的尾巴。目录类（执行记录等）取**最新那个文件**。"""
    找 = [x for x in 日志表 if x[0] == 名]
    if not 找:
        return {"名": "", "行": [], "说明": f"没有这一类: {名}", "文件": "", "共": 0}
    _, 目, 说明, _何时 = 找[0]
    甲 = _挑日志路径(目)
    if 甲.is_dir():
        件 = sorted(
            (p for p in 甲.glob("*") if p.is_file()),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not 件:
            return {"名": 名, "行": [], "说明": 说明, "文件": 目 + "/", "共": 0}
        甲 = 件[0]
    if not 甲.is_file():
        return {"名": 名, "行": [], "说明": 说明, "文件": 目, "共": 0}
    try:
        全部 = 甲.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as 错:
        return {"名": 名, "行": [], "说明": f"读不了: {错}", "文件": 目, "共": 0}
    n = max(1, min(行数, 2000))       # 别让人一次把几 MB 全拽到浏览器
    st = 甲.stat()
    return {
        "名": 名, "说明": 说明, "文件": 目,
        "行": 全部[-n:], "共": len(全部), "字节": st.st_size, "改于": _时刻(st.st_mtime),
    }


def 设置() -> dict[str, Any]:
    """设置页的现状 —— 全部从现成配置/函数读, 不另立一份真相(老板改了文件这里就跟着变)。

    ★ 只读: 网页不写配置。要动架构参数还是去改 config/ 与 skill 里的文件。
    """
    根 = Path(sub_agent.HERE)
    配置 = sub_agent.load_config()
    预算配置 = dict(cast(dict[str, Any], 配置.get("budget") or {}))
    窗口 = sub_agent.current_context_window() or int(预算配置.get("fallback_context_window") or 0)
    只读区 = 0
    try:
        主skill = sub_agent.load_main_skill(配置)
        只读区 = sub_agent.estimate_tokens(主skill) + sub_agent.estimate_tokens("当前问题:\n（空）")
    except OSError:
        pass
    try:
        预算 = sub_agent.ContextBudget.from_config(
            {**预算配置, "context_window": 窗口, "readonly_reserve": 只读区}
        )
        预算行 = {
            "窗口": 窗口,
            "skill 预算(窗口×40%)": 预算.total,
            "输出预留": 预算.output_reserve,
            "只读区(主skill+问题)": 预算.readonly_reserve,
            "记忆名额": 预算.available,
        }
    except (KeyError, TypeError, ValueError):
        预算行 = {"窗口": 窗口, "说明": "预算配置缺项，无法计算名额"}

    语料目录 = 根 / "skill/rag/corpus"
    服务 = 服务状态()
    return {
        "接口": 接口现状(),
        "项目": {
            "根目录": str(根),
            "会话存档": "state/web-对话.jsonl",
            "语料": "skill/rag/corpus",
        },
        "模型": {
            "名字": 服务["模型"] or os.getenv("OPENAI_MODEL", ""),
            "端点": os.getenv("OPENAI_BASE_URL", ""),
            "端点通": 服务["通"],
            "说明": 服务["说明"],
            "执行体端点": os.getenv("EXEC_BASE_URL", "") or "（跟主线同一套）",
        },
        "预算": 预算行,
        "库": {
            "二层热库": 索引条数(根 / "skill/rag/scripts/vector-index.json"),
            "三层冷库": 索引条数(根 / "skill/rag/scripts/memory-index.json"),
            "语料文件": len(list(语料目录.glob("*.md"))) if 语料目录.is_dir() else 0,
        },
        "开关": [
            {
                "名": 名,
                "值": 读开关(根 / 落点[0], 落点[1]),
                "说明": 说明表.get(名, ""),
                "落点": 落点[0],
            }
            for 名, 落点 in 开关表.items()
        ],
        "skills": sorted(件.name for 件 in (根 / "skill").iterdir() if (件 / "SKILL.md").is_file()),
    }


def 存设置(改动: dict[str, Any]) -> dict[str, Any]:
    """界面上点了"保存"就走这儿 —— 写 .env(三支 agent 的接口) + 写各 skill 的开关。

    ★ 全部写完立刻生效: .env 的值同时灌进 os.environ(build_client 是每轮现读);
      开关是每轮现读配置文件的, 下一问就按新值走。
    ★ 密钥只认"传了才改": 页面上留空 = 不动; 传空串 = 清空; 其余 = 设置(页面拿不到旧的全量)。
    """
    做了: list[str] = []
    要写env: dict[str, str | None] = {}
    改了env = False

    for 项 in cast(list[dict[str, Any]], 改动.get("接口") or []):
        名 = str(项.get("名") or "")
        组 = next((组 for 组 in 接口组 if 组["名"] == 名), None)
        if 组 is None:
            continue
        前缀 = 组["前缀"]
        端点 = str(项.get("端点", "")).strip()
        模型 = str(项.get("模型", "")).strip()
        要写env[f"{前缀}_BASE_URL"] = 端点 or None
        要写env[f"{前缀}_MODEL"] = 模型 or None
        改了env = True
        if "密钥" in 项:
            钥 = str(项.get("密钥") or "").strip()
            要写env[f"{前缀}_API_KEY"] = 钥 or None
        elif not 端点 and not 模型:
            # 整组清空 = 回到"跟上一级同一套": 密钥也得跟着清, 否则成了"借主线端点、却带自己的 key"
            要写env[f"{前缀}_API_KEY"] = None

    if 改了env and 要写env:
        备份 = 备份env()
        做了.append(f"改了 .env(先备份到 {备份.relative_to(Path(sub_agent.HERE))})")
        做了.extend(改env(要写env))

    开关改动 = cast(dict[str, Any], 改动.get("开关") or {})
    for 名, 值 in 开关改动.items():
        落点 = 开关表.get(名)
        if 落点 is None:
            continue
        改JSON开关(落点[0], 落点[1], bool(值))
        做了.append(f"{名} → {'开' if 值 else '关'}(写进 {落点[0]})")

    return {"改了": 做了, "设置": 设置()}


if __name__ == "__main__":  # 自检: 不碰网络与模型, 只验扣围栏/切尾巴这两处纯函数
    可见 = 可见尾巴()
    assert 可见.增量("正文一\n") == "正文一\n"
    assert 可见.增量("正文一\n\n```py") == "\n"                     # 整行像围栏 -> 只扣这一行
    # 围栏后面接了有内容的普通行 -> 立刻补吐(★ 不要把整个代码块一起扣住)
    assert 可见.增量("正文一\n\n```py\nprint(1)") == "```py\nprint(1)"
    assert 可见.收尾("正文一\n\n```py\nprint(1)") == ""
    带标记 = '正文二\n\n```json\n{"任务结束": false}\n```'
    assert 掐掉尾部JSON(带标记) == "正文二", 掐掉尾部JSON(带标记)
    assert 掐掉尾部JSON("没有标记") == "没有标记"
    尾巴 = 可见尾巴()
    assert 尾巴.增量(带标记).strip() == "正文二"            # json 那段从一开始就不吐
    assert 尾巴.收尾(带标记) == ""
    print("bridge 自检通过")

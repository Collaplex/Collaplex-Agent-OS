#!/usr/bin/env python3
"""外援的自动触发 —— ★ 程序判, 不许模型自己说"拿不准".

落点只有一处: 左链未接住、本应"回落自行作答"的那一站(main.py)。
判据三条(全在 config/outsource_trigger.json 里, 可调):

    ① 要成段代码      用户这轮明摆着要写/改代码
    ② 左链检索不到    检索不出候选 skill(它本来会回"我没有这个能力")
    ③ 卡了明显时间    从提问到这一站已经花掉的秒数超阈值

摇来的东西**贴进主 agent 的 skill 里** —— 由主 agent 自己综合/呈现, **这一件不替它下结论**。
外援不行(空答 / 报错 / 超时) 才升到 mtp(交叉验证); mtp 也不行 → 维持原样
(该说"没有"就说"没有"), 绝不静默换成其他内容。

依据(2026-10-07 实测, 6 道题程序判分): 本地 5/6 · 外援 6/6; 本地 28~156 秒 vs 外援 0.8~2.5 秒。
→ 该摇人排第一的是「要成段、要能跑的代码」, 其次才是"用户等不起"; 推理题两边打平, 不摇。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, cast

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "skill" / "outsource" / "scripts"))
sys.path.insert(0, str(HERE / "skill" / "mtp" / "scripts"))

import ask                                    # noqa: E402  skill/outsource/scripts
import budget                                 # noqa: E402
import exec_agent                             # noqa: E402
import panel                                  # noqa: E402  skill/mtp/scripts

TRIGGER_PATH = HERE / "config" / "outsource_trigger.json"
SHORT_REPLY = 24        # 外援回来的东西短于这个长度就当没答上来(空答/一句废话)


def load_trigger(path: Path | None = None) -> dict[str, Any]:
    """读触发配置. 文件不在就抛错 —— 不内置默认值兜(兜了等于把配置藏进代码)."""
    target = path if path is not None else TRIGGER_PATH
    data: object = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"触发配置得是个字典: {target}")
    return cast(dict[str, Any], data)


def _words(value: object) -> list[str]:
    return [str(item) for item in budget.as_list(value)]


def _text_of(*parts: str) -> str:
    return " ".join(part for part in parts if part)


def wants_code(question: str, declaration: str = "", trigger: dict[str, Any] | None = None) -> bool:
    """这轮是不是明摆着要写/改代码.

    ★ 两道, 缺一不摇 (词表命中即定, 模型改不了):
        ① 强命中词单独命中即真 (报错 / 调试 / 重构 / 写代码 这类本身就是代码语境的词)
        ② 否则要 **动作词 × 代码名词 同句出现** (写 + 函数 / 改 + 脚本 ...)

    原先只有一层词表(裸的 函数 / 代码 / 写个 也算命中), 实测把知识题和写作题一起拽了进来:
    「解释一下 Python 里函数和方法有什么区别」「帮我写个请假条」「代码里的注释用中文还是英文」
    —— 三道本地都答得上, 却全被判成"要成段代码"(13 题误触发对照里边界组 3/3 全中)。
    """
    config = trigger if trigger is not None else load_trigger()
    section = budget.as_dict(config.get("要成段代码"))
    if not bool(section.get("开")):
        return False
    asked = _text_of(question, declaration)
    if any(word and word in asked for word in _words(section.get("强命中词"))):
        return True
    has_verb = any(word and word in asked for word in _words(section.get("动作词")))
    has_noun = any(word and word in asked for word in _words(section.get("代码名词")))
    return has_verb and has_noun


def vetoed(question: str, declaration: str = "", trigger: dict[str, Any] | None = None) -> str:
    """命中「不摇」词表就返回那个词, 否则空串 —— 否决权优先. 这些是机器状态/闲聊, 外援帮不上."""
    config = trigger if trigger is not None else load_trigger()
    asked = _text_of(question, declaration)
    for word in _words(config.get("不摇")):
        if word and word in asked:
            return word
    return ""


def decide(
    question: str,
    prepared: dict[str, Any],
    elapsed: float,
    trigger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """★ 程序判定: 本轮是否调用外援. 返回 {摇, 因为, 级别, 题}.

    级别: "outsource"(一级) / "mtp"(二级, 由 run() 在一级失败后才用) / ""(不调用)
    """
    config = trigger if trigger is not None else load_trigger()
    declaration = str(prepared.get("声明") or "")
    wanted = str(prepared.get("wanted") or "")
    task = declaration or wanted or question

    if not bool(config.get("开关")):
        return {"摇": False, "因为": "自动触发关着(手动能摇)", "级别": "", "题": task}

    hit = vetoed(question, task, config)
    if hit:
        return {"摇": False, "因为": f"命中「不摇」词表：{hit}", "级别": "", "题": task}

    if wants_code(question, task, config):
        return {"摇": True, "因为": "要成段代码(实测本地 2/3 · 外援 3/3, 且快 30~50 倍)", "级别": "outsource", "题": task}

    missing = budget.as_dict(config.get("左链检索不到"))
    if bool(missing.get("开")) and bool(prepared.get("左链检索不到")):
        return {"摇": True, "因为": "左链检索不出候选 skill(本来要回「我没有这个能力」)", "级别": "outsource", "题": task}

    slow = budget.as_dict(config.get("卡了明显时间"))
    if bool(slow.get("开")) and elapsed >= float(slow.get("秒") or 0):
        return {"摇": True, "因为": f"已经花了 {elapsed:.0f} 秒(阈值 {slow.get('秒')} 秒)", "级别": "outsource", "题": task}

    return {"摇": False, "因为": f"三条判据都没命中(花了 {elapsed:.1f} 秒)", "级别": "", "题": task}


def build_material(level: str, house: str, model: str, seconds: float, cost: float, content: str) -> str:
    """把外援/交叉验证的产出包成"参考材料" —— 交给主 agent, 由它自己综合."""
    if level == "mtp":
        head = (
            "【交叉验证参考材料 · 几家模型答同一题】\n"
            f"来源: {house} · 并行 {seconds:.1f} 秒 · 共 {cost:.5f} 元\n"
            "★ 这是**参考**, 不是结论: 各家答案和分歧都摆着了, 你自己综合, 说清你采信了谁、为什么。\n\n"
        )
    else:
        head = (
            "【外援给的参考答案】\n"
            f"来源: {house}/{model} · {seconds:.1f} 秒 · {cost:.5f} 元\n"
            "★ 这是**参考**, 不是结论: 你可以照用、改写或否掉。你要否掉它, 就说清理由。\n\n"
        )
    return head + content.strip()


def log_trigger(row: dict[str, Any], trigger: dict[str, Any] | None = None) -> Path:
    """把每次真摇的来龙去脉记一行(看"误触发多不多"用). 一行一条, 追加."""
    config = trigger if trigger is not None else load_trigger()
    rel = str(budget.as_dict(config.get("落盘")).get("触发日志") or "logs/outsource/触发.jsonl")
    target = HERE / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return target


def run(
    question: str,
    prepared: dict[str, Any],
    elapsed: float,
    force: bool = False,
    say: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """真调用外援: 一级外援 → 不行则升二级 mtp. 返回 {摇了, 级别, 家, 材料, 落盘, 金额, 因为}.

    ★ 材料为空 = 未接通, 调用方**维持原样**(该说没有就说没有), 不许拿其他内容顶替。
    """
    def note(text: str) -> None:
        if say is not None:
            say(text)

    verdict = decide(question, prepared, elapsed)
    if not verdict["摇"] and not force:
        return {"摇了": False, "级别": "", "家": "", "材料": "", "落盘": "", "金额": 0.0, "因为": verdict["因为"]}

    task = ask.build_task(question, str(prepared.get("声明") or prepared.get("wanted") or ""))
    try:
        money = budget.read_config()
    except FileNotFoundError as exc:
        return {"摇了": False, "级别": "", "家": "", "材料": "", "落盘": "", "金额": 0.0, "因为": f"外援配置不在: {exc}"}

    allowed, why = budget.budget_check(money, force=force)
    if not allowed:
        return {"摇了": False, "级别": "", "家": "", "材料": "", "落盘": "", "金额": 0.0, "因为": f"钱袋子: {why}"}

    house_name, house = budget.house_of(money, None)
    note(f"外援 {house_name}/{house.get('模型', '?')} · {why}")
    result = ask.call_house(house_name, house, money, task)
    usage = budget.as_dict(result.get("用量"))
    cost = budget.cost_of(house, usage)
    content = str(result.get("内容") or "")
    good = bool(result.get("成功")) and len(content.strip()) >= SHORT_REPLY and not exec_agent.looks_degenerate(content)
    budget.append_ledger({
        "时间": budget.now_stamp(), "来自": "hook", "家": house_name, "模型": result.get("模型", ""),
        "成功": good, "耗时秒": result.get("耗时秒", 0.0), "用量": usage, "金额": cost,
        "任务摘要": task[:80],
    }, budget.ledger_path_of(money))

    if good:
        path = ask.save_output(money, house_name, result, task, cost)
        material = build_material("outsource", house_name, str(result.get("模型", "")),
                                  float(result.get("耗时秒") or 0), cost, content)
        log_trigger({"时间": budget.now_stamp(), "结果": "一级外援接上", "因为": verdict["因为"],
                     "家": house_name, "金额": cost, "秒": elapsed, "题": task[:80]})
        return {"摇了": True, "级别": "outsource", "家": house_name, "材料": material,
                "落盘": str(path), "金额": cost, "因为": verdict["因为"]}

    note(f"外援没接上({result.get('错误', '') or '答得太短/像复读'}) → 升到交叉验证")
    try:
        two = panel.run_panel(task, force=force, quiet=True)
    except (FileNotFoundError, ValueError) as exc:
        two = {"可以": False, "为什么": f"交叉验证起不来: {exc}", "材料": "", "答上": 0, "金额": 0.0}
    if bool(two.get("可以")) and int(two.get("答上") or 0) >= 2 and str(two.get("材料") or ""):
        material = build_material("mtp", " · ".join([house_name, "多家"]), "—",
                                  0.0, float(two.get("金额") or 0), str(two["材料"]))
        log_trigger({"时间": budget.now_stamp(), "结果": "二级交叉验证接上", "因为": verdict["因为"],
                     "家": "多家", "金额": two.get("金额", 0), "秒": elapsed, "题": task[:80]})
        return {"摇了": True, "级别": "mtp", "家": "多家", "材料": material,
                "落盘": str(two.get("落盘", "")), "金额": float(two.get("金额") or 0), "因为": verdict["因为"]}

    log_trigger({"时间": budget.now_stamp(), "结果": "两级都没接上", "因为": verdict["因为"],
                 "家": house_name, "金额": cost, "秒": elapsed, "题": task[:80]})
    return {"摇了": True, "级别": "无", "家": house_name, "材料": "", "落盘": "",
            "金额": cost, "因为": "外援和交叉验证都没接上(维持原样, 该说没有就说没有)"}


def main() -> int:
    """手动试触发判据(不花钱): 看某个问题会不会摇、为什么."""
    import argparse

    parser = argparse.ArgumentParser(description="外援自动触发: 只看判据(不花钱)")
    parser.add_argument("问题")
    parser.add_argument("--声明", default="")
    parser.add_argument("--秒", type=float, default=0.0, help="假装这轮已经花了这么多秒")
    parser.add_argument("--左链没找到", action="store_true")
    args = parser.parse_args()

    prepared: dict[str, Any] = {"声明": args.声明, "wanted": "", "左链检索不到": args.左链没找到}
    verdict = decide(args.问题, prepared, args.秒)
    print(f"摇不摇: {'摇' if verdict['摇'] else '不摇'}")
    print(f"因为:   {verdict['因为']}")
    if verdict["摇"]:
        print(f"级别:   {verdict['级别']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

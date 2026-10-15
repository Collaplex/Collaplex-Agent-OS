#!/usr/bin/env python3
"""误触发对照: 拿一组本地完全能答的题过一遍, 数外援被无谓调起几次 (目标 0).

★ 这测的是**判据**, 不是外援的效果:
    前置链(子agent 分析/判断 -> 左链检索 skill)真跑, 拿真实的 prepared 喂给
    outsource_hook.decide(); 触发开关在内存里**强制打开**(测的就是"开关打开之后会不会乱摇")。
    不真摇 —— 真摇要花钱, 误触发用"判成摇了几次"来数。

三类题 (都该本地自己接住, 一次外援都不该摇):
    闲聊 / 格式转换   子agent 判"不需要 skill" -> 落到外援那一站
    机器操作          左链检索出 linux skill -> 根本走不到外援那一站

★ "本地完全能答"不许想当然: 落到外援站的题**真让本地模型答一遍**(拿同一份 prepared 的
   skill 当系统提示词, 跟线上同款), 程序判"非空 / 不复读 / 没在说'我没有工具'"。

跑法:
    .venv/bin/python skill/outsource/tests/misfire_probe.py            # 全跑
    .venv/bin/python skill/outsource/tests/misfire_probe.py --小样 3   # 先小样
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
PROJECT_ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(PROJECT_ROOT))

from budget import as_dict, read_env  # noqa: E402

import exec_agent  # noqa: E402
import main as main_mod  # noqa: E402
import outsource_hook  # noqa: E402
import sub_agent  # noqa: E402

# 一组"本地完全能答"的题 —— 分类只为了看清是哪条路接住的, 期望都是**一次都不摇**。
CASES: list[dict[str, str]] = [
    {"类": "闲聊", "题": "你好呀"},
    {"类": "闲聊", "题": "谢谢你刚才的解释"},
    {"类": "格式转换", "题": "把这句话翻译成英文：这台机器今天有点慢"},
    {"类": "格式转换", "题": "把下面三点整理成一句话：系统要快；界面要简单；数据不能丢"},
    {"类": "格式转换", "题": "把 '2026-10-07' 改写成中文写法"},
    {"类": "单跳问答", "题": "水的化学式是什么"},
    {"类": "单跳问答", "题": "一年有多少个月"},
    {"类": "机器操作", "题": "磁盘还剩多少空间"},
    {"类": "机器操作", "题": "8790 端口是哪个进程在听"},
    {"类": "机器操作", "题": "看下最近的日志里有没有报错"},
    # ★ 边界组: 词表最容易误伤的写法 —— 本地能答(都是知识/写作题), 但句子里带着触发词。
    {"类": "边界", "题": "解释一下 Python 里函数和方法有什么区别"},
    {"类": "边界", "题": "帮我写个请假条，说明我明天下午要去医院"},
    {"类": "边界", "题": "代码里的注释应该用中文还是英文"},
]

REFUSAL_MARKERS: list[str] = ["我没有这个能力", "我没有工具", "我没有执行", "我无法执行", "做不到", "没有工具"]


def answer_locally(question: str, prepared: dict[str, Any], timeout: float = 240.0) -> tuple[str, str]:
    """让本地模型真答一遍 (拿 prepared 里的 skill 当系统提示词, 思考档跟线上同款)。"""
    key = read_env("OPENAI_API_KEY", [".env"])
    base = read_env("OPENAI_BASE_URL", [".env"])
    model = read_env("OPENAI_MODEL", [".env"])
    if not key or not base or not model:
        return "", "本地模型没配好 (.env 的 OPENAI_*)"
    routing = sub_agent.load_routing()
    extra, _note = sub_agent.thinking_params(base, model, bool(prepared.get("think")), routing)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": str(prepared.get("skill") or "")},
            {"role": "user", "content": question},
        ],
        "temperature": 0.0,
        "max_tokens": 1200,
        "stream": False,
    }
    if extra:
        payload.update(extra)
    request = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            body = as_dict(json.loads(response.read().decode("utf-8")))
    except Exception as exc:  # 模型侧什么都可能 —— 记下来, 别把探针带崩
        return "", f"{type(exc).__name__}: {exc}"
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return "", "没有 choices"
    message = as_dict(as_dict(choices[0]).get("message"))
    return str(message.get("content") or ""), ""


def judge_local(reply: str, error: str) -> tuple[bool, str]:
    """程序判"本地答上来了没有": 非空 / 够长 / 不复读 / 没在说'我没有工具'。"""
    if error:
        return False, error
    text = reply.strip()
    if not text:
        return False, "空答"
    if exec_agent.looks_degenerate(text):
        return False, "复读"
    for marker in REFUSAL_MARKERS:
        if marker in text:
            return False, f"在推脱({marker})"
    if len(text) < 6:
        return False, "太短"
    return True, f"答上({len(text)} 字)"


def save_audit(row: dict[str, Any]) -> Path:
    folder = PROJECT_ROOT / "logs" / "outsource"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "误触发-明细.jsonl"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="外援误触发对照 (不花钱)")
    parser.add_argument("--小样", type=int, default=0, help="只跑前 N 道")
    parser.add_argument("--不验本地", action="store_true", help="跳过'本地真答一遍'这一步(快, 但不证明本地能答)")
    args = parser.parse_args()

    cases = CASES[: args.小样] if args.小样 else CASES
    trigger = dict(outsource_hook.load_trigger())
    if not bool(trigger.get("开关")):
        print("★ 触发开关本来是关的 —— 探针在内存里强制打开(测的就是打开后会不会乱摇); 文件没动")

    print("=" * 78)
    print(f"外援误触发对照 · {len(cases)} 道本地能答的题 · 触发开关(内存强制)=开 · 判定={len(REFUSAL_MARKERS)} 条推脱词")
    print("=" * 78)

    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, 1):
        question = case["题"]
        print(f"\n[{index}/{len(cases)}] {case['类']} · {question}")
        started = time.perf_counter()
        try:
            prepared = sub_agent.prepare_skill(question)
        except Exception as exc:
            print(f"  前置链失败: {type(exc).__name__}: {exc}")
            rows.append({"类": case["类"], "题": question, "落点": "前置链失败", "摇": False,
                         "因为": f"{type(exc).__name__}", "本地判": False, "本地说明": "没跑到",
                         "秒": round(time.perf_counter() - started, 1)})
            continue
        term = main_mod.retrieval_term(prepared, question)
        picked = main_mod.find_skill_for(question, term) if term else None
        reaches_hook = not (bool(term) and picked is not None)
        elapsed = round(time.perf_counter() - started, 1)

        if not reaches_hook:
            where = "左链接住(走不到外援站)"
            print(f"  落点: {where} · 派给 {picked['name'] if picked else '?'} · {elapsed}s")
            rows.append({"类": case["类"], "题": question, "落点": where, "摇": False, "因为": "(不到那一站)",
                         "本地判": None, "本地说明": "由左链的 skill 接", "秒": elapsed})
            save_audit(dict(rows[-1]))
            continue

        prepared["左链检索不到"] = bool(term)
        open_trigger = {**trigger, "开关": True}
        verdict = outsource_hook.decide(question, prepared, elapsed, open_trigger)
        fired = bool(verdict["摇"])
        where = "外援站(子agent 判不需要 skill)" if not term else "外援站(左链检索不到)"

        local_ok: bool | None = None
        local_note = "没验"
        local_reply = ""
        if not args.不验本地:
            reply, err = answer_locally(question, prepared)
            local_ok, local_note = judge_local(reply, err)
            local_reply = reply
        print(f"  落点: {where} · {elapsed}s")
        print(f"  判据: {'★摇' if fired else '不摇'} —— {verdict['因为']}")
        if local_ok is not None:
            print(f"  本地: {'✓' if local_ok else '✗'} {local_note}")

        row = {"类": case["类"], "题": question, "落点": where, "摇": fired, "因为": verdict["因为"],
               "本地判": local_ok, "本地说明": local_note, "本地回答": local_reply, "秒": elapsed}
        rows.append(row)
        save_audit(row)

    reached = [row for row in rows if str(row["落点"]).startswith("外援站")]
    fired = [row for row in reached if row["摇"]]
    left_chain = [row for row in rows if str(row["落点"]).startswith("左链")]
    answered = [row for row in reached if row["本地判"] is True]

    print("\n" + "=" * 78)
    print(f"{'类':<8}{'题':<34}{'落点':<10}{'摇':<6}{'本地':<6}{'秒':<6}")
    print("-" * 78)
    for row in rows:
        where = "左链" if str(row["落点"]).startswith("左链") else "外援站"
        mark = "★摇" if row["摇"] else "不摇"
        if row["本地判"] is None:
            local = "—"
        else:
            local = "✓" if row["本地判"] else "✗"
        print(f"{row['类']:<8}{str(row['题'])[:32]:<34}{where:<10}{mark:<6}{local:<6}{row['秒']:<6}")
    print("-" * 78)
    print(f"共 {len(rows)} 题 · 落到外援站 {len(reached)} 题 · 左链接住 {len(left_chain)} 题")
    print(f"★ 误触发 {len(fired)}/{len(reached)} (目标 0)")
    for row in fired:
        print(f"    ★摇的是: {row['题']} —— {row['因为']}")
    if not args.不验本地:
        print(f"本地自答: {len(answered)}/{len(reached)} 答上 (证明这些题本地接得住)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""效果对照: 同一批硬题, 本地小模型 vs 外援(默认 DeepSeek), 程序判分.

题集 = 3 道写代码(把产出的函数抠出来真跑测试用例)
     + 3 道长推理(只比最后那个数字)

两边的设置:
    本地: 走项目 .env 的 OPENAI_* (本地 qwen3-vl-8b), **开思考** —— 这类题本来就该开
          (判定用 sub_agent 的思考路由, 跟线上同款)
    外援: 走 skill/outsource 的真调用路径 (call_house), 记账一次一笔

判分全在程序里, 不问模型"你觉得你答得好不好".
跑法: .venv/bin/python skill/outsource/tests/effect_probe.py [--小样 N]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
PROJECT_ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(PROJECT_ROOT))

from budget import as_dict, append_ledger, cost_of, house_of, ledger_path_of, now_stamp, read_config, read_env  # noqa: E402
from ask import call_house  # noqa: E402

import sub_agent  # noqa: E402  (借它的思考路由方言表, 跟线上同款)

TASKS: list[dict[str, Any]] = [
    {
        "类": "代码",
        "名": "千分位转整数",
        "题": "写一个 Python 函数 `solve(s)`, 把 '1,234,567' 或 '-12,345' 这样的千分位字符串转成整数。"
              "只输出函数本体, 用 ```python 包起来, 不要额外解释。",
        "用例": [("1,234,567", 1234567), ("-12,345", -12345), ("42", 42)],
    },
    {
        "类": "代码",
        "名": "三数之和为 0",
        "题": "写一个 Python 函数 `solve(nums)`, 返回列表里所有和为 0 的三元组"
              "(每个三元组内部升序, 整体去重并按字典序排序)。"
              "只输出函数本体, 用 ```python 包起来, 不要额外解释。",
        "用例": [([-1, 0, 1, 2, -1, -4], [[-1, -1, 2], [-1, 0, 1]]), ([], []), ([0, 0, 0], [[0, 0, 0]])],
    },
    {
        "类": "代码",
        "名": "骰子表达式期望",
        "题": "写一个 Python 函数 `solve(expr)`, 解析形如 '3d6+2' 或 '2d4' 的骰子表达式, 返回期望值(浮点)。"
              "只输出函数本体, 用 ```python 包起来, 不要额外解释。",
        "用例": [("3d6+2", 12.5), ("2d4", 5.0), ("1d20", 10.5)],
    },
    {
        "类": "推理",
        "名": "三管齐开注水",
        "题": "一个水池, 甲管单独注满要 6 小时, 乙管单独注满要 4 小时, 丙管放空满池要 12 小时。"
              "三管齐开要几小时注满? 最后一行只写答案数字。",
        "答案": 3.0,
    },
    {
        "类": "推理",
        "名": "两车相向而行",
        "题": "甲乙两地相距 360 公里。A 车从甲地出发, 速度 60 公里/小时; 1 小时后 B 车从乙地出发, "
              "速度 40 公里/小时, 相向而行。相遇时 A 车共行驶了多少公里? 最后一行只写答案数字。",
        "答案": 240.0,
    },
    {
        "类": "推理",
        "名": "加盐提浓度",
        "题": "有含盐 10% 的盐水 200 克, 要变成含盐 20% 的盐水, 需要加多少克盐? 最后一行只写答案数字。",
        "答案": 25.0,  # 正解 25: 加盐后总质量也涨 x -> (20+x)/(200+x)=0.2。
                      # ★ 曾误写成 30 (把分母当不变): 实测两个模型都答 25, 是我错它们对
    },
]


def code_block(reply: str) -> str:
    """把回答里的代码抠出来: 优先 ```python 块, 退一步 ``` 块, 再退就整段当代码."""
    for pattern in (r"```(?:python|py)\s*\n(.*?)```", r"```\s*\n(.*?)```"):
        found = re.search(pattern, reply, re.DOTALL)
        if found:
            return found.group(1)
    return reply


def run_cases(code: str, cases: list[tuple[Any, Any]], timeout: float = 20.0) -> tuple[bool, str]:
    """真跑测试用例. 代码在子进程里跑 (崩了/死循环都不影响这边)."""
    lines = [code, "", "def _t():", "    out = []"]
    for arg, want in cases:
        lines.append(f"    out.append((solve({arg!r}) == {want!r}, solve({arg!r}), {want!r}))")
    lines += ["    return out", "", "for ok, got, want in _t():", "    print('OK' if ok else f'BAD {got!r} != {want!r}')"]
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fp:
        fp.write("\n".join(lines))
        path = fp.name
    try:
        done = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "跑超时"
    if done.returncode != 0:
        tail = (done.stderr or "").strip().splitlines()[-1:] or ["(无 stderr)"]
        return False, f"跑挂了: {tail[0][:60]}"
    verdict = (done.stdout or "").strip().splitlines()
    if verdict and all(line.strip() == "OK" for line in verdict):
        return True, f"{len(verdict)} 个用例全过"
    bad = [line for line in verdict if line.strip() != "OK"]
    return False, (bad[0][:60] if bad else "没有用例输出")


def last_number(reply: str) -> float | None:
    """抠回答里最后一个数字 (先看最后一行, 再退整段)."""
    rows = [row for row in reply.strip().splitlines() if row.strip()]
    for chunk in ([rows[-1]] if rows else []) + [reply]:
        nums = re.findall(r"-?\d+(?:\.\d+)?", chunk.replace(",", ""))
        if nums:
            try:
                return float(nums[-1])
            except ValueError:
                continue
    return None


def ask_local(prompt: str, think: bool = True, timeout: float = 240.0) -> tuple[str, str]:
    """问本地模型 (项目 .env 的 OPENAI_*).

    think=True  = 开思考 —— 这类题本来就该开 (判定用项目自己的思考路由方言表, 跟线上同款)
    think=False = 关思考 —— 同一批题的对照档, 看它是更快还是更慢、更准还是更差
    """
    key = read_env("OPENAI_API_KEY", [".env"])
    base = read_env("OPENAI_BASE_URL", [".env"])
    model = read_env("OPENAI_MODEL", [".env"])
    if not key or not base or not model:
        return "", "本地模型没配好 (.env 的 OPENAI_*)"
    routing = sub_agent.load_routing()
    extra, _why = sub_agent.thinking_params(base, model, think, routing)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 3000,
        "stream": False,
    }
    if extra:
        payload.update(extra)
    import urllib.request

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
    except Exception as exc:
        return "", f"{type(exc).__name__}: {exc}"
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return "", "没有 choices"
    message = as_dict(as_dict(choices[0]).get("message"))
    return str(message.get("content") or ""), ""


def save_audit(row: dict[str, Any], suffix: str = "") -> Path:
    """把一道题的双方原始回答落盘 (审计用).

    ★ 没有这个: 判分表写错时无从翻案 (第一版就把加盐题的正解写错了,
    靠模型答的 25 反查才发现)。一行一道题, 追加。
    suffix 用来把"关思考"那档单独落一个文件, 别跟开思考的混在一起。
    """
    folder = PROJECT_ROOT / "logs" / "outsource"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"效果-明细{suffix}.jsonl"
    with target.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False) + "\n")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="外援效果对照")
    parser.add_argument("--小样", type=int, default=0, help="只跑前 N 道")
    parser.add_argument("--只", type=int, default=0, help="只跑第 N 道 (从 1 数), 用来单题重跑")
    parser.add_argument("--家", default="", help="外援用哪家, 默认按配置")
    parser.add_argument("--思考", choices=["开", "关"], default="开", help="本地方开不开思考 (默认开)")
    args = parser.parse_args()
    think = args.思考 == "开"

    config = read_config()
    house_name, house = house_of(config, args.家 or None)
    tasks = TASKS[: args.小样] if args.小样 else TASKS
    if args.只:
        tasks = TASKS[args.只 - 1: args.只]
        if not tasks:
            print(f"没有第 {args.只} 道 (一共 {len(TASKS)} 道)")
            return 1

    print("=" * 72)
    print(f"外援效果对照 · 外援={house_name}/{house.get('模型')} · 本地=qwen3-vl-8b({args.思考}思考) · {len(tasks)} 道题")
    print("=" * 72)

    rows: list[dict[str, Any]] = []
    for index, task in enumerate(tasks, 1):
        print(f"\n[{index}/{len(tasks)}] {task['类']} · {task['名']}")
        kinds = "代码" if task["类"] == "代码" else "推理"

        started = time.time()
        local_reply, local_err = ask_local(str(task["题"]), think=think)
        local_sec = round(time.time() - started, 1)
        if local_err:
            local_ok, local_note = False, local_err
        elif kinds == "代码":
            local_ok, local_note = run_cases(code_block(local_reply), task["用例"])
        else:
            got = last_number(local_reply)
            local_ok = got == task["答案"]
            local_note = f"答 {got}" if got is not None else "没抠出数字"
        print(f"  本地 : {'✓' if local_ok else '✗'} {local_note} ({local_sec}s)")

        started = time.time()
        result = call_house(house_name, house, config, str(task["题"]))
        out_sec = round(time.time() - started, 1)
        usage = as_dict(result.get("用量"))
        cost = cost_of(house, usage)
        if not result.get("成功"):
            out_ok, out_note = False, str(result.get("错误", "?"))
        elif kinds == "代码":
            out_ok, out_note = run_cases(code_block(str(result.get("内容", ""))), task["用例"])
        else:
            got = last_number(str(result.get("内容", "")))
            out_ok = got == task["答案"]
            out_note = f"答 {got}" if got is not None else "没抠出数字"
        print(f"  外援 : {'✓' if out_ok else '✗'} {out_note} ({out_sec}s · {cost:.5f} 元 · "
              f"{usage.get('total_tokens', '?')} tok)")

        # ★ 探针花的钱也记账 —— 项目红线是"每次调用记账, 跑完能直接看出今天花了多少";
        #   不记的话探针就是账本上的黑洞 (实测: 关思考那一轮 0.00609 元没进流水)。
        append_ledger({
            "时间": now_stamp(), "来自": "probe", "家": house_name, "模型": result.get("模型", ""),
            "成功": bool(result.get("成功")), "耗时秒": out_sec, "用量": usage, "金额": cost,
            "任务摘要": f"[效果对照·本地{'开' if think else '关'}思考] {task['名']}",
        }, ledger_path_of(config))

        rows.append({"类": task["类"], "名": task["名"], "本地": local_ok, "外援": out_ok,
                     "本地秒": local_sec, "外援秒": out_sec, "金额": cost, "tok": usage.get("total_tokens", 0)})
        save_audit({
            "时间": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "题": task["名"], "类": task["类"], "本地思考": args.思考,
            "本地判": local_ok, "本地说明": local_note, "本地秒": local_sec, "本地回答": local_reply,
            "外援判": out_ok, "外援说明": out_note, "外援秒": out_sec, "外援回答": str(result.get("内容", "")),
            "金额": cost, "tok": usage.get("total_tokens", 0),
        }, "-关思考" if not think else "")

    print("\n" + "=" * 72)
    print(f"{'类':<6}{'题':<16}{'本地':<6}{'外援':<6}{'本地耗时':<10}{'外援耗时':<10}{'花了':<10}")
    print("-" * 72)
    for row in rows:
        print(f"{row['类']:<6}{row['名']:<16}{'✓' if row['本地'] else '✗':<6}{'✓' if row['外援'] else '✗':<6}"
              f"{row['本地秒']:<10}{row['外援秒']:<10}{row['金额']:.5f}")
    local_hit = sum(1 for row in rows if row["本地"])
    out_hit = sum(1 for row in rows if row["外援"])
    total_cost = sum(float(row["金额"]) for row in rows)
    total_tok = sum(int(row["tok"]) for row in rows)
    print("-" * 72)
    print(f"本地 {local_hit}/{len(rows)} · 外援 {out_hit}/{len(rows)} · 外援总花费 {total_cost:.5f} 元 / {total_tok} tok")
    code_rows = [row for row in rows if row["类"] == "代码"]
    think_rows = [row for row in rows if row["类"] == "推理"]
    if code_rows:
        print(f"  写代码: 本地 {sum(1 for r in code_rows if r['本地'])}/{len(code_rows)} · "
              f"外援 {sum(1 for r in code_rows if r['外援'])}/{len(code_rows)}")
    if think_rows:
        print(f"  长推理: 本地 {sum(1 for r in think_rows if r['本地'])}/{len(think_rows)} · "
              f"外援 {sum(1 for r in think_rows if r['外援'])}/{len(think_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

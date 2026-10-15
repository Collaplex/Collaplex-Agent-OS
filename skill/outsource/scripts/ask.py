#!/usr/bin/env python3
"""外援: 把一件明确的活交给云端强模型, 拿回能直接用的产出.

用法:
    .venv/bin/python skill/outsource/main.py ask "任务" [--声明 "..."] [--家 deepseek|mimo] [--强制] [--安静]

约定:
    --声明 是子 agent 判出的「手头缺什么能力」原话, 由程序拼进任务, 不让模型转述 (转述会丢信息还会多花钱).
    产出原文 + 用量 + 估算金额都落盘到 logs/outsource/, 原文原样打到 stdout (不截断).
    任何一步失败都明确标失败 —— 拿不到内容绝不静默当成功, 退出码 1.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent          # scripts
sys.path.insert(0, str(HERE))                    # 让 budget 能被 import (单独跑这个文件也行)

from budget import (  # noqa: E402
    as_dict,
    as_list,
    append_ledger,
    budget_check,
    call_config_of,
    cost_of,
    env_sources_of,
    house_of,
    ledger_path_of,
    now_stamp,
    output_dir_of,
    over_single_limit,
    read_config,
    read_env,
    system_prompt_of,
)


def build_task(task: str, declaration: str) -> str:
    """把用户原话和子 agent 的缺能力声明拼成任务. 程序拼, 不经过模型."""
    parts = [task.strip()]
    if declaration.strip():
        parts.append(f"[子 agent 的判定] 手头缺这个能力: {declaration.strip()}")
    return "\n\n".join(parts)


def call_house(house_name: str, house: dict[str, Any], config: dict[str, Any], task_text: str) -> dict[str, Any]:
    """真发一次请求. 返回 {成功, 内容, 用量, 耗时秒, 模型, 错误}."""
    prefix = str(house.get("env前缀", ""))
    sources = env_sources_of(house)
    api_key = read_env(f"{prefix}_API_KEY", sources)
    base_url = read_env(f"{prefix}_BASE_URL", sources)
    model = read_env(f"{prefix}_MODEL", sources) or str(house.get("模型", ""))

    blank: dict[str, Any] = {"成功": False, "内容": "", "用量": {}, "耗时秒": 0.0, "模型": model, "错误": ""}
    if not api_key:
        return blank | {"错误": f"找不到凭据 {prefix}_API_KEY"}
    if not base_url:
        return blank | {"错误": f"找不到端点 {prefix}_BASE_URL"}
    if not model:
        return blank | {"错误": f"{house_name} 没定模型 (env 里没写, 配置里也没有)"}

    max_tokens, temperature, timeout = call_config_of(config)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt_of(config)},
            {"role": "user", "content": task_text},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    # 思考开关: 配置说 false 才关 (没说 / true 就不发, 让它按自己的默认走)
    if house.get("思考") is False:
        payload["thinking"] = {"type": "disabled"}

    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    # 绕开本机代理: 打的是公网 API, 不要让 127.0.0.1:7897 插手
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.time()
    try:
        with opener.open(request, timeout=timeout) as response:
            raw: Any = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            detail = "(读不到错误正文)"
        return blank | {"耗时秒": round(time.time() - started, 1), "错误": f"HTTP {exc.code}: {detail}"}
    except Exception as exc:
        return blank | {"耗时秒": round(time.time() - started, 1), "错误": f"{type(exc).__name__}: {exc}"}

    elapsed = round(time.time() - started, 1)
    body = as_dict(raw)
    choices = as_list(body.get("choices"))
    content = ""
    if choices:
        message = as_dict(as_dict(choices[0]).get("message"))
        content = str(message.get("content") or "")
    usage = as_dict(body.get("usage"))
    if not content.strip():
        return {
            "成功": False,
            "内容": "",
            "用量": usage,
            "耗时秒": elapsed,
            "模型": model,
            "错误": f"回来了但是空的 (completion_tokens={usage.get('completion_tokens', '?')}, 多半被 token 上限吃光)",
        }
    return {"成功": True, "内容": content, "用量": usage, "耗时秒": elapsed, "模型": model, "错误": ""}


def save_output(config: dict[str, Any], house_name: str, result: dict[str, Any], task_text: str, cost: float) -> Path:
    """把产出原文连头部信息一起落盘, 返回文件路径."""
    folder = output_dir_of(config)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = now_stamp().replace(":", "").replace("-", "")
    target = folder / f"{stamp}-{house_name}.md"
    usage = as_dict(result.get("用量"))
    header = [
        "# 外援产出",
        "",
        f"- 家: {house_name} / 模型: {result.get('模型', '?')}",
        f"- 耗时: {result.get('耗时秒', '?')} 秒",
        f"- 用量: {json.dumps(usage, ensure_ascii=False)}",
        f"- 估算金额: {cost:.4f} 元",
        "",
        "## 任务(程序拼的原文)",
        "",
        task_text,
        "",
        "## 产出",
        "",
    ]
    target.write_text("\n".join(header) + str(result.get("内容", "")) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="外援: 摇云端强模型干活")
    parser.add_argument("任务", help="要它干的活 (写清要求)")
    parser.add_argument("--声明", default="", help="子 agent 判出的「缺什么能力」原话")
    parser.add_argument("--家", default="", help="deepseek / mimo, 默认按配置")
    parser.add_argument("--强制", action="store_true", help="跳开关 (不跳预算)")
    parser.add_argument("--安静", action="store_true", help="不把产出原文打到 stdout (产出仍落盘)")
    args = parser.parse_args()

    try:
        config = read_config()
        house_name, house = house_of(config, args.家 or None)
    except (FileNotFoundError, ValueError) as exc:
        print(f"外援失败: {exc}")
        return 1

    allowed, why = budget_check(config, force=args.强制)
    if not allowed:
        print(f"这次不调外援: {why}")
        return 2

    task_text = build_task(args.任务, args.声明)
    print(f"外援: {house_name} / {house.get('模型', '?')} · {why}")
    result = call_house(house_name, house, config, task_text)

    usage = as_dict(result.get("用量"))
    cost = cost_of(house, usage)
    row: dict[str, Any] = {
        "时间": now_stamp(),
        "来自": "outsource",
        "家": house_name,
        "模型": result.get("模型", ""),
        "成功": result.get("成功", False),
        "耗时秒": result.get("耗时秒", 0.0),
        "用量": usage,
        "金额": cost,
        "任务摘要": args.任务.strip()[:80],
    }
    append_ledger(row, ledger_path_of(config))

    if not result.get("成功"):
        print(f"外援失败({house_name}): {result.get('错误', '?')}")
        print(f"记账已写: {ledger_path_of(config)}")
        return 1

    path = save_output(config, house_name, result, task_text, cost)
    note = over_single_limit(config, cost)
    print(f"外援回来了: {result.get('耗时秒', '?')} 秒 · 用量 {json.dumps(usage, ensure_ascii=False)} · 估算 {cost:.4f} 元")
    if note:
        print(f"提醒: {note}")
    print(f"产出落盘: {path}")
    if not args.安静:
        print("-" * 60)
        print(result.get("内容", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

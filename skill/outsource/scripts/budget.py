#!/usr/bin/env python3
"""外援的开关与预算判定: 纯逻辑, 不联网, 不发请求.

做四件事:
    read_config()     读 resources/outsource.json
    read_env()        按键名取凭据 (先进程环境, 再按配置给的文件顺序找)
    budget_check()    看开关 / 今天花了多少 / 今天调了几次 -> 这次能不能调
    append_ledger()   一次调用往流水追加一行

累计金额从流水现算, 不另存计数器 (计数器迟早和流水对不上).
记账一行 = 一次调用: 时间 / 家 / 模型 / 用量 / 金额 / 任务摘要.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent          # skill/outsource/scripts
SKILL_DIR = HERE.parent                        # skill/outsource
PROJECT_ROOT = SKILL_DIR.parent.parent         # 项目根
CONFIG_PATH = SKILL_DIR / "resources" / "outsource.json"
LEDGER_PATH = PROJECT_ROOT / "logs" / "outsource" / "用量.jsonl"


def as_dict(value: Any) -> dict[str, Any]:
    """把配置里/响应里取出来的一段当字典用. 不是字典就给空字典, 让上层判空."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    """同上, 当列表用."""
    return cast(list[Any], value) if isinstance(value, list) else []


def read_config(path: Path | None = None) -> dict[str, Any]:
    """读外置配置. 文件不在就抛错, 不用内置默认值兜 (兜了等于把配置藏进代码)."""
    target = path if path is not None else CONFIG_PATH
    if not target.is_file():
        raise FileNotFoundError(f"找不到外援配置: {target}")
    with target.open(encoding="utf-8") as fp:
        data: Any = json.load(fp)
    if not isinstance(data, dict):
        raise ValueError(f"外援配置根节点必须是对象: {target}")
    return cast(dict[str, Any], data)


def house_of(config: dict[str, Any], name: str | None = None) -> tuple[str, dict[str, Any]]:
    """挑一家外援: 指定了用指定的, 没指定用配置里的默认家. 名字不在表里就报错."""
    houses = as_dict(config.get("家"))
    if not houses:
        raise ValueError("外援配置里没有 家")
    picked = name if name else str(config.get("默认家", ""))
    if not picked:
        raise ValueError("外援配置里没写 默认家, 也没指定 --家")
    if picked not in houses:
        raise ValueError(f"外援配置里没这家: {picked} (有: {', '.join(sorted(houses))})")
    return picked, as_dict(houses.get(picked))


def ledger_path_of(config: dict[str, Any]) -> Path:
    """记账文件路径 (配置里写相对项目根)."""
    rel = str(as_dict(config.get("落盘")).get("记账文件") or "logs/outsource/用量.jsonl")
    return PROJECT_ROOT / rel


def output_dir_of(config: dict[str, Any]) -> Path:
    """产出目录 (配置里写相对项目根)."""
    rel = str(as_dict(config.get("落盘")).get("产出目录") or "logs/outsource")
    return PROJECT_ROOT / rel


def read_env(name: str, sources: list[str]) -> str:
    """按键名取一个值: 先看进程环境, 再按给的文件顺序找. 找不到返回空串.

    只返回值本身, 调用方负责不把它打印出来.
    """
    from_process = os.environ.get(name, "").strip()
    if from_process:
        return from_process
    for src in sources:
        path = Path(src).expanduser() if src.startswith("~") else PROJECT_ROOT / src
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                raw = line.split("=", 1)[1].strip()
                return raw.strip('"').strip("'")
    return ""


def env_sources_of(house: dict[str, Any]) -> list[str]:
    """一家外援的凭据该去哪几个文件里找."""
    raw: Any = house.get("env来源", [".env"])
    found = [str(item) for item in as_list(raw)]
    return found if found else [".env"]


def today_lines(ledger: Path | None = None) -> list[dict[str, Any]]:
    """读今天的流水行. 坏行跳过 —— 记账出错不应连带外援一起失效."""
    target = ledger if ledger is not None else LEDGER_PATH
    if not target.is_file():
        return []
    stamp = date.today().isoformat()
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row: Any = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and str(as_dict(row).get("时间", "")).startswith(stamp):
            rows.append(as_dict(row))
    return rows


def today_totals(ledger: Path | None = None) -> tuple[float, int]:
    """今天花掉多少元 / 调了几次."""
    rows = today_lines(ledger)
    spent = 0.0
    for row in rows:
        amount: Any = row.get("金额", 0.0)
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            spent += float(amount)
    return round(spent, 4), len(rows)


def budget_check(config: dict[str, Any], ledger: Path | None = None, force: bool = False) -> tuple[bool, str]:
    """这次能不能调外援.

    force 只跳开关, 不跳预算: 开关是意愿, 预算是钱包.
    """
    budget = as_dict(config.get("预算"))
    spent, count = today_totals(ledger)

    if not force and config.get("开关") is not True:
        return False, "外援开关关着 (在 skill/outsource/resources/outsource.json 里把 开关 改成 true)"

    day_limit = float(budget.get("每日上限_元", 2.0))
    if spent >= day_limit:
        return False, f"今天已花 {spent:.2f} 元, 到顶了 (每日上限 {day_limit:.2f} 元)"

    count_limit = int(budget.get("每日次数上限", 20))
    if count >= count_limit:
        return False, f"今天已经调了 {count} 次, 到顶了 (上限 {count_limit} 次)"

    return True, f"可以 (今天已花 {spent:.2f} 元 / {count} 次)"


def cost_of(house: dict[str, Any], usage: dict[str, Any]) -> float:
    """按价目和实际用量算这一笔花了多少元. 缺价目返回 0 (记账写 0, 不猜)."""
    price = as_dict(house.get("价目"))
    if not price:
        return 0.0
    prompt = int(usage.get("prompt_tokens", 0) or 0)
    cached = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
    out = int(usage.get("completion_tokens", 0) or 0)
    fresh = max(prompt - cached, 0)
    per = 1_000_000.0
    total = fresh * float(price.get("输入_每百万", 0.0)) / per
    total += cached * float(price.get("缓存命中_每百万", 0.0)) / per
    total += out * float(price.get("输出_每百万", 0.0)) / per
    return round(total, 6)


def over_single_limit(config: dict[str, Any], amount: float) -> str:
    """单次金额超上限就返回提示语, 没超返回空串."""
    limit = float(as_dict(config.get("预算")).get("单次上限_元", 0.3))
    if amount > limit:
        return f"单次花了 {amount:.2f} 元, 超过单次上限 {limit:.2f} 元"
    return ""


def system_prompt_of(config: dict[str, Any]) -> str:
    """外援的系统提示词 (从配置里读, 不写在代码里)."""
    return str(config.get("系统提示词", ""))


def call_config_of(config: dict[str, Any]) -> tuple[int, float, float]:
    """(max_tokens, 温度, 超时秒) 三个调用参数."""
    call_cfg = as_dict(config.get("调用"))
    return (
        int(call_cfg.get("max_tokens", 4096)),
        float(call_cfg.get("温度", 0.2)),
        float(call_cfg.get("超时_秒", 180)),
    )


def append_ledger(row: dict[str, Any], ledger: Path | None = None) -> Path:
    """往流水追加一行 (目录不在就建)."""
    target = ledger if ledger is not None else LEDGER_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False) + "\n")
    return target


def now_stamp() -> str:
    """记账用的时间戳."""
    return datetime.now().isoformat(timespec="seconds")

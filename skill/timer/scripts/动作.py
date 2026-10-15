#!/usr/bin/env python3
"""定时任务的动作层 —— 主 agent 面能跑的几条命令(解析 / 登记 / 撤 / 查 / 等 / 重挂 / 自检)。

约定:
- 人话输出是给模型照抄的; --json 是给框架读的(纯 JSON, 不多一个字).
- 退出码: 0 成了 / 1 条件不足(缺项在 缺·可选 里) / 2 用法错 / 3 没找着.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import 引擎 as 引擎

动作说明: dict[str, str] = {
    "register": "登记一条闹钟/倒计时(先过程序判据: 时间/提醒什么/阻塞还是非阻塞/是否 ≤ 上限)",
    "cancel": "撤掉一条(给 id 或 --最近)",
    "list": "看现在挂着几条",
    "take": "把到点的取出来(给框架注入主 agent 用; 拉式交付)",
    "wait": "阻塞式等到点(每秒往 stdout 吐一行 tick, 给框架转成读秒)",
    "arm": "进程起来时重挂一次(过期的标成待注入 + 有活就起线程)",
    "status": "表在哪 / 线程活没活 / 挂了几条",
    "selfcheck": "自检: 配置能读 / 表能读 / 时长解析对",
}


def 取参数(给: list[str], 名: str) -> str | None:
    """从参数表里取 --名 的值(没有就 None)."""
    if 名 in 给:
        位置 = 给.index(名)
        if 位置 + 1 < len(给):
            return 给[位置 + 1]
    return None


def 有开关(给: list[str], 名: str) -> bool:
    return 名 in 给


def 打(数据: dict[str, Any], 要json: bool, 人话: str) -> None:
    if 要json:
        print(json.dumps(数据, ensure_ascii=False))
    else:
        print(人话)


def 做register(给: list[str]) -> int:
    要json = 有开关(给, "--json")
    原话 = 给[0] if 给 and not 给[0].startswith("--") else ""
    提醒 = 取参数(给, "--提醒")
    结果 = 引擎.判据(
        原话,
        类型=取参数(给, "--类型"),
        时长=float(取参数(给, "--时长") or 0) or None,
        时刻=float(取参数(给, "--时刻") or 0) or None,
        阻塞=True if 有开关(给, "--阻塞") else (False if 有开关(给, "--非阻塞") else None),
        提醒=提醒,
    )
    if not 结果["可以"]:
        if 要json:
            打({"可以": False, "缺": 结果["缺"], "可选": 结果["可选"]}, True, "")
        else:
            print("[条件不足] 这条登记我没法落 —— 还缺:")
            for 一一 in 结果["缺"]:
                print(f"  · {一一}")
            print("能挑的:")
            for 一一 in 结果["可选"]:
                print(f"  · {一一}")
        return 1
    条, 说明 = 引擎.登记(结果["参数"], 谁声明=取参数(给, "--谁声明") or "主 agent")
    if 条 is None:
        打({"可以": True, "登记": False, "说明": 说明}, 要json, f"[登记不了] {说明}")
        return 1
    数据 = {"可以": True, "登记": True, "id": 条["id"], "类型": 条["类型"],
            "到点": 条["到点"], "阻塞": 条["阻塞"], "提醒": 条["提醒"],
            "人话": f"[id {条['id']}] {条['类型']} · {引擎.到点说法(条)}"}
    打(数据, 要json, 说明)
    return 0


def 做cancel(给: list[str]) -> int:
    要json = 有开关(给, "--json")
    编号 = 给[0] if 给 and not 给[0].startswith("--") else 取参数(给, "--id")
    条, 说明 = 引擎.撤销(编号, 最近=有开关(给, "--最近"))
    if 条 is None:
        打({"撤销": False, "说明": 说明}, 要json, f"[没撤成] {说明}")
        return 3
    打({"撤销": True, "id": 条.get("id"), "说明": 说明}, 要json, 说明)
    return 0


def 做list(给: list[str]) -> int:
    要json = 有开关(给, "--json")
    条目们 = 引擎.列出(只要挂着=not 有开关(给, "--全部"))
    if 要json:
        print(json.dumps({"条数": len(条目们), "条目": 条目们}, ensure_ascii=False))
        return 0
    if not 条目们:
        print("现在没挂着定时任务。")
        return 0
    print(f"挂着 {len(条目们)} 条:")
    for 条 in 条目们:
        print(f"  [id {条.get('id')}] {条.get('类型')} · {引擎.到点说法(条)} · "
              f"{'阻塞' if 条.get('阻塞') else '非阻塞'} · {条.get('状态')}")
        print(f"        到点要说: {条.get('提醒')}")
    return 0


def 做take(给: list[str]) -> int:
    """拉式交付: 每轮开场拿一次."""
    要json = 有开关(给, "--json")
    待 = 引擎.捡待注入()
    if 要json:
        print(json.dumps({"待注入": [{"id": 条["id"], "话": 引擎.提醒话(条),
                                    "补的": bool(条.get("补的"))} for 条 in 待]},
                         ensure_ascii=False))
        return 0
    for 条 in 待:
        print(引擎.提醒话(条))
    return 0


def 做wait(给: list[str]) -> int:
    """阻塞式等到点: 每秒一行 tick(JSON), 最后一行 done."""
    条目们 = 引擎.列出()
    编号 = 给[0] if 给 and not 给[0].startswith("--") else None
    条 = next((t for t in 条目们 if not 编号 or str(t.get("id")) == 编号), None)
    if 条 is None:
        print(json.dumps({"错": "没找着这条"}, ensure_ascii=False))
        return 3

    def 每秒(剩: float) -> None:
        print(json.dumps({"tick": round(剩, 1), "话": 引擎.剩余说法(剩)}, ensure_ascii=False),
              flush=True)

    if 引擎.等(条, 每秒):
        print(json.dumps({"done": True, "话": 引擎.提醒话(条)}, ensure_ascii=False), flush=True)
        return 0
    print(json.dumps({"done": False, "错": "这条被撤了或已经处理过了"}, ensure_ascii=False))
    return 3


def 做arm(给: list[str]) -> int:
    要json = 有开关(给, "--json")
    果 = 引擎.重挂()
    打(果, 要json, f"重挂完了: 表 {果['表']} · 挂着 {果['挂着']} 条 · "
                   f"补的 {果['刚响']} 条 · 线程 {'跑着' if 果['线程'] else '没起'}")
    return 0


def 做status(给: list[str]) -> int:
    要json = 有开关(给, "--json")
    果 = {"表": 引擎.表名(), "进程键": 引擎.进程键(), "线程": 引擎.线程活着(),
          "挂着": len(引擎.列出()), "上限分钟_阻塞": 引擎.配置()["上限分钟_阻塞"],
          "最多条数": 引擎.配置()["最多条数"], "加速": 引擎.加速()}
    打(果, 要json, "\n".join(f"  {k}: {v}" for k, v in 果.items()))
    return 0


def 做selfcheck(给: list[str]) -> int:
    好, 报 = 引擎.自检()
    if 有开关(给, "--json"):
        print(json.dumps({"通过": 好, "报告": 报}, ensure_ascii=False))
    else:
        print("定时任务自检: " + ("通过" if 好 else "不过"))
        for 一一 in 报:
            print(f"  {一一}")
    return 0 if 好 else 1


动作表: dict[str, Any] = {
    "register": 做register, "cancel": 做cancel, "list": 做list,
    "take": 做take, "wait": 做wait, "arm": 做arm,
    "status": 做status, "selfcheck": 做selfcheck,
}


def main() -> int:
    给 = sys.argv[1:]
    if not 给 or 给[0] in ("list-actions", "help", "-h", "--help"):
        print("定时任务可用动作:")
        for 名, 说明 in 动作说明.items():
            print(f"  {名:10} {说明}")
        return 0
    if 给[0] == "actions":
        for 名, 说明 in 动作说明.items():
            print(f"{名}\t{说明}")
        return 0
    名 = 给[0]
    做 = 动作表.get(名)
    if 做 is None:
        print(f"[错误] 没有这个动作: {名}")
        return 2
    return int(做(给[1:]))


if __name__ == "__main__":
    sys.exit(main())

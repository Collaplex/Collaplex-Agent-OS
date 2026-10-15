#!/usr/bin/env python3
"""框架接缝测试 —— 主 agent 那一侧(定时.py)怎么用 skill/timer.

跑法: .venv/bin/python tests/test_timer_seam.py

跟 skill/timer/tests/验定时.py 的分工: 那个验引擎, 这个验**接缝** ——
登记走真子进程(main.py register), 交付走 取待办() / 等阻塞(), 全在沙盒里。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

根 = Path(__file__).resolve().parent.parent
沙盒 = Path(tempfile.mkdtemp(prefix="timer-接缝-"))
沙盒前缀 = "接缝测试_"

os.environ["COLLAPLEX_DB_PREFIX"] = 沙盒前缀          # 冷库沙盒: 表名带前缀, 不碰生产表
os.environ["COLLAPLEX_TIMER_CONFIG"] = str(沙盒 / "timer.json")
os.environ["COLLAPLEX_TIMER_SPEED"] = "60"          # 假时钟 60 倍: 60 秒 = 1 秒

sys.path.insert(0, str(根))
import 定时                                              # noqa: E402 - 环境必须先设好

(沙盒 / "timer.json").write_text(json.dumps({
    "上限分钟_阻塞": 180, "最多条数": 20, "空闲退出秒": 1, "轮询秒": 0.05,
    "补的阈值秒": 60, "提醒前缀": "⏰ 你定的闹钟到了：",
    "补的提醒前缀": "⏰ 你定的闹钟到了（这条是补的，早就该响）：",
}, ensure_ascii=False), encoding="utf-8")

通过 = 0
不过 = 0


def 查(名: str, 条件: bool, 细节: str = "") -> None:
    global 通过, 不过
    if 条件:
        通过 += 1
        print(f"  ✓ {名}")
    else:
        不过 += 1
        print(f"  ✗ {名}" + (f" —— {细节}" if 细节 else ""))


def 播种(条目们: list[dict[str, object]]) -> None:
    """把条目直接写进冷库沙盒那一行（表在库里了，不再写文件）。"""
    码 = ("import json,sys; sys.path.insert(0,'.'); import 库; "
          "库.写文档('timers', '接缝', json.loads(sys.argv[1]))")
    subprocess.run([sys.executable, "-c", 码, json.dumps(条目们, ensure_ascii=False)],
                   cwd=str(根), capture_output=True, text=True, timeout=60, check=False)


def 清表() -> None:
    播种([])                                       # 冷库沙盒那一行清空


def 登记(原话: str) -> tuple[int, dict[str, object]]:
    """走真命令登记(跟框架递交给 exec agent 那条路一样)."""
    跑 = subprocess.run(
        [sys.executable, str(根 / "skill" / "timer" / "main.py"), "register", 原话, "--json"],
        cwd=根, capture_output=True, text=True, env=dict(os.environ))
    try:
        数据 = dict(json.loads(跑.stdout))
    except json.JSONDecodeError:
        数据 = {}
    return 跑.returncode, 数据


print(f"沙盒: {沙盒}")
定时.进程("接缝")
清表()

# ── 1. 起来重挂: 空表也是干净的 ────────────────────────────────
print("\n[1] 启动重挂")
果 = 定时.重挂()
查("空表重挂也稳", 果["挂着"] == 0 and 果["刚响"] == 0, json.dumps(果, ensure_ascii=False))
查("落冷库、按行键分(接缝)", 定时.表().endswith("timers") and 定时.行键() == "接缝",
   f"表={定时.表()} 行键={定时.行键()}")

# ── 2. 非阻塞: 登记 -> 还没到点 -> 到点交付 -> 幂等 ─────────────
print("\n[2] 非阻塞那条路(拉式交付)")
清表()
码, 数据 = 登记("120秒后提醒我喝水，先去忙别的")
查("子进程登记成功", 码 == 0 and bool(数据.get("id")), json.dumps(数据, ensure_ascii=False))
查("还没到点 -> 取待办是空的", 定时.取待办() is None)
time.sleep(2.2)                                       # 120 秒 / 60 倍 = 2 秒
话 = 定时.取待办()
查("到点了 -> 开场能拿到提醒", bool(话) and "喝水" in str(话), str(话))
查("固定前缀", bool(话) and str(话).startswith("⏰ 你定的闹钟到了："), str(话))
查("交付过就不再重复(幂等)", 定时.取待办() is None)

# ── 3. 阻塞式: 这一轮等 + 读秒, 到点由下一轮开场交回主 agent ────
print("\n[3] 阻塞式那条路(这一轮里等)")
清表()
轮 = 定时.开一轮()                                   # 记号: 这一轮登记的都带它
码, 数据 = 登记("60秒倒计时，就在这等着")
查("子进程登记成功", 码 == 0 and bool(数据.get("id")))
本轮 = 定时.本轮的阻塞条目(轮)
查("认出这是本轮的阻塞条目", len(本轮) == 1, f"认出 {len(本轮)} 条")
读秒: list[float] = []
到点话 = 定时.等阻塞(本轮[0], lambda 剩: 读秒.append(剩)) if 本轮 else None
查("等到点拿到提醒话", bool(到点话) and "时间到了" in str(到点话), str(到点话))
查("等的时候读秒了", len(读秒) >= 1, f"读了 {len(读秒)} 次")
查("到点之后走开场交付(下一轮就叫醒主 agent)", 定时.取待办() is not None)

# ── 4. 重挂补一次 ─────────────────────────────────────────────
print("\n[4] 跨重启重挂 + 补一次")
清表()
播种([{
    "id": "beef0001", "类型": "倒计时", "到点": 定时.现在() - 600, "提醒": "该浇花了",
    "阻塞": False, "谁声明": "主 agent", "登记时刻": 定时.现在() - 900,
    "状态": "挂着", "补的": False,
}])
果 = 定时.重挂()
查("重挂认出过期那条", 果["刚响"] == 1, json.dumps(果, ensure_ascii=False))
话 = 定时.取待办()
查("补的交回时标明是补的", bool(话) and "补的" in str(话), str(话))

# ── 5. 本轮的阻塞条目只认本轮的 ────────────────────────────────
print("\n[5] 「本轮」判据")
清表()
轮2 = 定时.开一轮()
码, 数据 = 登记("300秒后提醒我旧事，先去忙别的")     # 非阻塞
查("非阻塞不算阻塞条目", 定时.本轮的阻塞条目(轮2) == [])
码2, _ = 登记("300秒倒计时，就在这等着")
查("同一轮里登记的阻塞条目认得出", len(定时.本轮的阻塞条目(轮2)) == 1)
查("换个记号 -> 认不出别人那一轮的", 定时.本轮的阻塞条目("别的轮") == [])

print(f"\n{通过}/{通过 + 不过} 通过")
sys.exit(0 if 不过 == 0 else 1)

#!/usr/bin/env python3
"""定时任务回归 —— 全在沙盒里跑(冷库沙盒表前缀 + 自己的配置 + 假时钟), 不碰生产表.

跑法: .venv/bin/python skill/timer/tests/test_timer.py

沙盒怎么隔: 环境变量 COLLAPLEX_DB_PREFIX=验定时_ → 所有表名自动带前缀(验定时_timers),
跑完自己删表。★ 表已经不在本地文件里了(2026-10-09 起落冷库)。

覆盖: 时长解析 / 时刻解析 / 四项判据 / 登记 / 非阻塞到点注入 / 阻塞式等(读秒) /
      撤销 / 上限 20 条 / 跨重启重挂补一次 / 线程到点自标 + 空了自停 / 表落冷库(按进程键分行) /
      命令行走一遍(main.py) / 引擎自检
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

沙盒 = Path(tempfile.mkdtemp(prefix="timer-验-"))
技能根 = Path(__file__).resolve().parent.parent
项目根 = 技能根.parent.parent

# ★ 这几行必须在 import 引擎 **之前** 设好 —— 引擎在 import 时就把配置路径定死了
os.environ["COLLAPLEX_DB_PREFIX"] = "验定时_"      # 冷库沙盒: 表名带前缀(验定时_timers)
os.environ["COLLAPLEX_TIMER_CONFIG"] = str(沙盒 / "timer.json")
os.environ["COLLAPLEX_TIMER_PROCESS"] = "验"
os.environ["COLLAPLEX_TIMER_SPEED"] = "200"        # 假时钟: 200 倍
原加速 = os.environ["COLLAPLEX_TIMER_SPEED"]       # 第 13 段要临时切回真钟再切回来

sys.path.insert(0, str(项目根))                       # 冷库公用层是仓根的 store.py
sys.path.insert(0, str(技能根 / "scripts"))
import memory_store as 库                                       # noqa: E402 - 要在设置环境之后
import timer_engine as 引擎                                   # noqa: E402 - 必须在设置环境之后

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


def 清表() -> None:
    引擎.写表([])


print(f"沙盒: {沙盒}")

# ── 1. 时长解析 ────────────────────────────────────────────────
print("\n[1] 时长解析")
for 文, 期望 in [("30分钟", 1800.0), ("1小时20分", 4800.0), ("一个半小时", 5400.0),
                 ("两个半小时", 9000.0), ("90秒", 90.0), ("0.5小时", 1800.0),
                 ("半小时", 1800.0), ("一刻钟", 900.0), ("2天", 172800.0)]:
    拿到 = 引擎.解析时长(文)
    查(f"{文} -> {期望:g} 秒", 拿到 == 期望, f"拿到 {拿到}")
查("没有单位就不认(该走条件不足)", 引擎.解析时长("一会儿") is None)
查("两处说法不相邻就不累加(别把 40 秒加成 80)",
   引擎.解析时长("40秒倒计时，就在这等着，到点提醒我40秒到了") == 40.0,
   str(引擎.解析时长("40秒倒计时，就在这等着，到点提醒我40秒到了")))

# ── 2. 时刻解析 ────────────────────────────────────────────────
print("\n[2] 时刻解析")
import datetime                                        # noqa: E402
# ★ 拿**引擎的钟**当「现在」: 假时钟下它的绝对值跟真实日期无关(固定锚 + 倍率),
#   所以期望值也得照它的钟算, 不能拿外面的 datetime.now() 比。
现在 = datetime.datetime.fromtimestamp(引擎.墙钟())
三点 = 引擎.解析时刻("下午3点")
查("下午3点 -> 15:00", 三点 is not None and
   datetime.datetime.fromtimestamp(三点).strftime("%H:%M") == "15:00")
明早 = 引擎.解析时刻("明天早上7点")
查("明天早上7点 -> 明天 07:00", 明早 is not None and
   datetime.datetime.fromtimestamp(明早).strftime("%m-%d %H:%M") ==
   (现在 + datetime.timedelta(days=1)).strftime("%m-%d") + " 07:00")
查("说个已经过了的钟点 -> 顺推到明天",
   引擎.解析时刻(f"{现在.hour:02d}:{现在.minute:02d}") is not None and
   datetime.datetime.fromtimestamp(引擎.解析时刻(f"{现在.hour:02d}:{现在.minute:02d}") or 0) > 现在)
查("『晚上』不认成上午", datetime.datetime.fromtimestamp(
    引擎.解析时刻("晚上8点半") or 0).hour == 20)
查("中文数字的钟点也认(下午三点)", datetime.datetime.fromtimestamp(
    引擎.解析时刻("下午三点") or 0).strftime("%H:%M") == "15:00")

# ── 2b. 提醒抽干净(真机抓出的套娃根因) ──────────────────────────
# ★ 提醒原样喂回主 agent; 带回去的要是「30秒倒计时，就在这等着」这种指令, 模型会当新任务
#   再登记一条 -> 无限套娃。所以到点那句只能是内容本身。
print("\n[2b] 提醒内容抽干净")
for 文, 期望 in (("30秒倒计时，就在这等着，到点提醒我关火", "关火"),
                ("30秒后提醒我水开了，先去忙别的", "水开了"),
                ("1小时后提醒我给妈妈打电话，先去忙别的", "给妈妈打电话"),
                ("30秒倒计时，就在这等着", "时间到了"),
                ("下午三点开会", "开会")):
    拿到 = str(引擎.提取提醒(文))
    查(f"{文} -> {期望}", 拿到 == 期望, f"拿到 {拿到}")
查("提醒里不许再留『倒计时 / 等着』这种指令词",
   "倒计时" not in str(引擎.判据("30秒倒计时，就在这等着")["参数"]["提醒"])
   and "等着" not in str(引擎.判据("30秒倒计时，就在这等着")["参数"]["提醒"]))

# ── 3. 四项判据 ────────────────────────────────────────────────
print("\n[3] 四项判据")
好 = 引擎.判据("30分钟后提醒我关火，先去忙别的")
查("四项齐全 -> 可以", 好["可以"] and 好["参数"]["阻塞"] is False,
   json.dumps(好, ensure_ascii=False))
缺时间 = 引擎.判据("提醒我喝水")
查("缺时间 -> 报出来 + 给可选项",
   not 缺时间["可以"] and any("时间" in 一一 for 一一 in 缺时间["缺"]) and bool(缺时间["可选"]))
缺阻塞 = 引擎.判据("下午三点叫我起来")
查("缺阻塞还是非阻塞 -> 报出来", not 缺阻塞["可以"] and any("阻塞" in 一一 for 一一 in 缺阻塞["缺"]),
   json.dumps(缺阻塞, ensure_ascii=False))
超上限 = 引擎.判据("200分钟后叫醒我，等着")
查("阻塞 200 分钟 -> 超上限, 且摆出两个可选项",
   not 超上限["可以"] and any("超上限" in 一一 for 一一 in 超上限["缺"]) and len(超上限["可选"]) >= 1)
非阻塞长等 = 引擎.判据("300分钟后提醒我带伞，先去忙别的")
查("非阻塞 300 分钟 -> 不设上限", 非阻塞长等["可以"], json.dumps(非阻塞长等, ensure_ascii=False))

# ── 4. 登记 + 非阻塞到点注入 ───────────────────────────────────
print("\n[4] 登记 -> 到点 -> 注入(非阻塞, 假时钟)")
清表()
r = 引擎.判据("2秒后提醒我眨眼，先去忙别的")
条, 说明 = 引擎.登记(r["参数"])
查("登记进表", 条 is not None and len(引擎.列出()) == 1, 说明)
查("非阻塞条目 阻塞=False", bool(条 and 条["阻塞"]) is False)
time.sleep(0.2)                                        # 2 秒 / 200 倍 = 0.01 秒, 睡够
待 = 引擎.捡待注入()
查("到点被搬进待注入", len(待) == 1, f"待注入 {len(待)}")
查("提醒话是固定格式", bool(待) and 待[0]["话"] if False else  # noqa: SIM108 - 保留写法
   (bool(待) and 引擎.提醒话(引擎.列出(只要挂着=True)[0] if 引擎.列出() else 待[0]).startswith("⏰ 你定的闹钟到了：")))
查("准点响的不算『补的』", bool(待) and 待[0].get("补的") is False)
查("注入过就不再重复(幂等)", 引擎.捡待注入() == [])

# ── 5. 阻塞式等(读秒) ──────────────────────────────────────────
print("\n[5] 阻塞式等 + 读秒")
清表()
r = 引擎.判据("40秒倒计时，就在这等着")
条, _ = 引擎.登记(r["参数"])
assert 条 is not None                                  # 上面刚判据过, 这里只为过类型检查
读秒: list[float] = []
到点 = 引擎.等(条, lambda 剩: 读秒.append(剩))
查("等到点返回 True", 到点 is True)
查("等的时候回调了读秒(至少一次)", len(读秒) >= 1, f"读了 {len(读秒)} 次")

# ── 6. 撤销 ───────────────────────────────────────────────────
print("\n[6] 撤销")
清表()
r = 引擎.判据("60秒倒计时，就在这等着")
条, _ = 引擎.登记(r["参数"])
撤, 说明撤 = 引擎.撤销(str(条["id"]) if 条 else None)
查("撤掉给 id 的那条", 撤 is not None and len(引擎.列出()) == 0, 说明撤)
查("撤了之后等() 自己能停", 条 is not None and 引擎.等(条, None) is False)
撤2, 说明2 = 引擎.撤销("不存在的id")
查("撤不存在的 id -> 报没找着", 撤2 is None and "没找着" in 说明2)

# ── 7. 上限 20 条 ──────────────────────────────────────────────
print("\n[7] 上限 20 条")
清表()
满 = 0
for i in range(20):
    参 = 引擎.判据(f"{600 + i}秒后提醒我第 {i} 条，先去忙别的")
    条i, _ = 引擎.登记(参["参数"])
    if 条i is not None:
        满 += 1
第21 = 引擎.判据("900秒后提醒我第 21 条，先去忙别的")
条21, 说明21 = 引擎.登记(第21["参数"])
查("能挂满 20 条", 满 == 20, f"挂上 {满} 条")
查("第 21 条被拒 + 说清怎么办", 条21 is None and "上限" in 说明21, 说明21)

# ── 8. 跨重启重挂 + 补一次 ─────────────────────────────────────
print("\n[8] 跨重启重挂 + 补一次")
清表()
引擎.写表([{
    "id": "dead0001", "类型": "倒计时", "到点": 引擎.单调() - 300, "提醒": "该浇花了",
    "阻塞": False, "谁声明": "主 agent", "登记时刻": 引擎.单调() - 600,
    "状态": "挂着", "补的": False,
}])
果 = 引擎.重挂()
查("重挂把过期的标出来了", 果["刚响"] == 1, json.dumps(果, ensure_ascii=False))
待 = 引擎.捡待注入()
查("补的那条用了『补的』前缀",
   bool(待) and 引擎.提醒话(待[0]).startswith("⏰ 你定的闹钟到了（这条是补的"),
   str(引擎.提醒话(待[0])) if 待 else "空")
查("补的条目带 补的=True 标记", bool(待) and 待[0].get("补的") is True)

# ── 9. 线程: 到点自标 + 空了自停 ───────────────────────────────
print("\n[9] 定时器线程")
引擎.停线程()                                        # 第 8 段的重挂可能已经起过一条, 先停干净
清表()
r = 引擎.判据("40秒后提醒我线程这条，先去忙别的")
条, _ = 引擎.登记(r["参数"])
起了 = 引擎.起线程()
查("按需起线程", 起了 is True and 引擎.线程活着())
查("重复起不会起第二条", 引擎.起线程() is False)
等标 = time.time()
while time.time() - 等标 < 5 and not any(t.get("状态") == "到点待注入" for t in 引擎.读表()):
    time.sleep(0.05)
查("线程把到点的标掉了", any(t.get("状态") == "到点待注入" for t in 引擎.读表()))
引擎.捡待注入()
等停 = time.time()
while time.time() - 等停 < 5 and 引擎.线程活着():
    time.sleep(0.05)
查("表空 + 空闲一会儿 -> 线程自己关掉(看门狗)", not 引擎.线程活着())

# ── 10. 原子写不留 tmp ────────────────────────────────────────
print("\n[10] 落盘")
清表()
查("表落冷库(写过能读回来)", 引擎.写表([]) is None and 引擎.读表() == [])
残留 = list((沙盒 / "state").glob("*.tmp"))
查("没有留半截 tmp 件", not 残留, str(残留))
查("同一张表按进程键分行(别的键读不到这一行)",
    库.读文档("timers", "验") is not None and 库.读文档("timers", "别的进程") is None,
    f"表={引擎.表名()} 行键={引擎.进程键()}")

# ── 11. 命令行走一遍(main.py) ─────────────────────────────────
print("\n[11] 命令行(main.py)")
清表()
环境 = dict(os.environ)
跑 = subprocess.run([sys.executable, str(技能根 / "main.py"), "register",
                    "30分钟后提醒我命令行这条，先去忙别的", "--json"],
                   cwd=项目根, capture_output=True, text=True, env=环境)
查("register 退出码 0", 跑.returncode == 0, 跑.stderr[-200:])
try:
    js = json.loads(跑.stdout)
    查("--json 给的是纯 JSON", js.get("登记") is True and bool(js.get("id")), 跑.stdout[:200])
except json.JSONDecodeError:
    查("--json 给的是纯 JSON", False, 跑.stdout[:200])
跑2 = subprocess.run([sys.executable, str(技能根 / "main.py"), "register", "提醒我喝水", "--json"],
                    cwd=项目根, capture_output=True, text=True, env=环境)
查("条件不足 -> 退出码 1", 跑2.returncode == 1, f"退出码 {跑2.returncode}")
跑3 = subprocess.run([sys.executable, str(技能根 / "main.py"), "list", "--json"],
                    cwd=项目根, capture_output=True, text=True, env=环境)
查("list 数得对", json.loads(跑3.stdout).get("条数") == 1, 跑3.stdout[:200])

# ── 12. 引擎自检 ──────────────────────────────────────────────
print("\n[12] 引擎自检")
自检好, 报告 = 引擎.自检()
查("自检通过", 自检好, " / ".join(报告))

# ── 13. 真钟那一路: 两个钟必须各归各 ─────────────────────────────
# ★ 假时钟下 墙钟/单调 同轴, 会把「倒计时的到点用单调、判到期却用墙钟」这种错盖住
#   (真机实测抓出来过: 倒计时一登记就被判成到点, 还误标「补的」)。这一段专门跑真钟。
print("\n[13] 真钟(加速=1): 倒计时用单调钟, 闹钟用墙钟")
os.environ["COLLAPLEX_TIMER_SPEED"] = "1"
清表()
查("真钟下两个钟不是一把", 引擎.墙钟() > 1e9 > 引擎.单调(),
   f"墙钟 {引擎.墙钟():.0f} / 单调 {引擎.单调():.0f}")
真条, _ = 引擎.登记(引擎.判据("5秒后提醒我真钟这条，先去忙别的")["参数"])
assert 真条 is not None                                # 上面判据过了一定登记成功, 这行只为过类型检查
查("真钟下倒计时的到点写在单调钟上",
  abs(float(真条["到点"]) - (引擎.单调() + 5)) < 1.0,
  f"到点 {float(真条['到点']):.0f} / 单调+5 {引擎.单调() + 5:.0f}")
查("刚登记的倒计时不该被判到期", 引擎.扫到点() == [], str(引擎.扫到点()))
time.sleep(6.0)
刚响 = 引擎.扫到点()
查("真等了 5 秒之后才判到期", len(刚响) == 1, f"刚响 {len(刚响)}")
查("准点响的不算『补的』", bool(刚响) and 刚响[0]["补的"] is False,
   str(刚响[0].get("补的")) if 刚响 else "空")
真待 = 引擎.捡待注入()
查("真钟下提醒话不带『补的』前缀",
   bool(真待) and 引擎.提醒话(真待[0]).startswith("⏰ 你定的闹钟到了："),
   str(引擎.提醒话(真待[0])) if 真待 else "空")
os.environ["COLLAPLEX_TIMER_SPEED"] = 原加速

# ── 14. 阻塞式倒计时: 从「开始等」重新起算 ────────────────────────
# ★ 登记在 skill 子进程里, 之后模型还要说一大段话(真机实测常耗 60 秒+)—— 短倒计时会在
#   框架真正开始等之前就走完, 一格读秒都看不见。所以阻塞式倒计时从「开始等」重新起算。
print("\n[14] 阻塞式倒计时: 重新起算(只对倒计时, 闹钟不动)")
os.environ["COLLAPLEX_TIMER_SPEED"] = "1"
清表()
慢条, _ = 引擎.登记(引擎.判据("30秒倒计时，就在这等着")["参数"])
assert 慢条 is not None
time.sleep(1.2)                                       # 假装模型先说了一大段话
查("重新计时把到点推成「现在 + 时长」",
  引擎.重新计时(慢条) and abs(float(慢条["到点"]) - (引擎.单调() + 30)) < 1.0,
  f"到点-单调 = {float(慢条['到点']) - 引擎.单调():.1f} 秒")
目标 = datetime.datetime.fromtimestamp(引擎.墙钟() + 1800)      # 半小时后的一个钟点 -> 阻塞式也不越 180 上限
词 = 目标.strftime("%H:%M")
if 目标.day != datetime.datetime.fromtimestamp(引擎.墙钟()).day:
    词 = "明天" + 词                                       # 跨零点就说「明天」, 免得被顺推成 24 小时后
闹条, _ = 引擎.登记(引擎.判据(f"{词}叫我起来，就在这等着")["参数"])
assert 闹条 is not None
查("闹钟绝不重新计时(点就是点)", 引擎.重新计时(闹条) is False)
os.environ["COLLAPLEX_TIMER_SPEED"] = 原加速

print(f"\n{通过}/{通过 + 不过} 通过")

# 收尾: 把沙盒表删掉(测试不许在生产表里留东西)
库.删表("timers")
print("沙盒表已删:", 库.表名("timers"))
sys.exit(0 if 不过 == 0 else 1)

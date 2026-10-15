#!/usr/bin/env python3
"""定时任务引擎 —— 闹钟 + 倒计时。

定调(2026-10-09 老板定, 见 diagrams/定时任务.drawio 两页):
- 本体 = 闹钟(说时刻) + 倒计时(说时长); 阻塞 / 非阻塞由主 agent 声明
- 任务表落**冷库**(PG 表 timers), 按进程键分行 —— web 与 CLI 会同时开着, 同一张表各占一行不互相覆盖
  (仓里没有跨进程锁的先例; 提醒本来就只该回它自己那个进程, 分开正好)
- 倒计时按单调钟量时长, 闹钟按墙钟定点; 存盘存绝对时刻(单调钟跨不了重启)
- 重挂发现「早该响」的条目 -> 补一次, 并标明是补的
- 阻塞式硬上限 180 分钟: 超了算「条件不合」, **不悄悄降级**, 由子 agent 提醒主 agent 摆可选项
- 测试钩子: COLLAPLEX_TIMER_SPEED=N 让时间流快 N 倍(假时钟)

谁跑线程: 线程在**框架进程**里(主 agent 那一侧), 不在 skill 子进程里 —— skill 子进程登记完就退。
交付提醒是「拉」式: 每轮开场扫表, 过期的搬进「到点待注入」; 线程只负责让它准时、以及在本进程空闲时也能标到点。
两边都幂等(看 状态), 所以线程没起着也不会漏提醒。

对外: 解析时长 · 解析时刻 · 判据 · 登记 · 撤销 · 列出 · 待注入 · 已注入 · 等 · 起线程 · 重挂 · 自检
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, cast

HERE = Path(__file__).resolve().parent          # skill/timer/scripts
根 = HERE.parent.parent.parent                  # 项目根
if str(根) not in sys.path:                    # 冷库公用层在仓根(库.py)
    sys.path.insert(0, str(根))
import 库  # noqa: E402  - 路径要先塞好

_配置环境 = os.environ.get("COLLAPLEX_TIMER_CONFIG", "").strip()
配置路径 = Path(_配置环境) if _配置环境 else 根 / "config" / "timer.json"

默认配置: dict[str, Any] = {
    "上限分钟_阻塞": 180,
    "最多条数": 20,
    "空闲退出秒": 60,
    "轮询秒": 0.2,
    "补的阈值秒": 60,
    "提醒前缀": "⏰ 你定的闹钟到了：",
    "补的提醒前缀": "⏰ 你定的闹钟到了（这条是补的，早就该响）：",
}

# ── 时间: 两个钟(真机上是两个不同的钟; 假时钟下同轴), 加速时一起快 ────


def 加速() -> float:
    """假时钟倍率: COLLAPLEX_TIMER_SPEED=60 就是「一分钟当一分钟用 -> 一秒」.

    ★ 环境变量名必须是 ASCII(bash 的 export 只吃 ASCII 名), 所以这里的名字不写中文.
    """
    原文 = os.environ.get("COLLAPLEX_TIMER_SPEED", "").strip()
    if not 原文:
        return 1.0
    try:
        return max(1.0, float(原文))
    except ValueError:
        return 1.0


_假锚 = 1750000000.0          # 假时钟的固定锚(常数): 各进程算出来同一个值, 跨进程才对得上


def 墙钟() -> float:
    """墙钟(闹钟定点用): 跟着系统钟走 —— NTP 校正/改时间它跟着动, 这正是"定点"要的.

    ★ 假时钟(加速)时改成从**固定锚**线性映射 —— 不能各进程锚自己进程的启动时刻,
      否则子进程写的 到点 和框架算的 现在 差着 (加速-1)×真实耗时, 跨进程没法比。
    """
    K = 加速()
    if K == 1.0:
        return time.time()
    return _假锚 + (time.time() - _假锚) * K


def 单调() -> float:
    """单调钟(倒计时量时长用): 只量「过了多久」, 系统钟被跳变也不受影响.

    ★ 假时钟下与 墙钟() 同轴(测试要的是"快 N 倍的同一根时间轴"); 「单调」这套区别
      只在真机上有意义(挂起恢复/NTP 跳变), 那个假时钟本来也模拟不了。
    """
    K = 加速()
    if K == 1.0:
        return time.monotonic()
    return _假锚 + (time.time() - _假锚) * K


def 配置() -> dict[str, Any]:
    """读 config/timer.json; 读不到就用默认(键名带 _ 的是注释, 不覆盖)."""
    合并: dict[str, Any] = dict(默认配置)
    try:
        原始: Any = json.loads(配置路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 合并
    if isinstance(原始, dict):
        for k, v in cast(dict[str, Any], 原始).items():
            if not str(k).startswith("_"):
                合并[str(k)] = v
    return 合并


def 补阈值() -> float:
    """晚了超过这个秒数才响的, 标成「补的」."""
    return float(配置()["补的阈值秒"])


def 轮记号() -> str:
    """框架给每一轮打的小记号(环境变量带下来) —— 用来认「这条是这一轮登记的」.

    ★ 为什么不拿「登记时刻 >= 本轮起点」判: 两个进程各自锚定时钟, 加速(假时钟)下根本不可比;
      记号跟着环境走, 哪个进程写的都能对得上.
    """
    return os.environ.get("COLLAPLEX_TIMER_TURN", "").strip()


def 进程键() -> str:
    """这张表属于哪个进程: web / cli(默认). 由框架在启动时用环境变量点名.

    ★ 名字写 ASCII: bash 里 export 非 ASCII 名会直接报「不是有效的标识符」.
    """
    原文 = os.environ.get("COLLAPLEX_TIMER_PROCESS", "").strip()
    return 原文 or "cli"


# ── 表: 落冷库(PG)。一个进程一行: 键 = 进程键, 值 = 这一进程的条目们 ────
# ★ 2026-10-09 换存放处: 原先是 state/timers-<进程键>.json（本地文件）。
#   冷库这边一条 upsert 就是原子的, 不再需要"先写临时件再换名"那套。
_表锁 = threading.RLock()


def 表名() -> str:
    """表叫什么（带沙盒前缀）。★ 进程键是**行键**不是表名：web 与 CLI 同一张表、各占一行。"""
    return 库.表名("timers")


def 读表() -> list[dict[str, Any]]:
    """读这一进程的条目。★ 冷库不通要炸出来 —— 静默当空表会把别人的条目覆盖掉。"""
    with _表锁:
        原始: Any = 库.读文档("timers", 进程键())
    if not isinstance(原始, list):
        return []
    return [dict(cast(dict[str, Any], 条)) for 条 in cast(list[Any], 原始) if isinstance(条, dict)]


def 写表(条目们: list[dict[str, Any]]) -> None:
    """整份写回这一进程那一行（upsert，一条语句就是原子的）。"""
    with _表锁:
        库.写文档("timers", 进程键(), 条目们)


# ── 文本解析: 时长 / 时刻(确定性, 不劳模型) ─────────────────────────
中文数: dict[str, int] = {"零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
                          "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
时长单位: dict[str, float] = {"秒": 1.0, "分钟": 60.0, "分": 60.0,
                              "小时": 3600.0, "时": 3600.0, "个钟头": 3600.0, "天": 86400.0}
时长模式 = re.compile(r"(\d+(?:\.\d+)?)\s*(?:个)?\s*(天|小时|个钟头|时|分钟|分|秒)")


def 挖中文数(文: str) -> str:
    """把常见中文数字换成阿拉伯数字, 同时把「半小时 / 一个半 / 一刻钟」折算成数字."""
    出 = 文
    出 = re.sub(r"([一二两三四五六七八九十])个半小时",
                lambda m: f"{中文数[m.group(1)] + 0.5}小时", 出)
    出 = 出.replace("半小时", "0.5小时").replace("半个钟头", "0.5小时")
    出 = 出.replace("一刻钟", "15分钟")
    出 = re.sub(r"([一二两三四五六七八九十])个?(天|小时|个钟头|时|分钟|分|秒|点)",
                lambda m: f"{中文数[m.group(1)]}{m.group(2)}", 出)
    return 出


def 解析时长(文本: str) -> float | None:
    """一句话里有「等多久」就折成秒: 30分钟 / 1小时20分 / 一个半小时 / 90秒 / 0.5小时.

    ★ 只把**挨着的**几段单位加在一起("1小时20分" = 一段复合说法), 中间隔了别的字就停 ——
      否则「40秒阻塞式倒计时…到点提醒我40秒到了」会被加成 80 秒(2026-10-09 真机实测抓出来的)。
    """
    s = 挖中文数((文本 or "").strip())
    if not s:
        return None
    总 = 0.0
    命中 = False
    上一段末 = -1
    for m in 时长模式.finditer(s):
        if 命中 and m.start() > 上一段末 + 2:      # 中间隔了内容 -> 这是另一处说法, 不再累加
            break
        命中 = True
        总 += float(m.group(1)) * 时长单位[m.group(2)]
        上一段末 = m.end()
    return 总 if 命中 and 总 > 0 else None


def 解析时刻(文本: str) -> float | None:
    """一句话里有「几点」就折成绝对时刻: 14:30 / 下午3点 / 晚上8点半 / 明天早上7点.

    说的时刻今天已经过了(且没说"明天/后天") -> 顺推到明天.
    """
    原 = (文本 or "").strip()
    if not 原:
        return None
    s = 挖中文数(原)
    天偏移 = 0
    if "后天" in s:
        天偏移 = 2
    elif "明天" in s or "明早" in s or "明晚" in s:
        天偏移 = 1
    for 词 in ("后天", "明天", "明早", "今早", "今天", "今儿", "今晚"):
        s = s.replace(词, "")
    s = s.replace("明晚", "晚上").replace("今晚", "晚上")
    半 = "半" in s
    s = s.replace("半", "")
    m = re.search(r"(\d{1,2})\s*[:：点时]\s*(\d{1,2})?", s)
    if m is None:
        return None
    时 = int(m.group(1))
    分 = int(m.group(2)) if m.group(2) is not None else 0
    if 半:
        分 = 30
    if 时 > 24 or 分 > 59:
        return None
    下午 = any(k in 原 for k in ("下午", "傍晚", "晚上", "夜里", "夜里", "晚"))
    上午 = any(k in 原 for k in ("上午", "早上", "早晨", "凌晨", "早"))
    if 下午 and 时 < 12:
        时 += 12
    if 上午 and 时 == 12:
        时 = 0
    if 时 == 24:
        时 = 0
    现在 = 墙钟()
    今天 = datetime.fromtimestamp(现在).replace(hour=时, minute=分, second=0, microsecond=0)
    目标 = 今天 + timedelta(days=天偏移)
    if 天偏移 == 0 and 目标.timestamp() <= 现在:
        目标 += timedelta(days=1)
    return 目标.timestamp()


# ── 判据: 四项(时间 / 提醒什么 / 阻塞还是非阻塞 / 是否 ≤ 上限) ────────
阻塞词 = ("等着", "等到", "就在这", "阻塞", "守着", "一直等", "等它响", "盯着")
非阻塞词 = ("提醒我", "提醒你", "到时候告诉", "不用等", "先去忙", "回头告诉", "通知我", "提醒下")

时刻模式 = re.compile(r"\d{1,2}\s*[:：点时]\s*\d{0,2}")
# 「到点要说的那句」的提示词(见到就取它后面的内容); 长的排前面, 免得短的先截
提醒提示 = ("提醒我一下", "提醒我一声", "提醒我", "提醒下", "提醒一声", "提醒", "叫我起来",
            "叫醒我", "叫我", "通知我", "告诉我", "说一声", "说声")
# 尾巴上这些是「阻塞还是非阻塞」的说法, 不算提醒内容
尾巴说法 = ("就在这儿等着", "就在这等着", "就在这等我", "就在这守着", "就在这", "守着",
            "等着", "我先去忙别的", "我先去忙", "先去忙别的", "先去忙", "我先去干别的",
            "先去干别的", "我去忙", "不用等", "先走", "去忙")
时间词头 = ("明天早上", "明天上午", "明天中午", "明天下午", "明天晚上", "明早", "明晚",
            "今天早上", "今天上午", "今天中午", "今天下午", "今天晚上", "早上", "上午",
            "中午", "下午", "晚上", "凌晨", "明天", "今天", "今晚", "到点", "到时候")


def 提取提醒(原话: str) -> str:
    """从原话里挑出「到点要跟老板说的那句」.

    ★ 为什么非挑不可: 这句会原样喂回主 agent —— 要是把「30秒倒计时，就在这等着」整句带回去,
      收到提醒的模型会把它当**新任务**再登记一条, 于是无限套娃(2026-10-09 真机实测抓到)。
    """
    s = 挖中文数(原话 or "").strip()
    if not s:
        return ""
    内容 = ""
    for 提示 in 提醒提示:                      # 1) 「…提醒我 X」-> 取 X
        位置 = s.rfind(提示)
        if 位置 >= 0:
            内容 = s[位置 + len(提示):]
            break
    if not 内容.strip(" 　,，.。、:：;；!！?？"):     # 2) 没有提示词: 摘掉时间说法, 剩下的就是内容
        内容 = 时长模式.sub("", s)
        内容 = 时刻模式.sub("", 内容)
    for 词 in 时间词头:
        内容 = 内容.replace(词, "")
    for 词 in 提醒提示:                        # 提醒提示词本身不算内容(免得留下个「叫我」)
        内容 = 内容.replace(词, "")
    for 尾 in 尾巴说法:
        内容 = 内容.replace(尾, "")
    内容 = 内容.strip(" 　,，.。、:：;；!！?？和跟与我")
    if 内容 in ("倒计时", "计时", "闹钟", "定时", ""):
        内容 = "时间到了"                      # 原话里没说要提醒什么 -> 给个通用的
    return 内容


def 判据(原话: str, 类型: str | None = None, 时长: float | None = None,
        时刻: float | None = None, 阻塞: bool | None = None,
        提醒: str | None = None) -> dict[str, Any]:
    """解一条「登记」声明. 缺什么、有哪些可选项, 一块儿给出来(交给子 agent 去提醒主 agent).

    返回: {可以, 参数, 缺, 可选}
    """
    s = (原话 or "").strip()
    配置表 = 配置()
    上限分钟 = int(配置表["上限分钟_阻塞"])

    时长 = 时长 if 时长 is not None else 解析时长(s)
    时刻 = 时刻 if 时刻 is not None else 解析时刻(s)
    if 类型 is None:
        类型 = "倒计时" if 时长 is not None else ("闹钟" if 时刻 is not None else None)

    缺: list[str] = []
    可选: list[str] = []

    if 类型 == "倒计时" and 时长 is not None:
        到点 = 单调() + 时长
        间隔 = 时长
    elif 类型 == "闹钟" and 时刻 is not None:
        到点 = 时刻
        间隔 = 时刻 - 墙钟()
    else:
        到点 = None
        间隔 = None
        缺.append("时间 —— 等多久(倒计时)或几点(闹钟)")
        可选.append("倒计时:「30 分钟后」「2 小时」; 闹钟:「14:30」「晚上八点」「明天早上 7 点」")

    if 阻塞 is None:
        if any(k in s for k in 阻塞词):
            阻塞 = True
        elif any(k in s for k in 非阻塞词):
            阻塞 = False
    if 阻塞 is None:
        缺.append("阻塞还是非阻塞 —— 要我等在这儿, 还是先放我走")
        可选.append("阻塞: 加「等我」「就在这等着」; 非阻塞: 加「提醒我」「先去忙别的」")
    elif 阻塞 and 间隔 is not None and 间隔 > 上限分钟 * 60:
        缺.append(f"阻塞式超上限 —— 你要等 {间隔 / 60:.0f} 分钟, 上限是 {上限分钟} 分钟")
        可选.append(f"① 改短到 ≤{上限分钟} 分钟; ② 改成非阻塞(我先走, 到点提醒你)")
    elif 间隔 is not None and 间隔 <= 0:
        缺.append("这个时刻已经过了(或就在当下)")
        可选.append("换个还没到的时刻, 或者改用倒计时(等多久)")

    提醒 = (提醒 or 提取提醒(s)).strip()
    if not 提醒:
        缺.append("提醒什么 —— 到点要跟你说的那句话")

    参数: dict[str, Any] = {}
    if not 缺:
        参数 = {"类型": 类型, "到点": 到点, "提醒": 提醒, "阻塞": bool(阻塞),
                "间隔秒": 间隔 or 0.0}
    return {"可以": not 缺, "参数": 参数, "缺": 缺, "可选": 可选}


# ── 动作: 登记 / 撤销 / 列出 / 到点 / 注入 ───────────────────────────
def 新条目(参数: dict[str, Any], 谁声明: str = "主 agent") -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:8],
        "类型": 参数["类型"],
        "到点": float(参数["到点"]),
        "时长": float(参数.get("间隔秒") or 0.0),      # 倒计时的时长(重新计时要靠它)
        "提醒": str(参数["提醒"]),
        "阻塞": bool(参数["阻塞"]),
        "谁声明": 谁声明,
        "登记时刻": 墙钟(),
        "轮记号": 轮记号(),
        "状态": "挂着",
        "补的": False,
    }


def 重新计时(条: dict[str, Any]) -> bool:
    """阻塞式倒计时: 从「框架开始等」那一刻重新起算.

    ★ 为什么不在登记那一刻起算: 登记发生在 skill 子进程里, 之后模型还要说一大段话、
      还可能兜底重试一次 —— 真实等待往往晚几十秒才开始, 短倒计时(60 秒)会整段走完,
      一格读秒都看不见(2026-10-09 真机实测)。「就在这等着」的本意是"从我开始等算这个时长"。
    只动「倒计时 + 还挂着 + 有时长」的条目; **闹钟绝不重新计时**(点就是点)。
    """
    if 条.get("类型") != "倒计时" or not 条.get("时长"):
        return False
    条目们 = 读表()
    for 现存 in 条目们:
        if str(现存.get("id")) != str(条.get("id")) or 现存.get("状态") != "挂着":
            continue
        现存["到点"] = 单调() + float(现存["时长"])
        条["到点"] = 现存["到点"]
        写表(条目们)
        return True
    return False


def 登记(参数: dict[str, Any], 谁声明: str = "主 agent") -> tuple[dict[str, Any] | None, str]:
    """写进表. 返回 (条目, 说明); 满员时 条目=None 并给说明."""
    配置表 = 配置()
    最多 = int(配置表["最多条数"])
    条目们 = 读表()
    挂着 = [条 for 条 in 条目们 if 条.get("状态") == "挂着"]
    if len(挂着) >= 最多:
        return None, (f"挂着 {len(挂着)} 条, 到上限 {最多} 条了 —— "
                      f"先撤一条(撤 [id] / 撤最近那条)再登记")
    条 = 新条目(参数, 谁声明)
    条目们.append(条)
    写表(条目们)
    return 条, f"登记好了: [id {条['id']}] {条['类型']} · {到点说法(条)}"


def 到点说法(条: dict[str, Any]) -> str:
    """把「到点」说成人话.

    ★ 倒计时的「到点」是**单调钟**上的数(见 单调()), 用它当时间戳会打出一个荒唐日期 ——
      所以倒计时只报「还有多久」, 不报钟点; 只有闹钟才报钟点(它的到点本来就是墙上时刻)。
    """
    是倒计时 = 条.get("类型") == "倒计时"
    剩 = float(条["到点"]) - (单调() if 是倒计时 else 墙钟())
    if 是倒计时:
        return "已到点" if 剩 <= 0 else f"还有 {剩余说法(剩)}"
    时刻 = datetime.fromtimestamp(float(条["到点"])).strftime("%m-%d %H:%M:%S")
    if 剩 <= 0:
        return f"{时刻}（已到点）"
    return f"{时刻}（还有 {剩余说法(剩)}）"


def 剩余说法(秒: float) -> str:
    秒 = max(0.0, 秒)
    if 秒 < 60:
        return f"{秒:.0f} 秒"
    if 秒 < 3600:
        return f"{int(秒 // 60)} 分 {int(秒 % 60):02d} 秒"
    return f"{int(秒 // 3600)} 小时 {int((秒 % 3600) // 60):02d} 分"


def 撤销(编号: str | None, 最近: bool = False) -> tuple[dict[str, Any] | None, str]:
    条目们 = 读表()
    目标: dict[str, Any] | None = None
    if 编号:
        for 条 in 条目们:
            if str(条.get("id")) == 编号.strip():
                目标 = 条
                break
    elif 最近:
        挂着 = [条 for 条 in 条目们 if 条.get("状态") == "挂着"]
        if 挂着:
            目标 = max(挂着, key=lambda 条: float(条.get("登记时刻") or 0.0))
    if 目标 is None:
        return None, "没找着要撤的那条（用「列表」看一眼 id）"
    目标["状态"] = "已撤"
    目标["撤销时刻"] = 墙钟()
    写表(条目们)
    return 目标, f"撤了: [id {目标.get('id')}] {目标.get('提醒')}"


def 列出(只要挂着: bool = True) -> list[dict[str, Any]]:
    条目们 = 读表()
    if not 只要挂着:
        return 条目们
    return [条 for 条 in 条目们 if 条.get("状态") in ("挂着", "到点待注入")]


def 扫到点() -> list[dict[str, Any]]:
    """把「到点了还没标过」的条目标成「到点待注入」. 线程和每轮开场都会调, 幂等."""
    条目们 = 读表()
    刚响: list[dict[str, Any]] = []
    现在 = 墙钟()
    单调现在 = 单调()
    变了 = False
    for 条 in 条目们:
        if 条.get("状态") != "挂着":
            continue
        到点 = float(条.get("到点") or 0.0)
        此刻 = 单调现在 if 条.get("类型") == "倒计时" else 现在
        if 到点 <= 此刻:
            条["状态"] = "到点待注入"
            条["到点标时"] = 现在
            # ★ 「晚了多少」也必须用**这条自己的钟**量: 倒计时的到点是单调钟的数,
            #   拿墙钟去减会得出个天文数字 -> 每条倒计时都被误标成「补的」(真机实测抓出来的)。
            条["补的"] = bool(此刻 - 到点 > 补阈值())
            变了 = True
            刚响.append(dict(条))
    if 变了:
        写表(条目们)
    return 刚响


def 提醒话(条: dict[str, Any]) -> str:
    """到点要跟主 agent 说的那句(固定格式, 见台账「提醒格式」)."""
    前缀 = str(配置()["补的提醒前缀"] if 条.get("补的") else 配置()["提醒前缀"])
    return f"{前缀}{条.get('提醒')}"


def 捡待注入() -> list[dict[str, Any]]:
    """每轮开场: 到点的搬出来(交给框架注入主 agent), 标成「已注入」."""
    扫到点()
    条目们 = 读表()
    待: list[dict[str, Any]] = []
    变了 = False
    for 条 in 条目们:
        if 条.get("状态") == "到点待注入":
            条["状态"] = "已注入"
            条["注入时刻"] = 墙钟()
            变了 = True
            待.append(dict(条))
    if 变了:
        写表(条目们)
    return 待


# ── 阻塞式等待: 就在这一轮里等, 每秒回调一次(读秒) ──────────────────
def 等(条: dict[str, Any], 每秒: Callable[[float], None] | None = None) -> bool:
    """等到点. **整秒变了才**调 每秒(还剩多少秒). 到点返回 True; 被撤/表里没了返回 False."""
    上次整: int | None = None
    while True:
        现存 = [t for t in 读表() if str(t.get("id")) == str(条.get("id"))]
        if not 现存 or 现存[0].get("状态") in ("已撤", "已注入"):
            return False
        剩 = float(条["到点"]) - (单调() if 条.get("类型") == "倒计时" else 墙钟())
        if 剩 <= 0:
            扫到点()
            return True
        整 = int(剩)
        if 每秒 is not None and 整 != 上次整:
            每秒(剩)                    # ★ 一轮只报一次(轮询是 0.2 秒, 每轮都报会刷屏)
        上次整 = 整
        间隔 = float(配置()["轮询秒"])
        间隔 = min(1.0, max(0.05, 间隔))
        time.sleep(间隔)


# ── 定时器线程(在框架进程里; 表空 + 空闲一会儿就自己关掉) ─────────────
class 定时器线程(threading.Thread):
    """按需起、空了自停. 只做一件事: 到点了就把表里的状态标掉."""

    def __init__(self, 收到: Callable[[dict[str, Any]], None] | None = None) -> None:
        super().__init__(name="定时器线程", daemon=True)
        self.收到 = 收到
        self._停 = threading.Event()

    def 停(self) -> None:
        self._停.set()

    def run(self) -> None:
        配置表 = 配置()
        轮询 = max(0.05, float(配置表["轮询秒"]))
        空闲上限 = float(配置表["空闲退出秒"])
        空闲从 = 单调()
        while not self._停.is_set():
            刚响 = 扫到点()
            for 条 in 刚响:
                if self.收到 is not None:
                    self.收到(条)
            还有挂着的 = any(t.get("状态") == "挂着" for t in 读表())
            if 还有挂着的:
                空闲从 = 单调()
            elif 单调() - 空闲从 >= 空闲上限:
                return                      # 看门狗: 没任务了 + 又空转了一会儿 -> 关掉
            self._停.wait(轮询)


_线程锁 = threading.Lock()
_线程: 定时器线程 | None = None


def 起线程(收到: Callable[[dict[str, Any]], None] | None = None) -> bool:
    """确保线程跑着(已在跑就不重复起). 返回是否新起了一个."""
    global _线程
    with _线程锁:
        if _线程 is not None and _线程.is_alive():
            return False
        _线程 = 定时器线程(收到)
        _线程.start()
        return True


def 线程活着() -> bool:
    return _线程 is not None and _线程.is_alive()


def 停线程() -> bool:
    """把线程停掉(等它退). 给测试和收尾用. 返回是否真停过一条."""
    global _线程
    with _线程锁:
        当前 = _线程
        _线程 = None
    if 当前 is None:
        return False
    当前.停()
    当前.join(timeout=2.0)
    return True


def 重挂(收到: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """进程起来时调一次: 看表里还有什么, 过期的标成待注入(补一次), 有活就起线程."""
    刚响 = 扫到点()
    有活 = any(t.get("状态") == "挂着" for t in 读表())
    if 有活 or 刚响:
        起线程(收到)
    return {"表": 表名(), "行键": 进程键(), "刚响": len(刚响), "挂着": len(列出()),
            "线程": 线程活着()}


# ── 自检(自检脚本会用): 表能读 / 配置能读 / 解析对不对 / 全链路走一遍 ──
def 自检() -> tuple[bool, list[str]]:
    报: list[str] = []
    好 = True
    配置表 = 配置()
    if 配置表["上限分钟_阻塞"] != 180:
        报.append(f"上限不是 180 分钟(现在是 {配置表['上限分钟_阻塞']})")
    样 = [("30分钟", 1800.0), ("1小时20分", 4800.0), ("一个半小时", 5400.0),
          ("90秒", 90.0), ("0.5小时", 1800.0), ("2天", 172800.0)]
    for 文, 期望 in 样:
        拿到 = 解析时长(文)
        if 拿到 != 期望:
            好 = False
            报.append(f"时长解析不对: {文} -> {拿到}, 应该是 {期望}")
    try:
        表 = 读表()
    except Exception as 错:                     # noqa: BLE001 - 自检就该什么都接住
        好 = False
        报.append(f"表读不了: {错!r}")
        return 好, 报
    报.append(f"表: {表名()} · 行键 {进程键()} · 能读 · {len(表)} 条")
    return 好, 报

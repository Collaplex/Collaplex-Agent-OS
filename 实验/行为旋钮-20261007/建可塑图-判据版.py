"""行为旋钮 · 骨架第③层（判据版）

换奖励信号：不再只用"被拦/没被拦"（太粗，学到的只是规则），改成三层合成奖励：
  ① 环境结果        成功 +、报错 0、被拦 −（保留）
  ② 这一步有没有用   该步输出里的关键词有没有出现在那轮的最终答案里（有用 +，空转 −）
  ③ 这一轮成不成     该轮判据是否命中（命中 → 全轮正向加权；没命中 → 被拦/空转的步重罚）

考试也换：看"图推荐的做法"在历史上的**判据贡献率**（该做法出现过的轮里，判据命中占多少），
对比全体做法平均 —— 这才不会像"成功率"那样人人 100%。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

这里 = Path(__file__).parent
源 = 这里.parent / "小模型对照-20261007"
项目 = 这里.parent.parent

总线 = [json.loads(x) for x in (这里 / "反馈总线.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
快照 = {f"{x['轮']}#{x['序号']}": x for x in
        (json.loads(y) for y in (这里 / "情境快照.jsonl").read_text(encoding="utf-8").splitlines() if y.strip())}
样 = [json.loads(x) for x in (源 / "样本.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
轮表: dict[str, dict[str, Any]] = {}
for s in 样:
    轮表[f"{s.get('臂')}{s.get('题号')}-{s.get('遍')}"] = s

库原: Any = json.loads((项目 / "skill/rag/scripts/memory-index.json").read_text(encoding="utf-8"))
_列: list[Any] = cast("list[Any]", 库原) if isinstance(库原, list) else cast("list[Any]", 库原.get("items", []))
节点文 = [str(cast("dict[str, Any]", x).get("text", "")) for x in _列 if isinstance(x, dict)]

停 = {"这个", "那个", "什么", "怎么", "可以", "不是", "就是", "一个", "现在", "已经", "如果", "因为",
      "所以", "但是", "然后", "还是", "没有", "需要", "能不能", "问题", "结果", "时候", "这里", "我们",
      "本机", "命令", "执行", "输出", "文件", "目录", "用户", "要求", "建议", "使用", "可能", "应该"}
词形 = re.compile(r"[\u4e00-\u9fff]{2,4}|[A-Za-z_][A-Za-z0-9_.\-]{1,15}")


def 关键(文: str) -> set[str]:
    return {w for w in 词形.findall(文) if w not in 停}


节点词 = [关键(t) for t in 节点文]


def 情境节点(文: str) -> list[int]:
    词 = 关键(文)
    return [i for i, k in enumerate(节点词) if len(k & 词) >= 2]


def 行为族(动: str) -> str:
    """合并成"粗族"：按首词 + 参数形状，把 218 个碎族并成 30 来个。"""
    d = 动.strip()
    if not d:
        return "空"
    有sudo = d.startswith("sudo ") or " sudo " in d[:14]
    核 = d.split("sudo ", 1)[-1] if 有sudo else d
    首群 = 核.split()
    首 = (首群[0].split("/")[-1] if 首群 else "?")
    if re.search(r"\brm\b[^|]*-(rf|fr)", 核):
        return "删:递归强制"
    if re.search(r"\brm\b[^|]*-r\b", 核) or ("xargs" in 核 and "rm" in 核):
        return "删:递归"
    if "-delete" in 核:
        return "删:find带条件" if ("-name" in 核 or "-type" in 核 or "-mindepth" in 核) else "删:find裸删"
    if 首 == "rm":
        return "删:点名"
    表 = {"df": "查:磁盘", "free": "查:内存", "ss": "查:端口", "netstat": "查:端口",
          "systemctl": "查:服务", "journalctl": "查:日志", "ls": "查:目录", "du": "查:占用",
          "ps": "查:进程", "pgrep": "查:进程", "top": "查:进程", "lscpu": "查:硬件",
          "lshw": "查:硬件", "dmidecode": "查:硬件", "nvidia-smi": "查:硬件", "date": "查:系统",
          "uptime": "查:系统", "who": "查:系统", "cat": "读:文件", "head": "读:文件",
          "tail": "读:文件", "sed": "读:文件", "grep": "搜:文本", "find": "找:文件",
          "apt": "装:包", "pip": "装:包", "uv": "装:包", "curl": "网:抓取", "wget": "网:抓取",
          "echo": "写:输出", "mkdir": "动:文件", "touch": "动:文件", "cp": "动:文件", "mv": "动:文件"}
    if "skill/" in 核 or 首 in ("python", "python3", "bash", "sh"):
        return "调:skill/脚本"
    return 表.get(首, ("sudo:" + 首) if 有sudo else ("其他:" + 首))


挡 = re.compile(r"rm 带了递归|find \.\.\. -delete|不用 sudo|rm -rf|高危")


def 拦族(馈: str) -> str:
    m = 挡.search(馈)
    return "拦:" + (m.group(0) if m else 馈[:14])


# ── 组事件 + 三层奖励 ─────────────────────────────────────────
事件: list[dict[str, Any]] = []
for e in 总线:
    轮 = str(e["轮"])
    s = 轮表.get(轮)
    if not s:
        continue
    答案 = 关键(str(s.get("答案", "")))
    命 = s.get("判据命中")
    快 = 快照.get(f"{轮}#{e['序号']}")
    上馈 = str(快.get("上一步反馈", "")) if 快 else ""
    情境 = f"{s.get('题', '')} {上馈}"
    有贡献 = len(关键(str(e["反馈"])) & 答案) >= 2          # 这一步的输出进了最终答案
    奖 = 0.0
    奖 += 1.0 if e["结果"] == "成功" else (-1.2 if e["结果"] == "拦截" else 0.0)
    奖 += 0.8 if 有贡献 else -0.3
    if 命 is True:
        奖 += 1.0
    elif 命 is False:
        奖 = 奖 * 1.5 if 奖 < 0 else 奖 * 0.5
    事件.append({"轮": 轮, "序号": int(e["序号"]), "情境": 情境节点(情境),
                 "行为": 行为族(str(e["动作"])), "拦族": 拦族(str(e["反馈"])),
                 "奖": 奖, "命": 命, "上一步结果": str(快.get("上一步结果", "")) if 快 else "",
                 "结果": str(e["结果"])})
事件.sort(key=lambda x: (x["轮"], x["序号"]))
切 = int(len(事件) * 0.7)
训, 测 = 事件[:切], 事件[切:]
行为们 = sorted({e["行为"] for e in 事件} | {e["拦族"] for e in 事件})
行为号 = {b: i for i, b in enumerate(行为们)}
print(f"事件 {len(事件)} 步（训练 {len(训)} / 测试 {len(测)}）｜有贡献的步 {sum(1 for e in 事件 if e['奖'] > 1.5)}")

# 每个做法的"判据贡献率"（它出现过的轮里判据命中的比例）——考试用
轮族: defaultdict[str, set[str]] = defaultdict(set)
for e in 事件:
    轮族[e["行为"]].add(e["轮"])
判率: dict[str, float] = {}
for f, rs in 轮族.items():
    好 = sum(1 for r in rs if (轮表.get(r) or {}).get("判据命中") is True)
    判率[f] = 好 / max(1, len(rs))
全均 = sum(判率.values()) / max(1, len(判率))
print(f"全体做法的平均判据贡献率 {全均*100:.1f}%")


频: defaultdict[str, int] = defaultdict(int)
for e in 训:
    频[e["行为"]] += 1


def 跑一档(模式: str) -> dict[str, Any]:
    权重: defaultdict[tuple[int, int], float] = defaultdict(float)
    for i, e in enumerate(训):
        for n in e["情境"]:
            k = (n, 行为号.get(e["行为"], -1))
            if 模式 == "静态":
                权重[k] += 1.0 / max(1.0, 频[e["行为"]] ** 0.5)
            else:
                r = e["奖"]
                if 模式 == "只加强" and r < 0:
                    continue
                权重[k] += r * 0.1 / max(1.0, 频[e["行为"]] ** 0.5)   # 按出现频率开根号归一，去掉"高频做法"的红利
        if 模式 == "完整" and (i + 1) % 300 == 0:
            for k in list(权重):
                权重[k] *= 0.9
    考 = [e for e in 测 if e["上一步结果"] == "拦截" or e["结果"] == "拦截"]
    好 = 避 = 0
    for e in 考:
        分: defaultdict[int, float] = defaultdict(float)
        for n in e["情境"]:
            本 = [(b, w) for (nn, b), w in 权重.items() if nn == n and w > 0]
            if 本:
                b2 = max(本, key=lambda x: x[1])
                分[b2[0]] += b2[1]
        if not 分:
            continue
        名 = 行为们[max(分.items(), key=lambda kv: kv[1])[0]]
        好 += 判率.get(名, 0.0)
        if 名 != e["拦族"]:
            避 += 1
    n2 = max(1, len(考))
    return {"模式": 模式, "考步数": len(考), "推荐的判据贡献率": round(好 / n2, 3),
            "避开坑": round(避 / n2, 3)}


表 = [跑一档(x) for x in ("静态", "只加强", "完整")]
print(f"  （基线：全体做法平均判据贡献率 {全均*100:.1f}%）")
for r in 表:
    print(f"  {r['模式']:6s} 考题 {r['考步数']:3d} 步 ｜ 推荐的判据贡献率 {r['推荐的判据贡献率']*100:5.1f}% ｜ 避开坑 {r['避开坑']*100:5.1f}%")
(这里 / "结果-可塑图-判据版.json").write_text(json.dumps({"基线": 全均, "表": 表}, ensure_ascii=False, indent=1), encoding="utf-8")

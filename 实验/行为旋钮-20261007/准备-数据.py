"""行为旋钮实验 · 准备数据

产出 数据集.npz，含四样东西：
  ① 首轮样本：327 轮真数据 → 情境（题面＋上文形态）→ 行为标签（动手/先问/直接答）
  ② 被拦后样本：照正确习惯造的教材（60 条）→ 标签（换路 / 继续同族）
  ③ 情境向量：调本机 8199 嵌入服务编码
  ④ 图：295 个记忆节点（用现成向量）＋ 共现真桥（同一轮任务里一起出现的条目）
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any, cast

import numpy as np

这里 = Path(__file__).parent
源 = 这里.parent / "小模型对照-20261007"
项目 = 这里.parent.parent

# ── ① 首轮样本 ────────────────────────────────────────────────
题 = [json.loads(x) for x in (源 / "题库.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
样 = [json.loads(x) for x in (源 / "样本.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
题表: dict[int, dict[str, Any]] = {int(t["号"]): t for t in 题}


def 标签(题行: dict[str, Any]) -> str:
    """正确行为：先问（破坏性/有副作用）＞ 动手 ＞ 直接答。"""
    if 题行.get("破坏性"):
        return "先问"
    if 题行.get("该动手"):
        return "动手"
    return "直接答"


def 上文档(行: dict[str, Any]) -> str:
    臂, 遍 = str(行.get("臂")), int(行.get("遍", 1))
    if 臂 == "F":
        return "上文含之前的失败过程" if 遍 == 1 else "上文只有结论"
    if 臂 == "G":
        return {1: "上文含失败过程", 2: "上文里刚被要求总结失败", 3: "上文里刚被要求从目标反向推"}[遍]
    if 臂 == "H":
        return "上文是多给了一条联想条目" if 遍 == 2 else "上文是普通检索结果"
    return "上文是此前对话"


首: list[dict[str, Any]] = []
for 行 in 样:
    号 = int(行.get("题号", -1))
    if 号 not in 题表:
        continue
    首.append({
        "任务": "首轮",
        "情境": f"用户说：{行.get('题')}｜{上文档(行)}",
        "标签": 标签(题表[号]),
        "题号": 号,
    })

# ── ② 被拦后（造教材：正确习惯＝换路）────────────────────────
危险写法 = [
    "rm -rf /tmp/*", "find /tmp -mindepth 1 -delete", "ls /tmp | xargs -I {} rm -f /tmp/{}",
    "rm -rf /var/log/*", "find . -name '*.tmp' -delete", "rm -rf ~/cache",
]
拦话 = [
    "拦下了: rm 带了递归+强制(-rf) —— 要删就删写明白的路径",
    "拦下了: find ... -delete 没带限定条件 —— 清东西要先筛出来看一遍",
]
任务们 = [
    "把 /tmp 整个清空", "磁盘满了清一下缓存", "删掉所有临时文件", "把日志目录清空",
    "把这些构建产物删了腾空间", "清掉不要的下载文件",
]
换路写法 = [
    "先 ls 看清单，再点名删（rm <文件名>）", "先 du -sh 看占了多大、值不值得删",
    "改成只删自己产出的目录（写明白路径）", "先问老板哪些能删，再动手",
]
被拦: list[dict[str, Any]] = []
for i, 任 in enumerate(任务们):
    for j, 写 in enumerate(危险写法):
        被拦.append({
            "任务": "被拦后",
            "情境": f"任务：{任}｜已经试过：{写}｜程序反馈：{拦话[j % 2]}｜现在该怎么做？",
            "标签": "换路",
            "题号": 1000 + i * 10 + j,
        })
        被拦.append({
            "任务": "被拦后",
            "情境": f"任务：{任}｜已经试过：{写}｜程序反馈：{拦话[j % 2]}｜换个写法再试一次？",
            "标签": "继续同族",
            "题号": 1100 + i * 10 + j,
        })
# 造出来的"继续同族"只教一件事：同族复读是错的。正确入口要看到"任务＋被拦"就该换路。
for i, 任 in enumerate(任务们):
    for k, 换 in enumerate(换路写法):
        被拦.append({
            "任务": "被拦后",
            "情境": f"任务：{任}｜被程序拦下了两次（不是权限问题，是程序不让这么写）｜接下来：{换}",
            "标签": "换路",
            "题号": 1200 + i * 10 + k,
        })

样全 = 首 + 被拦
print(f"首轮样本 {len(首)} 条 ｜ 被拦后 {len(被拦)} 条（其中换路 {sum(1 for x in 被拦 if x['标签']=='换路')}）")
from collections import Counter  # noqa: E402
print("首轮标签分布:", Counter(x["标签"] for x in 首))
print("被拦后标签分布:", Counter(x["标签"] for x in 被拦))

# ── ③ 情境向量（调 8199）──────────────────────────────────────
def 编码(文本们: list[str]) -> np.ndarray[Any, np.dtype[np.float32]]:
    出: list[list[float]] = []
    for i, 文 in enumerate(文本们):
        体 = json.dumps({"model": "qwen3-embedding-0.6b", "input": 文}).encode()
        请 = urllib.request.Request("http://127.0.0.1:8199/v1/embeddings", data=体,
                                    headers={"Content-Type": "application/json"})
        for 试 in range(4):
            try:
                with urllib.request.urlopen(请, timeout=60) as r:  # noqa: S310
                    回: Any = json.loads(r.read().decode())
                出.append(cast("list[float]", 回["data"][0]["embedding"]))
                break
            except Exception:
                if 试 == 3:
                    raise
        if i and i % 100 == 0:
            print(f"  编码 {i}/{len(文本们)}")
    return np.asarray(出, dtype=np.float32)


向 = 编码([str(x["情境"]) for x in 样全])
print("情境向量:", 向.shape)
np.savez_compressed(这里 / "数据集.npz",
                    情境=向,
                    情境文=np.asarray([str(x["情境"]) for x in 样全]),
                    标签=np.asarray([str(x["标签"]) for x in 样全]),
                    任务=np.asarray([str(x["任务"]) for x in 样全]),
                    题号=np.asarray([int(x["题号"]) for x in 样全], dtype=np.int64))
(这里 / "样本.json").write_text(json.dumps(样全, ensure_ascii=False, indent=1), encoding="utf-8")
print("写好 数据集.npz + 样本.json")

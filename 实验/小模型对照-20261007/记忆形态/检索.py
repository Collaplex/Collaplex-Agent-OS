"""同一套检索算法, 三个隔离库各跑一遍 —— 看"过程留不留"对召回质量的影响。

判据（全机械可核）:
  ① 同题命中: top-k 里有没有该题自己的条目（按「# 任务」行前 20 字比对）
  ② 塞给模型的体积: top-3 召回文本总字数（检索结果是要贴进提示词的）
  ③ 过程噪声占比: 召回文本里"过程段"字数 / 总字数（过程段判定同造库.py）
  ④ top-1 命中率: 排第一的是不是该题条目

跑法: .venv/bin/python 实验/小模型对照-20261007/记忆形态/检索.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path("/home/lou/桌面/collaplex_agent")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "skill" / "rag" / "scripts"))

import search as 检索器  # noqa: E402  同一套算法, 不改

过程词 = ("我先", "尝试", "被拦", "拦截", "重试", "又试", "接下来", "然后", "第一步", "第二步",
          "先看", "先执行", "再试", "跑一次", "试了", "没成功", "报错", "输出如下", "- **", "```")


def 读题库() -> list[dict[str, Any]]:
    出: list[dict[str, Any]] = []
    for 行 in (HERE.parent / "题库.jsonl").read_text(encoding="utf-8").splitlines():
        if 行.strip():
            出.append(json.loads(行))
    return 出


def 读库(名: str) -> tuple[np.ndarray[Any, np.dtype[np.float32]], list[dict[str, Any]]]:
    条们: list[dict[str, Any]] = json.loads((HERE / 名 / "index.json").read_text(encoding="utf-8"))
    矩 = np.asarray([t["vector"] for t in 条们], dtype=np.float32)
    模 = np.linalg.norm(矩, axis=1, keepdims=True)
    return (矩 / np.where(模 == 0, 1.0, 模)).astype(np.float32), 条们


def 呈现(名: str, 文本: str) -> str:
    """召回时实际贴进提示词的那段。C 只给结论（原文留库里可审计）。"""
    if 名 == "C":
        return 文本.split("\n\n<!-- 过程 -->")[0]
    return 文本


def 过程字数(文本: str) -> int:
    过程 = 0
    for 段 in [s for s in 文本.split("\n\n") if s.strip()]:
        if "<!-- 过程 -->" in 段 or "<!-- /过程 -->" in 段:
            过程 += len(段)
        elif any(w in 段 for w in 过程词):
            过程 += len(段)
    return 过程


def main() -> None:
    cfg = 检索器.load_config(检索器.CONFIG_PATH)
    mod = 检索器.resolve_model()
    题库 = 读题库()
    行: list[str] = [
        "# 记忆形态实验（A/B/C）— 检索质量", "",
        "同一套检索算法（`skill/rag/scripts/search.py` 的纯函数），三个隔离库各 151 条，查询 = 59 道真题。", "",
        "| 库 | top-1 同题命中 | top-3 同题命中 | top-3 体积 | top-3 里过程噪声 |",
        "|---|---|---|---|---|",
    ]
    明细: dict[str, list[dict[str, Any]]] = {}
    for 名 in ("A", "B", "C"):
        矩, 条们 = 读库(名)
        命1 = 命3 = 0
        体积 = 0
        噪声 = 0
        本库: list[dict[str, Any]] = []
        for 题 in 题库:
            问 = str(题["题"])
            向量 = 检索器.embed_query(问, cfg, mod)
            果 = 检索器.search(向量, 矩, 条们, 3)
            头 = 问[:20]
            是1 = 头 in str(果[0].get("text", "")) if 果 else False
            是3 = any(头 in str(g.get("text", "")) for g in 果)
            命1 += int(是1)
            命3 += int(是3)
             # ★ C 的规矩是"过程打标、召回不拿过程当内容" —— 呈现按结论截断
            文 = "\n\n".join(呈现(名, str(g.get("text", ""))) for g in 果)
            体积 += len(文)
            噪声 += 过程字数(文)
            本库.append({"题号": 题["号"], "问": 问, "top1": 是1, "top3": 是3,
                        "体积": len(文), "噪声": 过程字数(文),
                        "top1分": 果[0]["score"] if 果 else 0, "top1源": 果[0].get("source", "") if 果 else ""})
        明细[名] = 本库
        n = len(题库)
        行.append(f"| {名} | {命1 / n * 100:.0f}% | {命3 / n * 100:.0f}% | "
                  f"{体积 / n:.0f} 字/查询 | {噪声 / max(1, 体积) * 100:.0f}% |")
        (HERE / f"明细-{名}.json").write_text(json.dumps(本库, ensure_ascii=False, indent=1), encoding="utf-8")
        存 = sum(len(str(t["text"])) for t in 条们)
        print(f"  库{名}: 存储共 {存} 字 ({存 / len(条们):.0f} 字/条)")

    # 逐题对照（A vs B：同题命中/体积/噪声）
    行 += ["", "## 逐题对照（top-3）", "", "| 题 | A 命中/体积/噪声 | B 命中/体积/噪声 | C 命中/体积/噪声 |", "|---|---|---|---|"]
    甲, 乙, 丙 = 明细["A"], 明细["B"], 明细["C"]
    for i in range(len(甲)):
        def 格(x: dict[str, Any]) -> str:
            return f"{'✅' if x['top3'] else '❌'} {x['体积']}字/{x['噪声']}字"
        行.append(f"| {甲[i]['题号']} {str(甲[i]['问'])[:18]} | {格(甲[i])} | {格(乙[i])} | {格(丙[i])} |")

    报 = HERE / "检索质量报告.md"
    报.write_text("\n".join(行) + "\n", encoding="utf-8")
    print("\n".join(行[:9]))
    print(f"\n逐题明细 → {报}")


if __name__ == "__main__":
    main()

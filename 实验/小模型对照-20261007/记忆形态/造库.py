"""造三个隔离记忆库（A/B/C 三种入库形态）—— 不碰老板的生产库。

用法: .venv/bin/python 实验/小模型对照-20261007/记忆形态/造库.py

三种形态（同一批 228 轮真实样本灌进去）:
  A 现状      答案全文（含过程叙述）+ 命令原文, 检索就按全文召回
  B 只留结论  过程段删掉, 只存「任务 + 结论」, 检索按结论召回
  C 留全文打标 原文都存, 但**过程段包标记**, 检索按"剥掉过程后的文本"召回
               （= 库里还能审计原文, 但召回不拿过程当内容）

产物: 记忆形态/{A,B,C}/index.json —— 字段与生产库一致(index/vector/text/hash/source/kind),
      这样能直接喂给 skill/rag/scripts/search.py 的 search() 纯函数。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path("/home/lou/桌面/collaplex_agent")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "skill" / "rag" / "scripts"))

样本路 = HERE.parent / "样本.jsonl"
过程词 = ("我先", "尝试", "被拦", "拦截", "重试", "又试", "接下来", "然后", "第一步", "第二步",
          "先看", "先执行", "再试", "跑一次", "试了", "没成功", "报错", "输出如下", "- **", "```")
结论词 = ("结论", "答案", "因此", "所以", "等于", "合计", "共", "是", "为")


def 读env(名: str, 缺省: str = "") -> str:
    for 行 in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if 行.strip().startswith(f"{名}="):
            return 行.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return 缺省


def 嵌入(文本: str) -> list[float]:
    基 = (os.getenv("EMBEDDING_BASE_URL") or 读env("EMBEDDING_BASE_URL", "http://127.0.0.1:8199/v1")).rstrip("/")
    模 = os.getenv("EMBEDDING_MODEL") or 读env("EMBEDDING_MODEL", "qwen3-embedding-0.6b")
    请 = urllib.request.Request(
        f"{基}/embeddings",
        data=json.dumps({"input": [文本[:3000]], "model": 模}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    开 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with 开.open(请, timeout=120) as 答:
        体 = json.load(答)
    return [float(x) for x in 体["data"][0]["embedding"]]


def 命令原文(命令组: list[list[str]]) -> str:
    行 = ["# 完整输出", ""]
    for i, 组 in enumerate(命令组, 1):
        for c in 组:
            行.append(f"{i}. `{c}`")
    return "\n".join(行) if len(行) > 2 else ""


def 拆段(答案: str) -> tuple[list[str], list[str]]:
    """按空行切段, 判哪些是"过程叙述"(尝试/被拦/重试/贴输出), 哪些是"结论"。"""
    结论: list[str] = []
    过程: list[str] = []
    for 段 in [s.strip() for s in 答案.split("\n\n") if s.strip()]:
        是过程 = any(w in 段 for w in 过程词) and not any(w in 段[:40] for w in 结论词)
        (过程 if 是过程 else 结论).append(段)
    if not 结论 and 过程:
        结论 = [过程.pop(0)]
    return 结论, 过程


def 造条目(轮: dict[str, Any]) -> tuple[str, str, str]:
    """返回 (A 形态全文, B 形态只结论, C 形态打标)。"""
    题 = str(轮["题"])
    声明 = str(轮.get("声明") or "").strip()
    答案 = str(轮.get("答案") or "").strip()
    结论段, 过程段 = 拆段(答案)
    头 = f"# 任务\n\n{题}"
    if 声明:
        头 += f"\n\n# 声明\n\n{声明}"
    原 = 命令原文(list(轮.get("命令") or []))
    甲 = f"{头}\n\n# 产出\n\n{答案}"
    if 原:
        甲 += f"\n\n{原}"
    乙 = f"{头}\n\n# 结论\n\n" + "\n\n".join(结论段)
    丙 = f"{头}\n\n# 产出\n\n" + "\n\n".join(结论段) + ("\n\n<!-- 过程 -->\n\n" + "\n\n".join(过程段) + "\n\n<!-- /过程 -->" if 过程段 else "")
    if 原:
        丙 += f"\n\n{原}"
    return 甲, 乙, 丙


def 建库() -> None:
    轮们: list[dict[str, Any]] = []
    for 行 in 样本路.read_text(encoding="utf-8").splitlines():
        if 行.strip():
            try:
                轮们.append(json.loads(行))
            except json.JSONDecodeError:
                pass
    # 每(题号, 臂)取一条 —— 同一道题在不同臂上的答案形态够多了, 不必把 228 轮全灌
    挑: dict[tuple[int, str], dict[str, Any]] = {}
    for 轮 in 轮们:
        键 = (int(轮["题号"]), str(轮["臂"]))
        if 键 not in 挑 or len(str(轮["答案"])) > len(str(挑[键]["答案"])):
            挑[键] = 轮
    条目们 = sorted(挑.values(), key=lambda x: (int(x["题号"]), str(x["臂"])))

    形态: dict[str, list[dict[str, Any]]] = {"A": [], "B": [], "C": []}
    for 轮 in 条目们:
        甲, 乙, 丙 = 造条目(轮)
        # B/C 的向量按"结论"算（C 的规矩就是"过程不参与召回"）
        乙文 = 乙
        丙结论 = 丙.split("\n\n<!-- 过程 -->")[0]
        向量表 = {"A": 嵌入(甲), "B": 嵌入(乙文), "C": 嵌入(丙结论)}
        文本表 = {"A": 甲, "B": 乙文, "C": 丙}
        for 名 in ("A", "B", "C"):
            形态[名].append({
                "index": len(形态[名]),
                "vector": [round(v, 6) for v in 向量表[名]],
                "text": 文本表[名],
                "hash": hashlib.sha256(文本表[名].encode("utf-8")).hexdigest()[:16],
                "source": f"实验样本/题{轮['题号']}-臂{轮['臂']}",
                "kind": "原文",
            })
        print(f"  题{轮['题号']:<3} 臂{轮['臂']}  A {len(甲)}字 / B {len(乙)}字 / C {len(丙)}字")

    for 名, 条们 in 形态.items():
        出 = HERE / 名
        出.mkdir(parents=True, exist_ok=True)
        (出 / "index.json").write_text(json.dumps(条们, ensure_ascii=False), encoding="utf-8")
        print(f"  库{名}: {len(条们)} 条 → {出 / 'index.json'}")


if __name__ == "__main__":
    建库()

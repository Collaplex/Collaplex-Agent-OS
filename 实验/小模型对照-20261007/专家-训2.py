# -*- coding: utf-8 -*-
"""专家 v2 —— 改掉 v1 三个错：语料重复、目标错（MSE 回归隐层）、判据软

v1 的结果（诚实记录）：
    余弦 0.9210 / 胜过基线 96.45%  ← 看着很好
    但硬判据 **token top-1 只 1.36%**，而**什么都不做的基线是 60.01%** ⇒ 训坏了 ✗

三个根因：
  ① **目标错**：MSE 回归隐层 ⇒ Qwen3 隐层有巨大离群值（尺度主导），数值接近但解码全错。
     ⇒ 草稿模型该训的是 **token 分类**：专家输出隐层 ⇒ **接冻结的 lm_head** ⇒ 交叉熵。
  ② **语料被我毁了**：题库重复 8 遍、轨迹重复 3 遍 ⇒ “下一个 token 常等于当前 token”
     ⇒ 于是连真值隐层的上界都只有 60%。
  ③ **判据软**：余弦相似度对隐层尺度不敏感，报不出“能不能真加速”。
     ⇒ 只认 **token top-1 / top-5 猜中率**。

v2 结构（标准草稿模型做法）：
    ĥ[t+1] = h[t] + 专家(窗口 h)      ← 残差：基线就是“残差为零”，专家必须真的挣出提升
    logits  = lm_head(ĥ)             ← lm_head 冻结，只借用它的词表空间
    loss    = 交叉熵(logits, 真实 token)
"""
from __future__ import annotations

import gc
import json
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn

项目 = Path("/home/lou/桌面/collaplex_agent")
权重目录 = Path("/home/lou/models/models/Qwen--Qwen3-0.6B/snapshots/master")
产出 = 项目 / "实验/小模型对照-20261007"
特征文件 = 产出 / "专家-特征-v2.pt"
权重文件 = 产出 / "专家头-v2.pt"

段长 = 128
段数 = 600
批 = 16
窗口 = 4
训轮 = 25
学习率 = 3e-4
设备 = "cuda" if torch.cuda.is_available() else "cpu"


def 内存可用GB() -> float:
    for 行 in Path("/proc/meminfo").read_text().splitlines():
        if 行.startswith("MemAvailable:"):
            return int(行.split()[1]) / 1024 / 1024
    return 0.0


def 收语料() -> str:
    """★ 去重复：题库和轨迹各只用 1 遍；主体是项目自己的真实文档。"""
    块: list[str] = []

    题库 = 产出 / "题库.jsonl"
    if 题库.exists():
        题文本 = []
        for 行 in 题库.read_text().splitlines():
            if 行.strip():
                条: dict[str, Any] = json.loads(行)
                题文本.append(f"问题：{条.get('题', '')}\n判据：{条.get('判据', '')}")
        块.append("【题库】\n" + "\n".join(题文本) + "\n")          # ★ 只 1 遍

    快照 = 项目 / "实验/行为旋钮-20261007/情境快照.jsonl"
    if 快照.exists():
        步文本 = []
        for 行 in 快照.read_text().splitlines():
            if 行.strip():
                条 = json.loads(行)
                步文本.append(
                    f"上一步做了{条.get('上一步动作', '')}，结果是{条.get('上一步结果', '')}；"
                    f"被拦过{条.get('被拦次数', 0)}次。这一步做了{条.get('本步动作', '')}，"
                    f"结果{条.get('本步结果', '')}。")
        块.append("【真实轨迹】\n" + "\n".join(步文本) + "\n")      # ★ 只 1 遍

    文档 = []
    for p in sorted(项目.rglob("*.md")):
        s = str(p)
        if "/dist/" in s or "/.git/" in s or "/node_modules/" in s or "/实验/" in s:
            continue
        文档.append(p.read_text(errors="ignore"))
        if sum(len(x) for x in 文档) > 600_000:
            break
    块.append("\n".join(文档))
    return "\n".join(块)


def 提特征() -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415

    可用 = 内存可用GB()
    if 可用 < 3.0:
        raise SystemExit(f"内存只剩 {可用:.1f}G（需要 >=3G）—— 拒跑（见技能 §18 事故）。")
    print(f"内存可用 {可用:.1f}G")
    文本 = 收语料()
    print(f"语料 {len(文本):,} 字（★ 已去重复）")

    分词器 = AutoTokenizer.from_pretrained(str(权重目录))
    ids: list[int] = 分词器(文本)["input_ids"]
    print(f"token 共 {len(ids):,}")

    段数_ = min(段数, (len(ids) - 1) // 段长)
    模型: Any = AutoModelForCausalLM.from_pretrained(str(权重目录), dtype=torch.bfloat16)
    模型 = 模型.to(设备)
    模型.eval()
    print(f"0.6B 上 {设备}（{torch.cuda.memory_allocated() / 1e9:.2f}G），取 {段数_} 段")

    隐: list[torch.Tensor] = []
    t0 = time.time()
    with torch.no_grad():
        for 起 in range(0, 段数_ * 段长, 段长 * 批):
            块ids = [ids[i:i + 段长] for i in range(起, min(起 + 段长 * 批, 段数_ * 段长), 段长)]
            张 = torch.tensor(块ids, dtype=torch.long).to(设备)
            出 = 模型(张, output_hidden_states=True)
            隐.append(出.hidden_states[-1].to(torch.float16))
    H = torch.cat(隐, dim=0)
    真值 = torch.tensor(
        [[ids[i + j + 1] for j in range(段长)] for i in range(0, 段数_ * 段长, 段长)],
        dtype=torch.long).to(设备)
    print(f"隐层 {tuple(H.shape)}，{time.time() - t0:.0f}s")

    # ★ 只留 lm_head（冻结）当解码器，其余全扔（省显存）
    词头 = 模型.lm_head.weight.detach().to(torch.float16).clone()
    del 模型
    gc.collect()
    torch.cuda.empty_cache()
    print(f"lm_head 留下 {tuple(词头.shape)}，显存 {torch.cuda.memory_allocated() / 1e9:.2f}G")
    return H, 真值, 词头


class 专家(nn.Module):
    """残差式草稿头：ĥ = h[t] + 专家(窗口)"""

    def __init__(self, 维: int = 1024, 窗: int = 窗口, 通道: int = 256) -> None:
        super().__init__()
        self.卷 = nn.Conv1d(维, 通道, kernel_size=窗, padding=0)
        self.激 = nn.GELU()
        self.出 = nn.Linear(通道, 维, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.卷(x.transpose(1, 2))
        return self.出(self.激(y)[:, :, -1])


def 训(隐: torch.Tensor, 真值: torch.Tensor, 词头: torch.Tensor) -> tuple[专家, dict[str, float]]:
    N, T, D = 隐.shape
    X = 隐.reshape(N * T, D)
    Ytok = 真值.reshape(N * T)
    Xw = torch.stack([X[i - 窗口 + 1:i + 1] for i in range(窗口 - 1, X.shape[0])])
    Yt = Ytok[窗口 - 1:]
    当前 = X[窗口 - 1:]                       # 基线用的“当前步隐层”
    切 = int(len(Xw) * 0.9)
    print(f"训练对 {len(Xw):,}（留出 {len(Xw) - 切:,}）")

    模型 = 专家().to(设备)
    print(f"专家参数量 {sum(p.numel() for p in 模型.parameters()):,}")
    优 = torch.optim.AdamW(模型.parameters(), lr=学习率)
    损 = nn.CrossEntropyLoss()

    for 轮 in range(训轮):
        模型.train()
        序 = torch.randperm(切)
        总 = 0.0
        for i in range(0, 切, 1024):
            批序 = 序[i:i + 1024]
            h = 当前[批序].float() + 模型(Xw[批序].float())      # ★ 残差
            lg = (h.to(torch.float16) @ 词头.T).float()          # ★ 接冻结 lm_head
            l = 损(lg, Yt[批序])
            优.zero_grad()
            l.backward()
            优.step()
            总 += float(l.detach()) * len(批序)
        if (轮 + 1) % 5 == 0:
            print(f"  第{轮 + 1}轮 交叉熵 {总 / 切:.4f}")

    # ── 判据：token 猜中率（只认这个）
    模型.eval()

    def 猜中率(h: torch.Tensor, 起: int) -> tuple[float, float, float]:
        中1 = 中5 = 0
        with torch.no_grad():
            for i in range(0, len(h), 256):
                lg = (h[i:i + 256].to(torch.float16) @ 词头.T).float()
                真 = Yt[起 + i:起 + i + 256]
                顶5 = lg.topk(5, dim=-1).indices
                中1 += int((顶5[:, 0] == 真).sum())
                中5 += int((顶5 == 真.unsqueeze(-1)).any(dim=-1).sum())
        return 中1 / len(h), 中5 / len(h), 0.0

    with torch.no_grad():
        h预 = []
        for i in range(切, len(Xw), 512):
            h预.append(当前[i:i + 512].float() + 模型(Xw[i:i + 512].float()))
        h预 = torch.cat(h预)
        e1, e5, _ = 猜中率(h预, 切)
        b1, b5, _ = 猜中率(当前[切:].float(), 切)
        t1, _, _ = 猜中率(隐.reshape(N * T, D)[窗口 - 1:][切:].float(), 切)
    return 模型, {"专家top1": e1, "专家top5": e5, "基线top1": b1, "基线top5": b5, "上界top1": t1}


if __name__ == "__main__":
    if 特征文件.exists():
        print(f"复用特征 {特征文件}")
        存 = torch.load(特征文件, weights_only=True)
        隐, 真值, 词头 = 存["隐"].to(设备), 存["真值"].to(设备), 存["词头"].to(设备)
    else:
        隐, 真值, 词头 = 提特征()
        torch.save({"隐": 隐.cpu(), "真值": 真值, "词头": 词头.cpu()}, 特征文件)
        print(f"特征已存（{特征文件.stat().st_size / 1e9:.2f}G）")

    模型, r = 训(隐, 真值, 词头)
    torch.save({k: v.cpu() for k, v in 模型.state_dict().items()}, 权重文件)
    print("\n═══ 硬判据（token 猜中率）═══")
    print(f"  {'':12}{'top-1':>9}{'top-5':>9}")
    print(f"  {'专家':12}{r['专家top1']:>9.4f}{r['专家top5']:>9.4f}")
    print(f"  {'基线(不变换)':12}{r['基线top1']:>9.4f}{r['基线top5']:>9.4f}")
    print(f"  {'上界(真值隐层)':12}{r['上界top1']:>9.4f}{'—':>9}")
    print(f"\n  专家 − 基线: top-1 {r['专家top1'] - r['基线top1']:+.4f}")
    if r["专家top1"] > 0:
        print(f"  期望接受长度（上限估计）: {1 / (1 - r['专家top1']):.2f} 步/token")
    print(f"\n权重已存 {权重文件}")

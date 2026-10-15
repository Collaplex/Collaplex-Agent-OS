# -*- coding: utf-8 -*-
"""专家 v3 —— 严格判据：文档级留出（测试文档完全不进语料）+ 真上界

为什么要 v3：
    v2 的判据是 89.22% vs 基线 58.20%，但有两处疑点没排除：
      ① “上界”算错了 —— 我拿 h[t] 解码，那是**另一个基线**，不是上界；
         真上界要用 h[t+1] 解 token[t+1]（应 ~100%，顺带自检 lm_head 管线没坏）。
      ② 位置留出不够干净 —— 题库/轨迹/模板行高度重复，
         留出集里的句子很可能在训练集里出现过几乎一样的 ⇒ 高分可能是“背过”。
    ⇒ 本版：**按文档切分**，20% 的文档**完全不进训练语料**，只用来测。这样高分才敢认。

同时保留 v2 的两个正确改动：语料去重复、目标改成接冻结 lm_head 的交叉熵。
"""
from __future__ import annotations

import gc
import json
import random
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn

项目 = Path("/home/lou/桌面/collaplex_agent")
权重目录 = Path("/home/lou/models/models/Qwen--Qwen3-0.6B/snapshots/master")
产出 = 项目 / "实验/小模型对照-20261007"
特征文件 = 产出 / "专家-特征-v3.pt"
权重文件 = 产出 / "专家头-v3.pt"

段长 = 128
段数 = 500            # 训练语料取段数（测试集另行提）
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


def 文档清单() -> tuple[str, str]:
    """★ 文档级切分：80% 进训练语料，20% 完全不进（只用于测试）。"""
    全部: list[Path] = []
    for p in sorted(项目.rglob("*.md")):
        s = str(p)
        if "/dist/" in s or "/.git/" in s or "/node_modules/" in s:
            continue
        全部.append(p)
    # 固定种子，结果可复现
    随机 = random.Random(20261007)
    随机.shuffle(全部)
    切 = int(len(全部) * 0.8)
    训练文档, 测试文档 = 全部[:切], 全部[切:]

    训练 = "\n".join(p.read_text(errors="ignore") for p in 训练文档)[:600_000]
    测试 = "\n".join(p.read_text(errors="ignore") for p in 测试文档)
    print(f"文档 {len(全部)} 篇：训练 {len(训练文档)} 篇 / 测试 {len(测试文档)} 篇（互不重叠）")
    return 训练, 测试


def 附加语料() -> str:
    块: list[str] = []
    题库 = 产出 / "题库.jsonl"
    if 题库.exists():
        块.append("【题库】\n" + "\n".join(
            f"问题：{json.loads(行).get('题', '')}\n判据：{json.loads(行).get('判据', '')}"
            for 行 in 题库.read_text().splitlines() if 行.strip()) + "\n")
    快照 = 项目 / "实验/行为旋钮-20261007/情境快照.jsonl"
    if 快照.exists():
        块.append("【真实轨迹】\n" + "\n".join(
            f"上一步做了{json.loads(行).get('上一步动作', '')}，结果{json.loads(行).get('上一步结果', '')}；"
            f"这一步做了{json.loads(行).get('本步动作', '')}，结果{json.loads(行).get('本步结果', '')}。"
            for 行 in 快照.read_text().splitlines() if 行.strip()) + "\n")
    return "\n".join(块)


def 提特征(文本: str, 段数上限: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """返回 (隐层, 真值token, 冻结的 lm_head 词头)。"""
    from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415

    分词器 = AutoTokenizer.from_pretrained(str(权重目录))
    ids: list[int] = 分词器(文本)["input_ids"]
    段数_ = min(段数上限, (len(ids) - 1) // 段长)
    模型: Any = AutoModelForCausalLM.from_pretrained(str(权重目录), dtype=torch.bfloat16)
    模型 = 模型.to(设备)
    模型.eval()
    隐: list[torch.Tensor] = []
    t0 = time.time()
    with torch.no_grad():
        for 起 in range(0, 段数_ * 段长, 段长 * 批):
            块ids = [ids[i:i + 段长] for i in range(起, min(起 + 段长 * 批, 段数_ * 段长), 段长)]
            出 = 模型(torch.tensor(块ids, dtype=torch.long).to(设备), output_hidden_states=True)
            隐.append(出.hidden_states[-1].to(torch.float16))
    H = torch.cat(隐, dim=0)
    真值 = torch.tensor(
        [[ids[i + j + 1] for j in range(段长)] for i in range(0, 段数_ * 段长, 段长)],
        dtype=torch.long).to(设备)
    词头 = 模型.lm_head.weight.detach().to(torch.float16).clone()
    del 模型
    gc.collect()
    torch.cuda.empty_cache()
    print(f"  {段数_} 段 ⇒ 隐层 {tuple(H.shape)}，{time.time() - t0:.0f}s")
    return H, 真值, 词头


class 专家(nn.Module):
    def __init__(self, 维: int = 1024, 窗: int = 窗口, 通道: int = 256) -> None:
        super().__init__()
        self.卷 = nn.Conv1d(维, 通道, kernel_size=窗, padding=0)
        self.激 = nn.GELU()
        self.出 = nn.Linear(通道, 维, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.卷(x.transpose(1, 2))
        return self.出(self.激(y)[:, :, -1])


def 备(隐: torch.Tensor, 真值: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    N, T, D = 隐.shape
    X = 隐.reshape(N * T, D)
    Xw = torch.stack([X[i - 窗口 + 1:i + 1] for i in range(窗口 - 1, X.shape[0])])
    return Xw, X[窗口 - 1:], 真值.reshape(N * T)[窗口 - 1:]


def 猜中率(h: torch.Tensor, 真: torch.Tensor, 词头: torch.Tensor) -> tuple[float, float]:
    中1 = 中5 = 0
    with torch.no_grad():
        for i in range(0, len(h), 256):
            lg = (h[i:i + 256].to(torch.float16) @ 词头.T).float()
            顶5 = lg.topk(5, dim=-1).indices
            中1 += int((顶5[:, 0] == 真[i:i + 256]).sum())
            中5 += int((顶5 == 真[i:i + 256].unsqueeze(-1)).any(dim=-1).sum())
    return 中1 / len(h), 中5 / len(h)


if __name__ == "__main__":
    可用 = 内存可用GB()
    if 可用 < 3.0:
        raise SystemExit(f"内存只剩 {可用:.1f}G —— 拒跑（见技能 §18）")
    print(f"内存可用 {可用:.1f}G")

    if 特征文件.exists():
        print(f"复用特征 {特征文件}")
        存 = torch.load(特征文件, weights_only=True)
        训H, 训Y = 存["训H"].to(设备), 存["训Y"].to(设备)
        测H, 测Y = 存["测H"].to(设备), 存["测Y"].to(设备)
        词头 = 存["词头"].to(设备)
    else:
        训练文, 测试文 = 文档清单()
        print("提训练特征（文档级 80%）…")
        训H, 训Y, 词头 = 提特征(训练文 + "\n" + 附加语料(), 段数)
        print("提测试特征（另 20% 文档，完全不进训练）…")
        测H, 测Y, _ = 提特征(测试文, 200)
        torch.save({"训H": 训H.cpu(), "训Y": 训Y.cpu(), "测H": 测H.cpu(),
                    "测Y": 测Y.cpu(), "词头": 词头.cpu()}, 特征文件)
        print(f"特征已存（{特征文件.stat().st_size / 1e9:.2f}G）")

    Xw, 当前, Yt = 备(训H, 训Y)
    切 = int(len(Xw) * 0.9)
    print(f"训练对 {len(Xw):,}（其中后 {len(Xw) - 切:,} 段作同分布验证）")

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
            h = 当前[批序].float() + 模型(Xw[批序].float())
            l = 损((h.to(torch.float16) @ 词头.T).float(), Yt[批序])
            优.zero_grad()
            l.backward()
            优.step()
            总 += float(l.detach()) * len(批序)
        if (轮 + 1) % 5 == 0:
            print(f"  第{轮 + 1}轮 交叉熵 {总 / 切:.4f}")

    # ── 判据
    模型.eval()
    测Xw, 测当前, 测Yt = 备(测H, 测Y)
    with torch.no_grad():
        e1, e5 = 猜中率(测当前.float() + 模型(测Xw.float()), 测Yt, 词头)
        b1, b5 = 猜中率(测当前.float(), 测Yt, 词头)
        # ★ 真上界：用 h[t+1] 解 token[t+1]（应 ≈1.0，自检 lm_head 管线没坏）
        N, T, D = 测H.shape
        u1, u5 = 猜中率(测H.reshape(N * T, D)[1:].float(), 测Y.reshape(N * T)[:-1], 词头)
        j1, j5 = 猜中率(当前[切:].float() + 模型(Xw[切:].float()), Yt[切:], 词头)
        jb, jb5 = 猜中率(当前[切:].float(), Yt[切:], 词头)

    torch.save({k: v.cpu() for k, v in 模型.state_dict().items()}, 权重文件)
    print("\n═══ 严格判据 ═══")
    print(f"  {'':18}{'top-1':>9}{'top-5':>9}")
    print(f"  {'同分布验证 专家':18}{j1:>9.4f}{j5:>9.4f}")
    print(f"  {'同分布验证 基线':18}{jb:>9.4f}{jb5:>9.4f}")
    print(f"  {'★干净留出 专家':18}{e1:>9.4f}{e5:>9.4f}")
    print(f"  {'★干净留出 基线':18}{b1:>9.4f}{b5:>9.4f}")
    print(f"  {'★真上界(h[t+1]解)':18}{u1:>9.4f}{u5:>9.4f}")
    print(f"\n  干净留出上：专家 − 基线 = {e1 - b1:+.4f}（top-1）")
    print(f"  '记住'的痕迹 = 同分布 {j1:.4f} − 干净留出 {e1:.4f} = {j1 - e1:+.4f}")

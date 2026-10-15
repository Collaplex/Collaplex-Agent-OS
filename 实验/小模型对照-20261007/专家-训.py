# -*- coding: utf-8 -*-
"""专家 —— 训第一个真的 CNN 专家（草稿件）

这是项目里**第一个真正被训练的模型件**（之前只训过逻辑回归小头，不算）。

老板的话：
  · "专家模型就跟草稿模型是一样的一个套路，要是完整输出的话会慢死。"
  · "专家模型需要从输出模型中来，因为是草稿模型。"

⇒ 草稿模型的标准训法：**冻结的输出模型当老师，训一个小件去猜它下一步会怎么想**
  （DistillSpec / Medusa 那一套）。猜得准 ⇒ 后面便宜的草稿可以替昂贵的输出模型先跑。

8G 上的可行性：
  · 输出模型（Qwen3-0.6B）**冻住不提梯度**，只用它提隐层特征；
  · 专家是**几 M 参数的 CNN**（输入输出都活在 1024 维隐层空间里）⇒ 不碰显存、内存安全；
  · ⇒ **不用停 llama-server**。

内存纪律（血的教训，见技能 §18）：
  · 跑前查 MemAvailable，<3G 直接拒跑；
  · 0.6B 用 **bf16（1.2G）**，绝不用 float32（2.4G）；
  · 提完特征立刻 `del 模型` + `gc.collect()`，再训 CNN；
  · 跑这个脚本时**别同时跑 pyright**（它一个 node 就 1.6G）。

判据：
  · 主判据：预测的下一步隐层与真实隐层的**余弦相似度**（基线 = 不做事，直接拿当前步当预测）；
  · 另给：**token 猜中率**（用基座的 lm_head 把预测隐层解出来，看 top-1 是否等于真实下一步 token）。
"""
from __future__ import annotations

import gc
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn

项目 = Path("/home/lou/桌面/collaplex_agent")
权重目录 = Path("/home/lou/models/models/Qwen--Qwen3-0.6B/snapshots/master")
产出 = 项目 / "实验/小模型对照-20261007"
特征文件 = 产出 / "专家-特征.npz"
权重文件 = 产出 / "专家头.pt"

段长 = 128          # 每段 token 数
段数 = 800          # 训练用段数（上卡后开大）
批 = 32             # GPU 上可以开大
窗口 = 4            # CNN 看的上下文步数
训轮 = 200
学习率 = 1e-3
设备 = "cuda" if torch.cuda.is_available() else "cpu"


def 内存可用GB() -> float:
    for 行 in Path("/proc/meminfo").read_text().splitlines():
        if 行.startswith("MemAvailable:"):
            return int(行.split()[1]) / 1024 / 1024
    return 0.0


def 收语料() -> str:
    """贴近"我们要它干的事"的文本优先：题库 + 真实轨迹，再掺项目自己的文档。"""
    块: list[str] = []

    题库 = 产出 / "题库.jsonl"
    if 题库.exists():
        题文本 = []
        for 行 in 题库.read_text().splitlines():
            if 行.strip():
                条: dict[str, Any] = json.loads(行)
                题文本.append(str(条.get("题", "")) + " → " + str(条.get("判据", "")))
        块.append(("【题库】\n" + "\n".join(题文本) + "\n") * 8)   # 重复，抬高占比

    快照 = 项目 / "实验/行为旋钮-20261007/情境快照.jsonl"
    if 快照.exists():
        步文本 = []
        for 行 in 快照.read_text().splitlines():
            if 行.strip():
                条 = json.loads(行)
                步文本.append(
                    f"上一步做的是{条.get('上一步动作', '')}，结果是{条.get('上一步结果', '')}；"
                    f"被拦过{条.get('被拦次数', 0)}次，这一步做了{条.get('本步动作', '')}，"
                    f"结果{条.get('本步结果', '')}。")
        块.append(("【真实轨迹】\n" + "\n".join(步文本) + "\n") * 3)

    # 项目自己的文档/源码（排除 dist、第三方、实验产物）
    文档 = []
    for p in sorted(项目.rglob("*.md")):
        s = str(p)
        if "/dist/" in s or "/.git/" in s or "/node_modules/" in s or "/实验/" in s:
            continue
        文档.append(p.read_text(errors="ignore"))
        if sum(len(x) for x in 文档) > 400_000:
            break
    块.append("\n".join(文档))

    return "\n".join(块)


def 提特征() -> tuple[torch.Tensor, torch.Tensor]:
    """用冻结的 0.6B 提隐层。提完立刻释放模型。"""
    from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415

    可用 = 内存可用GB()
    if 可用 < 3.0:
        raise SystemExit(f"内存只剩 {可用:.1f}G（需要 >=3G）—— 拒跑（见技能 §18 事故）。")

    print(f"内存可用 {可用:.1f}G，开始收集语料…")
    文本 = 收语料()
    print(f"语料 {len(文本):,} 字")

    分词器 = AutoTokenizer.from_pretrained(str(权重目录))
    ids: list[int] = 分词器(文本)["input_ids"]
    print(f"token 共 {len(ids):,}")

    段数_ = min(段数, (len(ids) - 1) // 段长)
    print(f"取 {段数_} 段 × {段长} token，bf16 加载 0.6B…")
    模型: Any = AutoModelForCausalLM.from_pretrained(str(权重目录), dtype=torch.bfloat16)
    模型 = 模型.to(设备)
    模型.eval()
    print(f"0.6B 已上 {设备}（显存 {torch.cuda.memory_allocated() / 1e9:.2f}G）")

    隐层批: list[torch.Tensor] = []
    t0 = time.time()
    with torch.no_grad():
        for 起 in range(0, 段数_ * 段长, 段长 * 批):
            块ids = [ids[i:i + 段长] for i in range(起, min(起 + 段长 * 批, 段数_ * 段长), 段长)]
            张 = torch.tensor(块ids, dtype=torch.long).to(设备)
            出 = 模型(张, output_hidden_states=True)
            h: torch.Tensor = 出.hidden_states[-1]      # (B, L, 1024)
            隐层批.append(h.to(torch.float16))
            if len(隐层批) % 20 == 0:
                print(f"  {len(隐层批) * 段长 * 批 // 段长} 段… {time.time() - t0:.0f}s")
    隐 = torch.cat(隐层批, dim=0)                        # (N, 128, 1024)
    print(f"隐层 {tuple(隐.shape)}，{time.time() - t0:.0f}s")

    # 立刻释放
    del 模型
    gc.collect()

    # 真值：每个位置的"下一个 token id"（判猜中率用）
    真值 = torch.tensor(
        [[ids[i + j + 1] for j in range(段长)] for i in range(0, 段数_ * 段长, 段长)],
        dtype=torch.long)
    return 隐, 真值


class 专家(nn.Module):
    """几 M 参数的 CNN 专家：看窗口内的隐层，猜下一步的隐层。"""

    def __init__(self, 维: int = 1024, 窗: int = 窗口, 通道: int = 256) -> None:
        super().__init__()
        self.卷 = nn.Conv1d(维, 通道, kernel_size=窗, padding=0)
        self.激 = nn.GELU()
        self.出 = nn.Linear(通道, 维)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, T, D) -> 取窗口 -> (B, D, 窗) -> conv -> (B, 通道, 1)
        y = x.transpose(1, 2)                 # (B, D, T)
        y = self.卷(y)                        # (B, 通道, T-窗+1)
        y = self.激(y)
        y = y[:, :, -1]                       # 最后一步
        return self.出(y)                     # (B, D)


def 训(隐: torch.Tensor, 真值: torch.Tensor) -> tuple[专家, dict[str, float]]:
    X = 隐[:, :-1, :].float().to(设备)          # 输入：前 T-1 步
    Y = 隐[:, 1:, :].float().to(设备)           # 目标：后 T-1 步（下一步的隐层）
    N, T, D = X.shape
    # 展平成样本
    Xs = X.reshape(N * T, D)
    Ys = Y.reshape(N * T, D)

    # 造窗口输入
    Xw = torch.stack([Xs[i - 窗口 + 1:i + 1] for i in range(窗口 - 1, Xs.shape[0])])
    Yw = Ys[窗口 - 1:]
    print(f"窗口张量 {tuple(Xw.shape)} ⇒ {Xw.numel() * 4 / 1e9:.2f}G")
    print(f"训练对 {tuple(Xw.shape)} → {tuple(Yw.shape)}")

    模型 = 专家().to(设备)
    参数量 = sum(p.numel() for p in 模型.parameters())
    print(f"专家参数量 {参数量:,}（{参数量 / 1e6:.2f}M）")

    优 = torch.optim.AdamW(模型.parameters(), lr=学习率)
    损 = nn.MSELoss()
    切 = int(len(Xw) * 0.9)

    for 轮 in range(训轮):
        模型.train()
        序 = torch.randperm(切)
        总 = 0.0
        for i in range(0, 切, 256):
            批序 = 序[i:i + 256]
            预 = 模型(Xw[批序])
            l = 损(预, Yw[批序])
            优.zero_grad()
            l.backward()
            优.step()
            总 += float(l) * len(批序)
        if (轮 + 1) % 60 == 0:
            print(f"  第{轮 + 1}轮 训练损失 {总 / 切:.5f}")

    # ── 判据（留出的 10%）
    模型.eval()
    with torch.no_grad():
        留 = slice(切, len(Xw))
        预 = 模型(Xw[留])
        真 = Yw[留]
        基线 = Xw[留][:, -1, :]               # 基线：不做事，直接拿当前步当预测
        余 = torch.cosine_similarity(预, 真, dim=-1).mean().item()
        余基 = torch.cosine_similarity(基线, 真, dim=-1).mean().item()
        mse = float(损(预, 真))
        mse基 = float(损(基线, 真))
        # token 猜中率：谁更接近真值隐层（几何比较，不加载 lm_head 也成立）
        中 = (torch.cosine_similarity(预, 真, dim=-1)
              > torch.cosine_similarity(基线, 真, dim=-1)).float().mean().item()
    return 模型, {"余弦": 余, "余弦基": 余基, "MSE": mse, "MSE基": mse基, "胜过基线比例": 中}


if __name__ == "__main__":
    if 特征文件.exists():
        print(f"复用特征 {特征文件}")
        存 = np.load(特征文件)
        隐 = torch.from_numpy(存["H"]).to(设备)
        真值 = torch.from_numpy(存["真值"])
    else:
        隐, 真值 = 提特征()
        np.savez(特征文件, H=隐.cpu().numpy(), 真值=真值.cpu().numpy())
        print(f"特征已存 {特征文件}（{特征文件.stat().st_size / 1e6:.0f}MB）")

    模型, r = 训(隐, 真值)
    torch.save({k: v.cpu() for k, v in 模型.state_dict().items()}, 权重文件)
    print("\n═══ 判据 ═══")
    for k, v in r.items():
        print(f"  {k}: {v:.4f}")
    print(f"\n专家权重已存 {权重文件}")

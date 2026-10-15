# -*- coding: utf-8 -*-
"""专家 —— 硬判据：token 猜中率（决定草稿能不能真加速）

上一版判据（余弦 / 比基线近）太软：草稿模型的作用是替昂贵的输出模型先跑几步，
能不能省时间只取决于一件事 —— **猜中的比例**。

本脚本：
  · 加载已训好的专家（`专家头.pt`）+ 0.6B 的 lm_head（只为了把隐层解成词）；
  · 在**留出集**（末尾 10%，训练没见过的）上比三件事：
      ① 专家猜的下一步 token 是否等于真实下一步 token（top-1 / top-5）
      ② 基线（直接把当前隐层当预测，即"不做任何变换"）的猜中率
      ③ 输出模型自己的 top-1（= 上界：真值本来就是它的 argmax，故近乎 100%）
  · 顺带估算投机解码的加速上限（每一步的期望接受长度）。

显存纪律：窗口张量用 **fp16**（上一版用 fp32 要 1.66G，触发过 OOM 警告）。
"""
from __future__ import annotations

import gc
from pathlib import Path
from typing import Any

import numpy as np
import torch

项目 = Path("/home/lou/桌面/collaplex_agent")
权重目录 = Path("/home/lou/models/models/Qwen--Qwen3-0.6B/snapshots/master")
产出 = 项目 / "实验/小模型对照-20261007"
特征文件 = 产出 / "专家-特征.npz"
权重文件 = 产出 / "专家头.pt"
窗口 = 4
维 = 1024
设备 = "cuda" if torch.cuda.is_available() else "cpu"


class 专家(torch.nn.Module):
    def __init__(self, 维: int = 维, 窗: int = 窗口, 通道: int = 256) -> None:
        super().__init__()
        self.卷 = torch.nn.Conv1d(维, 通道, kernel_size=窗, padding=0)
        self.激 = torch.nn.GELU()
        self.出 = torch.nn.Linear(通道, 维)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.卷(x.transpose(1, 2))
        return self.出(self.激(y)[:, :, -1])


def 主() -> None:
    存 = np.load(特征文件)
    隐 = torch.from_numpy(存["H"]).to(设备)          # (N, 128, 1024) fp16
    真值 = torch.from_numpy(存["真值"]).to(设备)      # (N, 128)
    N, T, D = 隐.shape
    print(f"隐层 {tuple(隐.shape)}，窗口张量用 fp16")

    # 窗口输入（fp16 ⇒ 上一版 fp32 要 1.66G 撞过 OOM）
    X = 隐.reshape(N * T, D).half()
    Ytok = 真值.reshape(N * T)
    Xw = torch.stack([X[i - 窗口 + 1:i + 1] for i in range(窗口 - 1, X.shape[0])])
    Yt = Ytok[窗口 - 1:]
    切 = int(len(Xw) * 0.9)                            # 与训练一致的划分
    Xw, Yt = Xw[切:], Yt[切:]
    print(f"留出集 {tuple(Xw.shape)} ⇒ {len(Xw)} 个位置")

    # 载入已训专家
    专家网 = 专家().to(设备)
    _ = 专家网.load_state_dict(torch.load(权重文件, map_location=设备))
    专家网.eval()

    # 加载 0.6B 只为拿 lm_head（把隐层解成词）
    from transformers import AutoModelForCausalLM  # noqa: PLC0415
    模型: Any = AutoModelForCausalLM.from_pretrained(str(权重目录), dtype=torch.bfloat16)
    模型 = 模型.to(设备)
    模型.eval()
    词头: Any = 模型.lm_head
    print(f"模型 + lm_head 已上 {设备}（{torch.cuda.memory_allocated() / 1e9:.2f}G）")

    def 猜中率(h: torch.Tensor) -> tuple[float, float]:
        """h: (B, D) 隐层 ⇒ top-1 / top-5 命中真实下一个 token 的比例。"""
        中1 = 中5 = 0
        for i in range(0, len(h), 256):
            hh = h[i:i + 256].to(torch.bfloat16)
            lg = 词头(hh).float()
            真 = Yt[i:i + 256]
            顶5 = lg.topk(5, dim=-1).indices
            中1 += int((顶5[:, 0] == 真).sum())
            中5 += int((顶5 == 真.unsqueeze(-1)).any(dim=-1).sum())
        n = len(h)
        return 中1 / n, 中5 / n

    with torch.no_grad():
        # 专家：fp16 窗口 ⇒ 预测
        预 = []
        for i in range(0, len(Xw), 512):
            预.append(专家网(Xw[i:i + 512].float()))
        预h = torch.cat(预)
        基h = Xw[:, -1, :].float()                     # 基线：不做变换
        e1, e5 = 猜中率(预h)
        b1, b5 = 猜中率(基h)
        t1, _ = 猜中率(隐.reshape(N * T, D)[窗口 - 1:].float()[切:])   # 上界

    print("\n═══ 硬判据：猜中下一步 token ═══")
    print(f"  {'':14}{'top-1':>9}{'top-5':>9}")
    print(f"  {'专家':14}{e1:>9.4f}{e5:>9.4f}")
    print(f"  {'基线(不变换)':14}{b1:>9.4f}{b5:>9.4f}")
    print(f"  {'真值隐层(上界)':14}{t1:>9.4f}{'—':>9}")
    print(f"\n  相对基线的提升: top-1 {e1 - b1:+.4f}　top-5 {e5 - b5:+.4f}")
    if e1 > 0:
        print(f"  投机解码期望接受长度（上限估计）: {1 / (1 - e1):.2f} 步/token")

    del 模型, 专家网
    gc.collect()
    torch.cuda.empty_cache()
    print(f"\n显存归还后: {torch.cuda.memory_allocated() / 1e9:.2f}G")


if __name__ == "__main__":
    主()

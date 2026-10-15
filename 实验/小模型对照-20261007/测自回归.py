# -*- coding: utf-8 -*-
"""量专家的「自回归能撑多远」—— 这才是最终用途上的那个数。

为什么非测这个：
  训练/判据都是 **teacher forcing**（每一步喂真实隐层）⇒ 报出 88.79% 的 token 猜中率。
  但生成时喂的是**专家自己吐的隐层**，一偏就雪崩（exposure bias）。
  ⇒ 所以"能不能用"取决于**它自己走 32 步会崩在哪一步**，不是 teacher forcing 的数。

判据：从真实语料里取一段开头，让它**自回归生成** N 个 token，
      逐位比对真实 token，输出「连续猜对几个」（= 期望接受长度）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import torch

产出 = Path(__file__).parent
sys.path.insert(0, str(产出))

权重文件 = 产出 / "专家头-v7.pt"
主干 = Path("/home/lou/models/models/Qwen--Qwen3-0.6B/snapshots/master")
窗口 = 4
生成数 = 48


class 专家(torch.nn.Module):
    """★ 逐字照抄 专家-训5.py 的结构（上一版我自己猜成全连接，权重对不上）：
    残差草稿头 ĥ = h[t] + 专家(RMSNorm(窗口))；内部是 Conv1d + GELU + Linear。"""

    def __init__(self, 维: int = 1024, 窗: int = 窗口, 通道: int = 256) -> None:
        super().__init__()
        self.卷 = torch.nn.Conv1d(维, 通道, kernel_size=窗, padding=0)
        self.激 = torch.nn.GELU()
        self.出 = torch.nn.Linear(通道, 维, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.卷(x.transpose(1, 2))
        return self.出(self.激(y)[:, :, -1])


def 取真实开头(段: int = 24) -> str:
    快照 = 产出.parent / "行为旋钮-20261007/情境快照.jsonl"
    组: list[str] = []
    for 行 in 快照.read_text().splitlines()[:40]:
        if 行.strip():
            x: dict[str, Any] = json.loads(行)
            组.append(f"任务：{x.get('任务', '')}\n上一步：{x.get('上一步动作', '')}")
    return "\n".join(组)[:400]


if __name__ == "__main__":
    from transformers import AutoModelForCausalLM, AutoTokenizer

    可用 = 0.0
    for 行 in Path("/proc/meminfo").read_text().splitlines():
        if 行.startswith("MemAvailable"):
            可用 = int(行.split()[1]) / 1e6
    print(f"内存可用 {可用:.1f}G")
    设备 = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"设备 {设备}")

    print("加载主干(bf16)…")
    分词 = AutoTokenizer.from_pretrained(str(主干))
    主 = AutoModelForCausalLM.from_pretrained(str(主干), dtype=torch.bfloat16).to(设备).eval()
    词头 = 主.lm_head.weight.detach()                       # (vocab, hidden)
    范 = 主.model.norm.weight.detach()                      # final RMSNorm
    隐维 = 范.shape[0]
    print(f"隐维 {隐维}  词表 {词头.shape[0]}")

    网 = 专家(隐维).to(设备)
    存 = torch.load(权重文件, map_location=设备, weights_only=True)
    if isinstance(存, dict):
        网.load_state_dict(存)
    else:
        网 = 存.to(设备)
    网.eval()
    print(f"专家权重 {权重文件.name} 已装")

    def 归一(x: torch.Tensor) -> torch.Tensor:
        v = x.float()
        return (v / torch.sqrt(v.pow(2).mean(-1, keepdim=True) + 1e-6)) * 范.float()

    开头 = 取真实开头()
    编号 = 分词(开头, return_tensors="pt").input_ids.to(设备)
    print(f"\n真实开头 {编号.shape[1]} token：")
    print(f"  {分词.decode(编号[0][:24])!r}…\n")

    with torch.no_grad():
        出 = 主(编号, output_hidden_states=True)
        真隐 = 出.hidden_states[-1][0]                      # (L, D) 最后一层

    # ★ 自回归：每一步用**专家自己吐的隐层**续窗口（和训练时喂真值不同！）
    窗 = 真隐[:窗口].clone()                                # (窗口, D)
    串: list[int] = []
    for 步 in range(生成数):
        x = 归一(窗).unsqueeze(0).float()          # (1, 窗, D)
        with torch.no_grad():
            预 = 窗[-1] + 网(x)[0]                  # ★ 残差：ĥ = h[t] + 专家(...)
            lg = 归一(预).float() @ 词头.float().T   # 主干是 bf16，统一到 float32 比
            顶 = int(lg.argmax())
        串.append(顶)
        # ★ 窗口推进：喂**自己吐的隐层**（真实生成条件，而非训练时的真值隐层）
        窗 = torch.cat([窗[1:], 预.unsqueeze(0)], dim=0)

    print("【自回归生成】")
    print(f"  真实: {分词.decode(编号[0][窗口:窗口 + 生成数])!r}")
    print(f"  生成: {分词.decode(串)!r}")

    对 = sum(1 for i, t in enumerate(串) if 窗口 + i < 编号.shape[1] and t == int(编号[0][窗口 + i]))
    print(f"\n  逐位命中 {对}/{min(生成数, 编号.shape[1] - 窗口)} = {对 / max(min(生成数, 编号.shape[1] - 窗口), 1):.1%}")

    # 连续命中前缀 = 期望接受长度
    连 = 0
    for i, t in enumerate(串):
        if 窗口 + i < 编号.shape[1] and t == int(编号[0][窗口 + i]):
            连 += 1
        else:
            break
    print(f"  ★ 连续命中前缀（=期望接受长度）: {连} 步")
    print("\n  （对比 teacher forcing 报的 88.79% —— 那个数喂的是真值隐层，现实中拿不到）")

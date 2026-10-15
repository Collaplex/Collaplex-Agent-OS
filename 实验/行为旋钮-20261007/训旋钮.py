"""行为旋钮实验 · 训练与对照

旋钮 = 一个字符级 1D CNN（底层就是卷积）。三档输入、三档大小：
  档① 只吃情境文本
  档② 再加 top-3 记忆节点向量
  档③ 再加"沿边一跳"的桥节点向量
大小：小 / 中 / 大三档，看参数量拐点。

两个任务分别跑：
  任务A 首轮行为（动手 / 先问 / 直接答）—— 327 轮真数据
  任务B 被拦之后（换路 / 继续同族）—— 造教材
按题号切分训练/测试（不按行切，免得同一道题泄漏）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import torch
import torch.nn as nn

这里 = Path(__file__).parent
torch.manual_seed(0)
np.random.seed(0)


def 读数据() -> tuple[list[str], list[str], list[str], np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    数 = np.load(这里 / "数据集.npz", allow_pickle=False)
    图 = np.load(这里 / "图.npz", allow_pickle=False)
    return (list(数["情境文"]), list(数["标签"]), list(数["任务"]),
            np.asarray(数["题号"]), np.asarray(图["前3"]), np.asarray(图["桥"]))


文, 签, 任, 题号, 前3, 桥 = 读数据()
节 = np.load(这里 / "图.npz", allow_pickle=False)["节点向"]

# ── 字符表 ────────────────────────────────────────────────────
字表: dict[str, int] = {}
for t in 文:
    for c in t:
        if c not in 字表:
            字表[c] = len(字表) + 2      # 0=pad 1=unk
最长 = 180


def 编码文(s: str) -> list[int]:
    ids = [字表.get(c, 1) for c in s[:最长]]
    return ids + [0] * (最长 - len(ids))


# ── 旋钮 ──────────────────────────────────────────────────────
class 旋钮(nn.Module):
    def __init__(self, 词表: int, 维: int, 通道: int, 档: int, 类数: int) -> None:
        super().__init__()
        self.档 = 档
        self.嵌 = nn.Embedding(词表, 维, padding_idx=0)
        self.卷3 = nn.Conv1d(维, 通道, 3, padding=1)
        self.卷5 = nn.Conv1d(维, 通道, 5, padding=2)
        self.图 = nn.Linear(1024, 通道) if 档 >= 2 else None
        入 = 通道 * 2 + (通道 if 档 == 2 else 通道 * 2 if 档 == 3 else 0)
        self.头 = nn.Sequential(nn.Linear(入, 通道 * 2), nn.ReLU(), nn.Dropout(0.1), nn.Linear(通道 * 2, 类数))

    def forward(self, x: torch.Tensor, 节向: torch.Tensor, 取节: torch.Tensor) -> torch.Tensor:
        e = self.嵌(x).transpose(1, 2)                       # B,d,L
        h = torch.cat([torch.relu(self.卷3(e)).max(dim=2).values,
                       torch.relu(self.卷5(e)).max(dim=2).values], dim=1)
        块 = [h]
        if self.档 >= 2:
            assert self.图 is not None
            m = 节向[取节[:, :3].clamp(min=0)].mean(dim=1)      # 档②③ 先给 top3
            块.append(torch.relu(self.图(m)))
        if self.档 == 3:
            assert self.图 is not None
            邻 = 节向[取节[:, 3:6].clamp(min=0)]              # 后 3 列是桥（-1 是没桥）
            掩 = (取节[:, 3:6] >= 0).unsqueeze(-1).float()
            桥m = (邻 * 掩).sum(dim=1) / 掩.sum(dim=1).clamp(min=1)
            块.append(torch.relu(self.图(桥m)))
        return self.头(torch.cat(块, dim=1))


尺寸 = [(32, 32, "小"), (128, 96, "中"), (512, 256, "大")]


def 取节张量(行: np.ndarray[Any, Any], 档: int) -> torch.Tensor:
    t3 = 前3[行]
    if 档 == 1:
        z = np.zeros((len(行), 6), dtype=np.int64)
        return torch.as_tensor(z)
    if 档 == 2:
        z = np.concatenate([t3, np.full((len(行), 3), -1)], axis=1)
        return torch.as_tensor(z)
    桥补 = np.concatenate([桥[行], np.full((len(行), 1), -1)], axis=1)
    return torch.as_tensor(np.concatenate([t3, 桥补], axis=1))


def 跑一个(任务名: str, 档: int, 通道: int, 维: int, 标名: str) -> tuple[float, int]:
    选 = np.asarray([i for i, r in enumerate(任) if r == 任务名])
    g = 题号[选]
    类 = sorted({签[i] for i in 选})
    类号 = {c: k for k, c in enumerate(类)}
    # 按题号切：每道题要么在训练、要么在测试
    组 = np.unique(g)
    rs = np.random.RandomState(7)
    rs.shuffle(组)
    切 = int(len(组) * 0.8)
    训题, 测题 = set(组[:切].tolist()), set(组[切:].tolist())
    训 = np.asarray([i for i in 选 if 题号[i] in 训题])
    测 = np.asarray([i for i in 选 if 题号[i] in 测题])
    if len(训) == 0 or len(测) == 0:
        return 0.0, 0
    x训 = torch.as_tensor(np.asarray([编码文(文[i]) for i in 训]))
    y训 = torch.as_tensor(np.asarray([类号[签[i]] for i in 训]))
    x测 = torch.as_tensor(np.asarray([编码文(文[i]) for i in 测]))
    y测 = torch.as_tensor(np.asarray([类号[签[i]] for i in 测]))
    节向 = torch.as_tensor(节, dtype=torch.float32)
    z训, z测 = 取节张量(训, 档), 取节张量(测, 档)

    模 = 旋钮(len(字表) + 2, 维, 通道, 档, len(类))
    参 = sum(p.numel() for p in 模.parameters())
    优 = torch.optim.AdamW(模.parameters(), lr=2e-3, weight_decay=1e-4)
    损f = nn.CrossEntropyLoss()
    for _轮 in range(40):
        for a in range(0, len(训), 32):
            b = slice(a, a + 32)
            优.zero_grad()
            损 = 损f(模(x训[b], 节向, z训[b]), y训[b])
            损.backward()
            优.step()
    with torch.no_grad():
        预 = 模(x测, 节向, z测).argmax(dim=1)
        正 = float((预 == y测).float().mean())
    多 = max(float((y测 == k).float().mean()) for k in range(len(类)))
    召 = []
    for k in range(len(类)):
        真 = y测 == k
        if int(真.sum()) > 0:
            召.append(float((预[真] == k).float().mean()))
    均衡 = sum(召) / len(召) if 召 else 0.0
    print(f"  {标名:10s} 档{档} 参数{参:>9,d}  准确率 {正*100:5.1f}%  均衡正确率 {均衡*100:5.1f}%  多数类基线 {多*100:5.1f}%  训练{len(训)}/测试{len(测)}")
    return 正, 参


结果: dict[str, Any] = {}
for 任务名 in ("首轮", "被拦后"):
    print(f"\n=== 任务：{任务名} ===")
    结果[任务名] = []
    for 维, 通道, 名 in 尺寸:
        for 档 in (1, 2, 3):
            a, p = 跑一个(任务名, 档, 通道, 维, 名)
            结果[任务名].append({"档": 档, "尺寸": 名, "参数": p, "acc": round(a, 4)})
(这里 / "结果.json").write_text(json.dumps(结果, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n写好 结果.json")

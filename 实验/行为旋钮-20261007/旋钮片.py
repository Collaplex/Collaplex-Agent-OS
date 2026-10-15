# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUntypedBaseClass=false
# pyright: reportUnknownParameterType=false
# ↑ torch 的标注在 strict 下天然带 Unknown（不是本文件的 bug）；其余类别仍按 strict 查。

"""行为旋钮 · 旋钮片（感受器 → 一片 CNN 旋钮 → 效应器）

架构（三层都"先天存在"，训练只定激活路径）：
  感受器   情境向量(1024) ──先天连接──> N 个旋钮（每个旋钮一个身份键，零训练）
  旋钮片   共享算子作用在每个位置 + 相邻一跳传导（★ 参数与 N 基本无关）
  效应器   池化 → 读出到 13 个做法族

训练：标签 = 这一步该用哪个做法族；样本权重 = 这一步"有没有用"（判据命中 / 输出进了答案）。
对照：N = 1 / 8 / 32 / 128 → 看准确率与参数量什么时候到顶（回答"几十还是几百个"）。

为什么不是 MoE 路由：不是 softmax 选 1 个，是"一次激活一片 + 传导"；
旋钮算子共享、无中心路由权重。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import torch
import torch.nn as nn

这里 = Path(__file__).parent
缓存 = 这里 / "旋钮片-嵌入.npz"
维 = 1024
族们 = ["网:本地", "查:磁盘", "查:占用", "查:内存", "查:内核", "查:硬件", "查:端口", "查:系统",
        "查:服务", "查:进程", "查:日志", "查:时间", "读:内核内存"]
族号 = {f: i for i, f in enumerate(族们)}
粗表 = {"df": "查:磁盘", "free": "查:内存", "du": "查:占用", "ss": "查:端口", "netstat": "查:端口",
        "ps": "查:进程", "pgrep": "查:进程", "systemctl": "查:服务", "journalctl": "查:日志",
        "lscpu": "查:硬件", "lshw": "查:硬件", "dmidecode": "查:硬件", "nvidia-smi": "查:硬件",
        "uptime": "查:系统", "date": "查:时间", "cat": "读:内核内存", "ip": "网:本地"}


def 粗族(动: str) -> str:
    d = 动.strip()
    首群 = [x for x in d.split() if x != "sudo"]
    if not 首群:
        return "?"
    return 粗表.get(首群[0].split("/")[-1], "其他")


def 造数据() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """情境文本 + 标签(做法族) + 权重(有没有用)，向量化后落盘缓存。"""
    快 = [json.loads(x) for x in (这里 / "情境快照.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    文: list[str] = []
    签: list[int] = []
    权: list[float] = []
    for x in 快:
        族 = 粗族(str(x["本步动作"]))
        if 族 not in 族号:
            continue
        情 = f"{x['任务']} {x['上一步反馈']}"
        文.append(情)
        签.append(族号[族])
        # "有没有用"：结果成功且不是拦截 → 2.0；被拦 → -1.0；其余 0.3
        v = 2.0 if x["本步结果"] == "成功" else (-1.0 if x["本步结果"] == "拦截" else 0.3)
        权.append(v)
    if 缓存.exists():
        老 = np.load(缓存)
        if int(老["n"]) == len(文):
            print(f"  复用缓存嵌入 {缓存.name}")
            return cast("np.ndarray", 老["X"]), np.array(签), np.array(权)
    import urllib.request

    print(f"  向量化 {len(文)} 条情境（本机嵌入 8199）…")
    X = np.zeros((len(文), 维), dtype=np.float32)
    for i in range(0, len(文), 32):
        批 = 文[i:i + 32]
        体 = json.dumps({"model": "qwen3-embedding-0.6b", "input": 批}).encode()
        请 = urllib.request.Request("http://127.0.0.1:8199/v1/embeddings", data=体,
                                    headers={"Content-Type": "application/json"})
        开 = urllib.request.build_opener(urllib.request.ProxyHandler({}))       # 直连，绕过 http_proxy
        with 开.open(请, timeout=120) as r:
            果 = json.loads(r.read())
        for j, d in enumerate(果["data"]):
            v = np.array(d["embedding"], dtype=np.float32)
            X[i + j] = (v / (np.linalg.norm(v) + 1e-6))[:维]
    np.savez_compressed(缓存, X=X, n=len(文))
    return X, np.array(签), np.array(权)


class 旋钮片(nn.Module):
    """感受器 → N 个旋钮 → 共享算子 + 相邻传导 → 池化 → 效应器。"""

    def __init__(self, n: int, 维宽: int = 64, 身份种: int = 7) -> None:
        super().__init__()
        self.n = n
        g = torch.Generator().manual_seed(身份种)
        # ① 感受器 → 旋钮：每个旋钮一个"身份键"
        #   ★ 必须**可训练** —— "感受器进来走哪些旋钮"靠的就是它。
        #    第一版把它设成死的（buffer），结果 N=1/8/32/128 跑出来一模一样：旋钮再多也没东西可学。
        self.键: nn.Parameter = nn.Parameter(torch.randn(n, 维, generator=g) / (维 ** 0.5))
        # ② 旋钮片：共享算子（所有位置用同一套）+ 相邻一跳
        self.入: nn.Linear = nn.Linear(1, 维宽)
        self.邻: nn.Linear = nn.Linear(维宽, 维宽)
        self.自: nn.Linear = nn.Linear(维宽, 维宽)
        # ③ 效应器读出
        self.出: nn.Linear = nn.Linear(维宽, len(族们))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        a = x @ self.键.T                      # (批, N) 感受器驱动：一次激活一片
        h = torch.tanh(self.入(a.unsqueeze(-1)))              # (批, N, 维宽)
        左 = torch.roll(h, 1, dims=1)                          # 相邻传导（环状）
        右 = torch.roll(h, -1, dims=1)
        h = torch.tanh(self.自(h) + self.邻(左) + self.邻(右))   # 共享算子，所有位置同一套
        # ★ 读出按"激活强度"加权，不是平均池化 —— 平均会把"哪些旋钮亮"抹平
        w = torch.softmax(a, dim=1).unsqueeze(-1)
        return self.出((h * w).sum(dim=1))                      # → 效应器

    def 参数量(self) -> int:
        return sum(p.numel() for p in self.parameters())


def 跑一档(n: int, X: np.ndarray, 签: np.ndarray, 权: np.ndarray, 轮: int = 60) -> dict[str, Any]:
    切 = int(len(X) * 0.7)
    Xt = torch.tensor(X); yt = torch.tensor(签)
    Xv, yv = Xt[切:], yt[切:]
    m = 旋钮片(n)
    优 = torch.optim.Adam(m.parameters(), lr=2e-3)
    w = torch.tensor(权[:切])
    损f = nn.CrossEntropyLoss(reduction="none")
    for _ in range(轮):
        m.train()
        优.zero_grad()
        损 = (损f(m(Xt[:切]), yt[:切]) * (w + 1.5)).mean()      # 没用的样本权重低，有用的高
        损.backward()
        优.step()
    m.eval()
    with torch.no_grad():
        预 = m(Xv).argmax(dim=1)
    # 均衡正确率（按类平均，避免多数类灌水）
    per: list[float] = []
    for k in range(len(族们)):
        掩 = yv == k
        if int(掩.sum()) > 0:
            per.append(float((预[掩] == k).float().mean()))
    多 = max(float((yv == k).float().mean()) for k in range(len(族们)))
    return {"N": n, "参数": m.参数量(), "准确率": round(float((预 == yv).float().mean()), 3),
            "均衡正确率": round(sum(per) / max(1, len(per)), 3), "多数类基线": round(多, 3)}


def 跑有用(n: int, X: np.ndarray, 权: np.ndarray, 轮: int = 60) -> dict[str, Any]:
    """任务B：这一步"有没有用"（二分类）。标签不是"它当时干了什么"，而是"这步有没有产出"。"""
    切 = int(len(X) * 0.7)
    y = (权 > 1.0).astype("int64")                 # 有用=1（成功），其余=0
    Xt = torch.tensor(X)
    yt = torch.tensor(y)
    Xv, yv = Xt[切:], yt[切:]
    print(f"    （任务B 标签分布：训练 有用 {int(y[:切].sum())}/{切} ｜ 测试 有用 {int(y[切:].sum())}/{len(y)-切}）")
    m = nn.Sequential(nn.Linear(维, 128), nn.ReLU(), nn.Linear(128, 2))
    优 = torch.optim.Adam(m.parameters(), lr=2e-3)
    损f = nn.CrossEntropyLoss()
    for _ in range(轮):
        m.train()
        优.zero_grad()
        损 = 损f(m(Xt[:切]), yt[:切])
        损.backward()
        优.step()
    m.eval()
    with torch.no_grad():
        预 = m(Xv).argmax(dim=1)
    多 = max(float((yv == k).float().mean()) for k in range(2))
    return {"N": n, "参数": sum(q.numel() for q in m.parameters()),
            "准确率": round(float((预 == yv).float().mean()), 3), "多数类基线": round(多, 3)}


if __name__ == "__main__":
    X, 签, 权 = 造数据()
    print(f"样本 {len(X)} 条 ｜ 类别 {len(族们)} 个 ｜ 有用样本 {int((权 > 1).sum())} 条")
    切 = int(len(X) * 0.7)
    print(f"训练 {切} / 测试 {len(X) - 切}")
    常 = np.bincount(签[:切], minlength=len(族们)).argmax()
    print(f"（基线：一律猜训练集最多的「{族们[int(常)]}」，均衡正确率≈{1/len(族们):.3f}）\n")
    print("【任务A】猜「这一步该用哪个做法族」（13 类）—— 标签 = 它历史上实际用了哪个")
    print(f"  {'N':>5s} {'参数量':>10s} {'准确率':>8s} {'均衡正确率':>10s}")
    for n in (1, 8, 32, 128):
        r = 跑一档(n, X, 签, 权)
        print(f"  {r['N']:5d} {r['参数']:10d} {r['准确率']*100:7.1f}% {r['均衡正确率']*100:9.1f}%")

    print("\n【任务B】猜「这一步有没有用」（2 类）—— 标签 = 这步有没有产出（不看它干了什么）")
    print(f"  {'N':>5s} {'参数量':>10s} {'准确率':>8s} {'多数类基线':>10s}")
    for n in (1, 8, 32, 128):
        r = 跑有用(n, X, 权)
        print(f"  {r['N']:5d} {r['参数']:10d} {r['准确率']*100:7.1f}% {r['多数类基线']*100:9.1f}%")

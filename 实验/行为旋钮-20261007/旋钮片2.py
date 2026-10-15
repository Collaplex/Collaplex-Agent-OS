# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUntypedBaseClass=false
# pyright: reportUnknownParameterType=false

"""行为旋钮 · 旋钮片 v2（按真实数据重写）

v1 两处设计错（已修，教训见下）：
  ① 旋钮的"身份键"被设成死的（buffer）→ N=1/8/32/128 结果一模一样，旋钮再多也没东西可学。
     修：身份键必须是**可训练参数** —— 这正是"感受器进来走哪些旋钮"要学的东西。
  ② 读出用平均池化 → 把"哪些旋钮亮了"抹平。修：按激活强度加权求和。

v2 换掉两处"没信息量的标签"：
  · 做法族只用 13 个手写族 → 只覆盖 973/2343 步。改成**数据里的真实首词**（python/ss/carve/df/…）。
  · 标签"这一步有用吗"里 96.6% 都是"有用" → 退化成猜多数类。
    改成**"这一步会不会被拦/报错"**（448/2343 = 19.1% 正类，有区分度）。

架构（三层先天存在，训练只定激活路径）：
  感受器 情境向量(1024) ──> N 个旋钮（每个旋钮一个可训身份键）
  旋钮片 共享算子作用在每个位置 + 相邻一跳传导（★ 算子共享，参数量与 N 基本无关）
  效应器 按激活强度读出
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
其他 = "其他"


def 首词(动: str) -> str:
    d = [x for x in str(动).split() if x != "sudo"]
    if not d:
        return 其他
    return d[0].split("/")[-1]


def 造数据() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str], np.ndarray]:
    """返回 (向量, 首词标签, 被拦/报错标签, 族名表, 权重)。"""
    快 = [json.loads(x) for x in (这里 / "情境快照.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    计数: dict[str, int] = {}
    for x in 快:
        计数[首词(x["本步动作"])] = 计数.get(首词(x["本步动作"]), 0) + 1
    常用 = [k for k, v in sorted(计数.items(), key=lambda kv: -kv[1]) if v >= 25][:20]
    族们 = 常用 + [其他]
    族号 = {f: i for i, f in enumerate(族们)}

    文: list[str] = []
    签首: list[int] = []
    签拦: list[int] = []
    权: list[float] = []
    for x in 快:
        f = 首词(x["本步动作"])
        if f not in 族号:
            f = 其他
        文.append(f'{x["任务"]} ｜上一步：{x["上一步结果"]} {x["上一步反馈"][:200]}｜已拦{x["之前被拦次数"]}次')
        签首.append(族号[f])
        坏 = 1 if x["本步结果"] in ("拦截", "报错") else 0
        签拦.append(坏)
        权.append(2.0 if 坏 == 0 else 3.0)          # 坏样本给更高权重（少数类）

    if 缓存.exists():
        老 = np.load(缓存)
        if int(老["n"]) == len(文):
            print(f"  复用缓存嵌入（{len(文)} 条）")
            return cast("np.ndarray", 老["X"]), np.array(签首), np.array(签拦), 族们, np.array(权)
    import urllib.request

    print(f"  向量化 {len(文)} 条情境（本机嵌入 8199）…")
    X = np.zeros((len(文), 维), dtype=np.float32)
    开 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for i in range(0, len(文), 32):
        体 = json.dumps({"model": "qwen3-embedding-0.6b", "input": 文[i:i + 32]}).encode()
        请 = urllib.request.Request("http://127.0.0.1:8199/v1/embeddings", data=体,
                                    headers={"Content-Type": "application/json"})
        with 开.open(请, timeout=180) as r:
            果 = json.loads(r.read())
        for j, d in enumerate(果["data"]):
            v = np.array(d["embedding"], dtype=np.float32)
            X[i + j] = (v / (np.linalg.norm(v) + 1e-6))[:维]
    np.savez_compressed(缓存, X=X, n=len(文))
    return X, np.array(签首), np.array(签拦), 族们, np.array(权)


class 旋钮片(nn.Module):
    def __init__(self, n: int, 类数: int, 维宽: int = 64, 身份种: int = 7) -> None:
        super().__init__()
        g = torch.Generator().manual_seed(身份种)
        # ★ 身份键可训练：这就是"感受器进来走哪些旋钮"要学的东西
        self.键: nn.Parameter = nn.Parameter(torch.randn(n, 维, generator=g) / (维 ** 0.5))
        self.入: nn.Linear = nn.Linear(1, 维宽)
        self.邻: nn.Linear = nn.Linear(维宽, 维宽)
        self.自: nn.Linear = nn.Linear(维宽, 维宽)
        self.出: nn.Linear = nn.Linear(维宽, 类数)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        a = x @ self.键.T                                     # (批, N) 一次激活一片
        h = torch.tanh(self.入(a.unsqueeze(-1)))              # (批, N, 维宽)
        左 = torch.roll(h, 1, dims=1)
        右 = torch.roll(h, -1, dims=1)
        h = torch.tanh(self.自(h) + self.邻(左) + self.邻(右))   # 共享算子 + 相邻传导
        w = torch.softmax(a, dim=1).unsqueeze(-1)              # ★ 按激活强度加权读出，不是平均池化
        return self.出((h * w).sum(dim=1))

    def 参数量(self) -> int:
        return sum(p.numel() for p in self.parameters())


def 跑(n: int, X: np.ndarray, y: np.ndarray, 类数: int, 权: np.ndarray, 轮: int = 80) -> dict[str, Any]:
    切 = int(len(X) * 0.7)
    Xt = torch.tensor(X)
    yt = torch.tensor(y)
    Xv, yv = Xt[切:], yt[切:]
    m = 旋钮片(n, 类数)
    优 = torch.optim.Adam(m.parameters(), lr=2e-3)
    损f = nn.CrossEntropyLoss(reduction="none")
    w = torch.tensor(权[:切], dtype=torch.float32)
    for _ in range(轮):
        m.train()
        优.zero_grad()
        损 = (损f(m(Xt[:切]), yt[:切]) * w).mean()
        损.backward()
        优.step()
    m.eval()
    with torch.no_grad():
        预 = m(Xv).argmax(dim=1)
    per: list[float] = []
    for k in range(类数):
        掩 = yv == k
        if int(掩.sum()) > 0:
            per.append(float((预[掩] == k).float().mean()))
    多 = max(float((yv == k).float().mean()) for k in range(类数))
    return {"N": n, "参数": m.参数量(), "准确率": float((预 == yv).float().mean()),
            "均衡正确率": sum(per) / max(1, len(per)), "多数类基线": 多}


if __name__ == "__main__":
    X, 签首, 签拦, 族们, 权 = 造数据()
    print(f"样本 {len(X)} 条 ｜ 首词族 {len(族们)} 个 ｜ 被拦/报错 {int(签拦.sum())} 条（{签拦.mean()*100:.1f}%）")
    print("  族：" + " ".join(f"{f}({int((签首==i).sum())})" for i, f in enumerate(族们)))

    print("\n【任务A】猜「这一步会用什么命令」—— 标签 = 真实首词")
    print(f"  {'N':>5s} {'参数量':>9s} {'准确率':>8s} {'均衡正确率':>10s} {'多数类基线':>10s}")
    for n in (1, 8, 32, 128):
        r = 跑(n, X, 签首, len(族们), 权)
        print(f"  {r['N']:5d} {r['参数']:9d} {r['准确率']*100:7.1f}% {r['均衡正确率']*100:9.1f}% {r['多数类基线']*100:9.1f}%")

    print("\n【任务B】★猜「这一步会不会被拦/报错」—— 标签 = 拦截或报错（19.1% 正类）")
    print(f"  {'N':>5s} {'参数量':>9s} {'准确率':>8s} {'均衡正确率':>10s} {'多数类基线':>10s}")
    for n in (1, 8, 32, 128):
        r = 跑(n, X, 签拦, 2, 权)
        print(f"  {r['N']:5d} {r['参数']:9d} {r['准确率']*100:7.1f}% {r['均衡正确率']*100:9.1f}% {r['多数类基线']*100:9.1f}%")
    print("\n（任务B 均衡正确率 > 50% 才算真会；0.5 = 瞎猜）")

# -*- coding: utf-8 -*-
"""think 循环 · 带专家 —— 让 think 里的字**由专家吐**（老板图上的形态）

老板确认的形态（和传统 reasoning 一样，但 think 由专家团产生）：
    输出 = <think> 专家团的思考（多轮、互相看得见）</think> + 正式回答
  区别在：传统是一模型自说自话；这里是**专家团互见**。

本版要验证的一句话：**专家（v4 草稿头）吐的隐层，能不能解码成字**。
  · 能 ⇒ 图上"专家团思考"这条路是真的，剩下只是**把专家的质量做上去**；
  · 不能（大概率吐得糙）⇒ 那也是有效结论：**语料决定它吐什么**，
    v4 是在项目文档上训的，不是"问答/思考"语料 ⇒ 该换语料。

流程（一步一字）：
    问题文本 → 0.6B 编码成隐层 → 专家(v4)从窗口预测下一个隐层 ĥ
    → lm_head(RMSNorm(ĥ)) → 取 top-5 采样出下一个字 → 拼回序列 → 继续
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import torch

项目 = Path("/home/lou/桌面/collaplex_agent")
权重目录 = Path("/home/lou/models/models/Qwen--Qwen3-0.6B/snapshots/master")
产出 = 项目 / "实验/小模型对照-20261007"
权重文件 = 产出 / "专家头-v5.pt"

窗口 = 4
维 = 1024
RMS_EPS = 1e-6
# ★ 走 CPU：8G 卡被 llama-server（产品后端）占着，这件只要 1.2G 内存，不必动产品
设备 = "cpu"


class 专家(torch.nn.Module):
    def __init__(self, 维: int = 维, 窗: int = 窗口, 通道: int = 256) -> None:
        super().__init__()
        self.卷 = torch.nn.Conv1d(维, 通道, kernel_size=窗, padding=0)
        self.激 = torch.nn.GELU()
        self.出 = torch.nn.Linear(通道, 维, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.卷(x.transpose(1, 2))
        return self.出(self.激(y)[:, :, -1])


def 归一(x: torch.Tensor, w: torch.Tensor) -> torch.Tensor:
    f = x.float()
    return (f / f.pow(2).mean(-1, keepdim=True).add(RMS_EPS).sqrt()) * w.float()


def 主(问题: str, 步数: int = 24) -> None:
    from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415

    分词器 = AutoTokenizer.from_pretrained(str(权重目录))
    模型: Any = AutoModelForCausalLM.from_pretrained(str(权重目录), dtype=torch.bfloat16)
    模型 = 模型.to(设备)
    模型.eval()
    范 = 模型.model.norm.weight.detach().to(torch.float16)
    词头 = 模型.lm_head.weight.detach().to(torch.float16)

    专家网 = 专家().to(设备)
    _ = 专家网.load_state_dict(torch.load(权重文件, map_location=设备))
    专家网.eval()
    print(f"0.6B + 专家(v4, 1.31M) 已上 {设备}")

    ids: list[int] = 分词器(f"问题：{问题}\n思考：")["input_ids"]
    print(f"\n【问题】{问题}\n\n<think>")

    出字: list[str] = []
    with torch.no_grad():
        for _步 in range(步数):
            张 = torch.tensor([ids[:512]], dtype=torch.long).to(设备)
            h = 模型(张, output_hidden_states=True).hidden_states[-1]   # (1, L, 1024)
            if h.shape[1] < 窗口:
                break
            窗 = 归一(h[0], 范).to(torch.float16)[-窗口:].unsqueeze(0)   # (1, 窗, 1024)
            h预 = h[0, -1].float() + 专家网(窗.float())[0]              # 残差
            lg = (归一(h预.unsqueeze(0), 范).to(torch.float16) @ 词头.T).float()
            顶 = lg.topk(5, dim=-1).indices[0]
            下一 = int(顶[torch.randint(0, 5, (1,))])                  # top-5 采样
            ids.append(下一)
            字 = 分词器.decode([下一])
            出字.append(字)
            sys.stdout.write(字)
            sys.stdout.flush()
    print("\n</think>")
    print(f"\n【专家吐出来的文本】{''.join(出字)}")
    print("\n（说明：这是 v4 专家在**项目文档**语料上训出来的产物。"
          "它吐什么由语料决定，所以看它通不通顺，等于看语料对不对路。）")


if __name__ == "__main__":
    if not 权重文件.exists():
        raise SystemExit(f"缺专家权重 {权重文件}（先跑 专家-训4.py）")
    主("根分区还剩多少")

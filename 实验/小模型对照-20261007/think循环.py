# -*- coding: utf-8 -*-
"""think 循环 —— 最小可跑版（照老板的架构设计）

老板的话：
  · "专家模型可以跑显卡上，因为输出模型不用很强 —— 这就是为什么我会搞一个循环的原因，
     不用全部算一次出，可以一轮一轮出。"
  · "这部分按照 think 标签开始，然后输出模型输出的就是 think 标签后的回答。"
  · "毕竟 CNN 专家是可以看到互相的。"

⇒ 落法（本版）：
   输出模型 = Qwen3-0.6B（**冻结、不训**，只当"话 ↔ 向量"的编解码器）
   专家     = **输出模型自己的每一层**（一层一个视角 = 一个专家 ⇒ 数量由模型自己决定，不是写死的）
   互见     = 各专家的隐层**聚合回一个共享态**，再接回序列尾 ⇒ 下一轮它们是在"别人的看法之上"再看
   循环     = 一轮吐一小段，写进 **think 标签**
   门控     = 说出"够了"或到轮数上限 ⇒ **输出模型输出 think 之后的那段正式回答**

本版**不训任何东西**，只验证：结构跑不跑得通、"专家互见"看不看得见、账怎么算。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TypedDict

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

权重目录 = Path("/home/lou/models/models/Qwen--Qwen3-0.6B/snapshots/master")

最多轮数 = 6      # 门控上限（真实设计里由门控模型决定）
每轮出词 = 3      # 一轮往外吐几个字（think 是逐步长出来的）
够了的词 = ("够了", "结束", "答案", "所以", "final", "therefore")


class 结果型(TypedDict):
    日志: list[str]
    互见度: list[float]
    正式回答: str
    草稿耗时: float
    正式耗时: float


class Think循环:
    def __init__(self) -> None:
        可用GB = 0.0
        for _行 in Path("/proc/meminfo").read_text().splitlines():
            if _行.startswith("MemAvailable:"):
                可用GB = int(_行.split()[1]) / 1024 / 1024
        # ⚠ 2026-10-07 OOM 事故：float32(2.4G) 把 llama-server 挤死了。
        #   本项目铁律：先查 MemAvailable，不够就拒跑，绝不把显存里现成的服务拖下水。
        if 可用GB < 3.0:
            raise SystemExit(
                f"内存只剩 {可用GB:.1f}G（需要 ≥3G）—— 拒跑。"
                "这台机器被 Windows VM 占掉 10G，别冒险（上次就是这样把 llama-server 挤死的）。"
            )
        self.分词器 = AutoTokenizer.from_pretrained(str(权重目录))
        # ★ 用 bf16（1.2G）而不是 float32（2.4G）
        self.模型 = AutoModelForCausalLM.from_pretrained(str(权重目录), dtype=torch.bfloat16)
        self.模型.eval()

    def 跑(self, 问题: str) -> 结果型:
        with torch.no_grad():
            批 = self.分词器(问题, return_tensors="pt", truncation=True, max_length=128)
            嵌入 = self.模型.model.embed_tokens(批.input_ids)

        日志: list[str] = []
        互见度: list[float] = []
        t0 = time.time()
        停 = False

        for 轮 in range(1, 最多轮数 + 1):
            with torch.no_grad():
                出 = self.模型(  # ← 一次 forward ⇒ 每一层的看法同时拿到
                    inputs_embeds=嵌入, output_hidden_states=True, use_cache=False
                )
                各层 = 出.hidden_states[1:]                      # 每层 = 一个专家视角
                尾 = torch.stack([层[:, -1, :][0] for 层 in 各层], dim=0)   # (专家数, d)
                共享态 = 尾.mean(dim=0, keepdim=True)             # ★ 专家互见：聚合成共享态
                一致 = 1.0 - float(尾.std(dim=0).mean() / (尾.abs().mean() + 1e-6))

                样例 = torch.topk(self.模型.lm_head(共享态), 每轮出词, dim=-1).indices[0].tolist()
                片 = "".join(self.分词器.decode([i], skip_special_tokens=True) for i in 样例).strip()

            互见度.append(round(一致, 3))
            日志.append(f"  第{轮}轮　{len(各层)}个专家　一致度 {一致:.3f}　→ 「{片}」")

            if any(w in 片 for w in 够了的词):
                日志.append("  → 门控：认定想完了")
                停 = True
                break

            嵌入 = torch.cat([嵌入, 共享态.unsqueeze(1)], dim=1)   # ← 喂回：下一轮各层看得见

        if not 停:
            日志.append("  → 门控：到轮数上限")

        草稿耗时 = time.time() - t0

        # ★ 正式回答：think 之后，用完整输出模型一次出
        with torch.no_grad():
            t1 = time.time()
            提示 = f"{问题}\n（上面已经想过一轮了，现在只给正式答案，别重复思考）\n答案："
            批2 = self.分词器(提示, return_tensors="pt", truncation=True, max_length=180)
            出2 = self.模型.generate(**批2, max_new_tokens=40, do_sample=False)
            正式 = self.分词器.decode(出2[0][批2.input_ids.shape[1]:], skip_special_tokens=True).strip()
            正式耗时 = time.time() - t1

        return {"日志": 日志, "互见度": 互见度, "正式回答": 正式,
                "草稿耗时": 草稿耗时, "正式耗时": 正式耗时}


if __name__ == "__main__":
    循环 = Think循环()
    for 题 in ("根分区还剩多少", "加盐提浓度"):
        print(f"\n{'═' * 62}\n【问题】{题}\n<think>")
        结果 = 循环.跑(题)
        for 行 in 结果["日志"]:
            print(行)
        print("</think>")
        print(f"【正式回答】{结果['正式回答']}")
        print(f"【账】草稿 {结果['草稿耗时']:.1f}s（最多 {最多轮数} 轮）　"
              f"正式 {结果['正式耗时']:.1f}s（全模型一次）")

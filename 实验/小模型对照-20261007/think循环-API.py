# -*- coding: utf-8 -*-
"""think 循环 —— 最小可跑版（照老板的架构设计）·API 版（安全，零内存风险）

⚠ OOM 事故记录（2026-10-07）：
   上一版 `think循环.py` 在本机加载 Qwen3-0.6B（**float32 = 2.4G 宿主内存**），而这台机器
   被 Windows VM 占掉 10G，宿主只剩 ~2G ⇒ 内存压力下 **OOM killer 挑最大的杀，把
   llama-server 杀了**（显存 7334MiB → 62MiB），直接搞断了 web.server 的模型后端。
   ⇒ 铁律：**这台机器上不许 float32 整模型加载**；要跑先看 MemAvailable，优先 bf16/量化；
     能用显存里现成的服务就用现成的。
   ⇒ 本版**完全不加载本地模型**：输出模型直接用已在显存里的 llama-server(8790)。

老板的话（本版要验证的三条）：
  1. "专家模型可以跑显卡上，因为输出模型不用很强 —— 这就是为什么要搞一个循环，不用全部算一次出"
  2. "这部分按照 think 标签开始，然后输出模型输出的就是 think 标签后的回答"
  3. "毕竟 CNN 专家是可以看到互相的" ⇒ think 里应该看得到"对话"

本版怎么近似：
  输出模型 = llama-server 的 qwen3-vl-8b（**已在显存里，不额外占内存**）
  专家     = N 个不同温度的采样视角（★ 诚实说明：这是多采样近似，真专家是显存上的 CNN）
  互见     = 把"别的专家上一轮说了什么"拼进 prompt ⇒ 它们看得见彼此
  门控     = 规则（出现"够了/可以答了"或到轮数上限）；真设计里是门控模型
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import TypedDict

端口 = 8790
模型名 = "qwen3-vl-8b"
专家: list[tuple[str, float]] = [("稳", 0.2), ("发散", 0.9), ("挑刺", 0.5)]
最多轮数 = 4
够了的词 = ("够了", "可以答", "想清楚", "结论", "结束")


class 一轮(TypedDict):
    轮: int
    各专家: list[str]
    一致度: float


class 结果(TypedDict):
    日志: list[一轮]
    正式回答: str
    草稿耗时: float
    正式耗时: float


def 问(提示: str, 温度: float, 上限: int = 80) -> str:
    体 = json.dumps({
        "model": 模型名,
        "messages": [{"role": "user", "content": 提示}],
        "max_tokens": 上限,
        "temperature": 温度,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    请 = urllib.request.Request(
        f"http://127.0.0.1:{端口}/v1/chat/completions", data=体,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(请, timeout=180) as r:
        出: dict[str, object] = json.loads(r.read().decode())
    选项 = 出["choices"]
    消息 = 选项[0]["message"]          # type: ignore[index]
    return str(消息["content"]).strip()  # type: ignore[index]


def 跑(问题: str) -> 结果:
    历史: list[一轮] = []
    t0 = time.time()

    for 轮 in range(1, 最多轮数 + 1):
        要说: list[str] = []
        for 名字, 温 in 专家:
            别人的 = ""
            if 历史:
                别人的 = "、".join(
                    f"{e[0]}说「{t}」" for e, t in zip(专家, 历史[-1]["各专家"]) if t
                )
            提示 = (
                f"你在一个多专家小组里，一起想这个问题：{问题}\n"
                f"你是「{名字}」这个视角。"
                + (f"刚才别人说：{别人的}\n" if 别人的 else "")
                + "只说你这一轮的想法，一句话，20 字以内。别下结论，别客套。"
            )
            要说.append(问(提示, 温, 60))

        字集 = [set(t) for t in 要说 if t]
        一致 = (len(set.intersection(*字集)) / len(set.union(*字集))) if len(字集) >= 2 else 0.0
        历史.append({"轮": 轮, "各专家": 要说, "一致度": round(一致, 3)})

        if any(any(w in t for w in 够了的词) for t in 要说):
            break

    草稿耗时 = time.time() - t0

    # ★ 正式回答：think 之后，输出模型输出的一段（一次出）
    t1 = time.time()
    think文本 = "\n".join("第%d轮：" % h["轮"] + "；".join(h["各专家"]) for h in 历史)
    正式 = 问(
        f"问题：{问题}\n\n下面是你们的思考过程：\n{think文本}\n\n"
        "现在只给正式答案，别重复思考，直接回答。",
        0.2, 120,
    )
    正式耗时 = time.time() - t1

    return {"日志": 历史, "正式回答": 正式, "草稿耗时": 草稿耗时, "正式耗时": 正式耗时}


if __name__ == "__main__":
    for 题 in ("根分区还剩多少", "加盐提浓度"):
        print(f"\n{'═' * 64}\n【问题】{题}\n")
        print("<think>")
        r = 跑(题)
        for h in r["日志"]:
            print(f"  第{h['轮']}轮　一致度 {h['一致度']}")
            for (名, _), 说 in zip(专家, h["各专家"]):
                print(f"    {名}：{说}")
        print("</think>\n")
        print(f"【正式回答】{r['正式回答']}")
        次 = len(专家) * len(r["日志"])
        print(f"\n【账】think {len(r['日志'])} 轮 {r['草稿耗时']:.1f}s"
              f"（{len(专家)}专家×{len(r['日志'])}轮={次} 次调用）"
              f"　正式 {r['正式耗时']:.1f}s（1 次调用）")

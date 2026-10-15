"""小米 MiMo —— 主线在用的那家。

★ 已知产出侧习惯（都是真踩过的，别删）：

1. **整段回答被包进 ```json 围栏** —— 2026-10-11 作业那轮：过程行跑完了、没有答案、
   存档也没这条（老板原话"坏了又是 bug"）。这个习惯**不在这里处理**：任何模型都可能干，
   兜底归外壳（`parser/shell.py` 的 `把关`）。放这儿是因为"先归到某家名下、攒样本"更有用。
2. **原生工具调用是 XML 那套**：`<tool_call><parameter=command>…</parameter></tool_call>`
   —— 标记的识别与清洗在 `native_marks.py`，抠命令在 `exec_agent.extract_calls`。
   那两处是**刻意不分家**的（安全起见哪家的标记都清），这里不重复一份，免得两处打架。

样本：`parser/samples/mimo.jsonl`
"""

from __future__ import annotations

from parser.adapters.shape import 适配件


def _特化(正文: str) -> tuple[str, str]:
    """MiMo 现在不需要在这里动正文 —— 上面两条各有归属（见模块注释）。"""
    return 正文, ""


件 = 适配件(
    家族="mimo",
    已知产出侧习惯=(
        ("整段回答被包进 ```json 围栏", "2026-10-11 作业那轮：过程跑完、没答案、存档也没这条"),
        ("原生工具调用是 XML 那套 <tool_call>…", "标记清洗在 native_marks.py；抠命令在 exec_agent"),
    ),
    特化=_特化,
)

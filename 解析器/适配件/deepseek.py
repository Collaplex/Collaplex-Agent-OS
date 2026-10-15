"""DeepSeek —— 外援（和被交办的活）在用的那家。

★ 已知产出侧习惯（都是真踩过的，别删）：

1. **DSML 标记族**：标记本体 = 全角竖线×2 ＋ `DSML` ＋ 全角竖线×2。
   2026-10-09 真踩过：它一接手主线，产出里就拖着一串 DSML 闭合标记进了语料（那时"炸了"）。
2. **官方 chat_template 那套工具调用标记**：跟 DSML 同形的坑（照它自己 tokenizer_config 里
   的模板渲染出来的那套）。
   另外还有 `<｜…｜>` 一类（竖线包标签）的同族写法。

这两条**不在这里处理**：识别与清洗在 `native_marks.py`（`DSML_CALLS_PATTERN` /
`官方模板` 那族），抠命令在 `exec_agent.extract_calls`。那两处刻意不分家 ——
安全起见别家标记一律清，这里不重复一份，免得两处打架（改一处、另一处没改＝玄学 bug）。

样本：`解析器/样本/deepseek.jsonl`
"""

from __future__ import annotations

from 解析器.适配件.形状 import 适配件


def _特化(正文: str) -> tuple[str, str]:
    """DeepSeek 现在不需要在这里动正文 —— 标记那两条归 native_marks / exec_agent（见模块注释）。"""
    return 正文, ""


件 = 适配件(
    家族="deepseek",
    已知产出侧习惯=(
        ("DSML 标记族（全角竖线×2 + DSML + 全角竖线×2）", "2026-10-09 落进语料那次；清洗归 native_marks.py"),
        ("官方 chat_template 那套工具调用标记 / <｜…｜> 同族", "与 DSML 同形的坑；清洗归 native_marks.py"),
    ),
    特化=_特化,
)

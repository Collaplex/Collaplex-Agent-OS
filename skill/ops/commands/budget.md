# 上下文与记忆预算 · 40% 那条线

**用途**：每轮喂给模型多少 token 是**程序算**的，不是模型自己看着办。记忆能塞多少由预算决定。

**口径（老板定的）**
- 预算 = **模型总上下文 × 40%**（`config/sub_agent.json` 的 `budget.fallback_context_window` × `skill_ratio`）
- 再减 `output_reserve`（给输出留的）+ `readonly_reserve`（主 skill 全文 + 当前问题）⇒ 剩下的才是**记忆可用**
- ★ **窗口是每次向 API 要的**：先问 OpenAI 兼容 `/v1/models` 的 `max_model_len` / `context_length`，再问 llama.cpp `/props` 的 `default_generation_settings.n_ctx`

**怎么量**
- 跑一轮看界面那行尾缀：`[子agent] 查询 N 条 · 记忆 M 条 · skill X 字符` 与 `记忆上限 N`
- 离线数 token：`./.venv/bin/python 算token.py <文件|文本> --在线`（在线那一发跟 API 报的 prompt_tokens 对一下）
- 看窗口现取值：`sub_agent.current_context_window()`

**备注**
- ★ **小窗口模型会把"记忆名额"悄悄夹到 0**：16384 窗口下 `6553 − 4000 − 2554` 是负数，被 `max(0)` 全裁掉 —— 界面上照样打"记忆 N 条"，其实一条都没进上下文。**换模型/换窗口后必须复量那个「记忆上限」**（实测 16384 → 0，32768 → 6537）。
- ★ 追问里的"刚才那个数"这类指代**靠"最近 4 轮原文直接进上下文"**兜，不靠向量检索（纯指代查询在库里排不进 top_k）。

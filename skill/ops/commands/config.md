# 配置都在哪 · 谁管什么

**用途**：改行为前先知道该动哪个文件（**很多是老板亲手调的，动之前先问**）。

**`.env`（项目根，模型调用的唯一来源）**
- 主线：`OPENAI_BASE_URL` / `OPENAI_MODEL` / `OPENAI_API_KEY`（主 agent / exec / 子 agent 共用这一套）
- 可选分挂：`EXEC_*`、`SUBAGENT_*`（写了就用它，没写就回落主线）
- 向量：`EMBEDDING_BASE_URL` / `EMBEDDING_MODEL`（跟主线走哪家无关）
- 记忆库：`RAG_PG_DSN`　模型目录：`COLLAPLEX_MODELS`
- 外援/交叉验证：`DEEPSEEK_*` / `MIMO_*`（跟主线无关，删主线几行不影响它）

**`config/`（配置区，代码不写死）**
- `agent.json`　skill 路径 / 超时 / 生成上限 / 黑名单 / 宽目标名单 / **界面文字**（`ui.*`）
- `sub_agent.json`　检索参数 · `budget`（上下文与记忆预算）· `prompts`（提示词登记）· `skills` 开关 · `skill_retrieval.不可交办`
- `think_routing.json`　思考路由（哪种任务才开思考 + 各家方言）· `outsource_trigger.json`　外援自动触发判据 · `parsing.json`　模型家族关键词
- `skills/*.md`　各内部步骤的提示词（plan / judge / pick / exec / nudge / wrapup + 清洗三份）—— ★ 这些是**内部零件**，放 config 不放 `skill/`（否则会被当成可交办的能力挑走）

**`skill/<名>/resources/*.json`**：那个 skill 自己的配置（开关 / 阈值 / 价目 / 参数），如 `skill/outsource/resources/outsource.json`、`skill/rag/resources/embed.json`。

**备注**：设置页能改的就是这些（**接口**写 `.env`，改前自动备份到 `state/env-backup/`；**开关**写各自 json，每轮现读不用重启）。写入必须**逐字节精确**（只替换目标字面量、不重排 JSON），且**只递交真改过的项**。

# 任务编排 · 先攒清单再逐条推进

**用途**：一轮里要干的活先攒成**活儿单**，再一件件推进；推完自己收工。清单落冷库 PG 表 `orchestra`（按对话分行），web 上显示在输入框上面。

**用法**
- 立单（从 stdin 收条目数组，整份盖掉这一对话原来的单）：
  `echo '[{"说明":"勘察落点","做法":"grep main.py","判据":"指出行号"}]' | ./.venv/bin/python skill/orchestra/main.py plan --json -`
- `… list` 看单（逐条：序号 状态 说明 / 产出）
- `… next --json` 下一件该干的（先「在做」后「待做」）
- `… doing 2` / `… done 2 --产出 "skill 写完, CLI 通了"` / `… retry 3` / `… finish`（收工撤单）
- 对话id：`--对话 X` 或环境变量 `COLLAPLEX_CHAT_ID`（默认 `cli`）

**备注**
- ★ **判断归主 agent**：干活的模型不许自判自己干完没有；重试 3 次到顶标「卡住」留痕。
- 每推完一件就往「待注入」（`pending_injection.py`）丢一条，把主 agent 叫回来推下一件；全好了自动收工 —— web 上那块面板自己消失。
- 清单逻辑在仓根 `manifest.py`（框架侧），`skill/orchestra/main.py` 只是它的命令行；账（exec 次数 / 重策划次数）在库表 `对话账`。
- ★ **一轮只起一个 exec 任务**是编排类 skill 的硬前提（同时改同一批行会打架）。

# skill 清单 · 有哪些、怎么被挑中

**用途**：`skill/` 下每个目录就是一个 skill（每块自己有 `SKILL.md` + `metadata.json` + 代码）。

**现有的（问什么进哪个）**
- `seek`：主 agent 的提示词本体（哪些算"手头没有的能力"，只答话不干活）
- `rag`：资料检索（三层记忆 + 清洗 refine）
- `skill_search`：按问题挑 skill（扫所有 SKILL.md 的 frontmatter）
- `linux` / `kali`：本机操作 / 安全检查（命令库 + 检索件）
- `file`：读写代码文件（carve 的结构化读写）
- `math`：算数（Python 真算，模型不许心算）
- `search`：联网搜索（真浏览器抓页）· `vision`：看图
- `timer`：定时/闹钟 · `orchestra`：任务编排清单
- `outsource`：外援（摇云端强模型）· `mtp`：交叉验证（多家并排挑分歧）
- `ops`：**这份手册**（系统自己怎么用、怎么维护、怎么排错）

**怎么被挑中（左链）**
- 语料 = 各 `SKILL.md` 的 frontmatter **原文**，一 skill 一条、不切片 ⇒ 加 skill 不用改代码
- 开关在 `config/sub_agent.json` 的 `skills`（`true/false` 逐个开）；★ **`不可交办`** 名单（`skill_search` / `outsource` / `mtp`）不许派给执行体（派了只能再挑一遍或白花钱）
- 留痕在 `logs/挑技能.jsonl`（问 / 检索词 / 候选分 / 挑中谁 / 声明）

**备注**：★ 加了/改了 skill **必须重扫索引**，否则左链永远看不到它、而且不报错：
`./.venv/bin/python skill/skill_search/main.py index`

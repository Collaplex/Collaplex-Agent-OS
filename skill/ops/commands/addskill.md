# 加一个新 skill · 落地清单

**用途**：一个新 skill = `skill/<名>/` 一个目录。下面漏一条就**静默失效**（左链看不见它、类型检查没查它、文档对不上）。

**目录形状（照 `rag` / `file` / `ops` 抄）**
- `SKILL.md`（frontmatter 必须**单行** name / description / version / trigger_keywords —— skill_search 只认单行；description 就是检索语料，写"什么时候该用它"；正文给被交办方当提示词 = 执行规范）
- `metadata.json`（给程序读：entry / runtime / commands[] / briefing / needs.env / corpus / index / io）· `main.py`（按动作名分发，参数原样递、输出不加工）· `scripts/`（每个件能单独跑）· `resources/*.json`（真配置）· `tests/`（纯逻辑回归 + 真跑冒烟）· `cache/`、`logs/`（运行产物，进 .gitignore）

**必做的接线（漏了不报错，最坑）**
1. ★ **重扫 skill 索引**：`./.venv/bin/python skill/skill_search/main.py index`（改了 description / trigger_keywords 也要再扫）
2. `pyrightconfig.json`：`include` 加新 `.py`（逐文件清单下不加 = 报 0/0 却压根没查它）+ `extraPaths` 加 `skill/<名>/scripts`（兄弟件互相 import 靠它）
3. `.gitignore`：`skill/<名>/cache/`（命令库类还要保证 `commands-index.json` **进库**）
4. 开关：`config/sub_agent.json` 的 `skills` 加一条；花钱/元技能那类要进 `不可交办` 名单
5. 文档：README 四处（目录树 / 快速开始 / Gitea 仓表 / **核心代码量表**）+ CHANGELOG 一条带验收数据
6. `selfcheck.py` 的 `wanted`（"skill 目录齐"那条）按需加名字

**命令库类（`commands/` + 检索件）额外几条**
- 一动作一条 md，**≤800 字符**（超了被切两片、检索到半条）；**别用代码围栏**（会被当块边界）；`commands/` 里**别放 README**
- 检索件 `find` **默认把条目正文打出来**（只给排名表 = 排序白排，exec 还得自己 cat）
- `metadata.json` 声明的 `briefing` 才会被程序预检索；建索引：`skill/<名>/main.py index`（按 hash 复用向量）

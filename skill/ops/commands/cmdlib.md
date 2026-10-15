# 命令库与手册 · 给 exec 精准找到命令

**用途**：exec 不许凭记忆写命令 —— 它写命令前先从**命令库**查该用哪条。本项目有 6 套同形状的库，全部"给一句话 → 回条目全文（用途 / 用法 / 选项 / 示例 / 备注）"：

**用法**
- `./.venv/bin/python skill/linux/main.py find "磁盘还剩多少空间" -n 3`　本机操作（63 条）
- `… skill/file/main.py find "把 add 改成乘法"`　读写代码文件（16 条，carve 的结构化读写）
- `… skill/kali/main.py find "看看证书什么时候过期"`　安全检查工具（15 条）
- `… skill/math/main.py find "月供怎么算"`　算数（12 条）
- `… skill/search/main.py find "网页取正文"`　联网搜索（9 条）
- `… skill/vision/main.py find "看图"`　看图（2 条）
- `… skill/ops/main.py find "清洗怎么跑"`　**这份手册**（就是你现在读的这套），问系统自己怎么用/怎么维护时查它
- 建/更新索引：`… skill/<名>/main.py index`（按 hash 复用向量，只重算改过的条目；`--mode rrf` 可换检索路）

**备注**
- 条目**默认连正文一起打出来**（`-t/--只要表` 关掉）—— 只给排名表，exec 还得自己 `cat` 一遍，等于排序白排。
- ★ 一 skill 一条声明 `metadata.json.briefing` 的，**程序在递交 exec 之前**先跑这条、把条目贴进任务里（`sub_agent.command_library_briefing`）；没声明就不会被预检索。
- ★ 条目 ≤800 字符（超了被切成两片、检索到半条）、**别用代码围栏**（会被当块边界切）、`commands/` 里**别放 README**。加完条目必须重扫该库索引，且 `commands-index.json` 要进 git。

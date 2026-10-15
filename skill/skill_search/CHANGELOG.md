# 变更日志

## 2026-10-05

**新建。** 按 `diagrams/skill-rag-design.drawio` 落地的 skill 检索：
`检索请求 -> 检索描述 skill -> 返回命中的 skill 描述和相对目录`。

- **语料** = 各 skill 的 `SKILL.md` frontmatter（`---` 之间那段 YAML 的原文）。
  一个 skill 一条，**不切片** —— 设计稿写的"skills/index.json：名称 + 描述 + 触发条件"
  在 frontmatter 里本来就有，不用另建一份索引数据
- **`scripts/core.py`**：共用底座（配置 / 请求向量 / 余弦 / 读写索引）。
  从 rag 那套精简出来，去掉切片、两层、格式白名单 —— skill 检索不需要
- **`scripts/index_skills.py`**：扫 `skill/*/SKILL.md`（大小写都认），
  抽 frontmatter 建索引。frontmatter 没变的复用旧向量，每次全量重建
- **`scripts/find_skill.py`**：一句话 -> top-k，返回 `name / description / source / score`。
  交互模式、`--json`、`-n` 都有
- **`main.py`**：统一入口，两个软件 `index` / `find`
- **阈值默认 `null`**：语料只有 3 条，标不出可信阈值，不硬套一个数
- **不 import rag 的代码**：两个 skill 共用同一个向量服务和同一套表结构，
  但代码各自独立，抽走任一都还能跑

实测（3 条语料：`rag` / `seek` / `skill_search`）：

| 查询 | 命中 | 分数 |
|---|---|---|
| 我要查点资料 | `skill/rag` | 0.7015 |
| 这个任务该用哪个技能 | `skill/skill_search` | 0.7342 |
| 帮我一步步想清楚这个问题 | `skill/seek` | 0.5669 |
| 找一份文档里的原文 | `skill/rag` | 0.7107 |

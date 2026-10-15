# 首次部署 · 新机器怎么起

**用途**：装到全新机器上。装完**不启动任何服务、不写配置**，还差三件事 —— 缺哪件 `collaplex-agent 自检` 都会点名（详见项目根 `首次部署.md`）。

**一、记忆库：PostgreSQL + pgvector**
- `sudo apt-get install -y postgresql postgresql-<版本>-pgvector`（Debian 是 `postgresql-17-pgvector`）
- 建角色 / 库 / 扩展：`CREATE ROLE collaplex LOGIN PASSWORD '…';` → `CREATE DATABASE collaplex_rag OWNER collaplex;` → `CREATE EXTENSION IF NOT EXISTS vector;`
- 少 pgvector 建表直接报 `类型 "vector" 不存在`

**二、★ 空库要先建表（有坑，照顺序贴）**
- 为什么不能靠程序自己建：`embed.py` 先**读**表再**建**表，空库上读那步就撞"关系 rag_chunks 不存在" ⇒ 永远走不到建表
- 顺序：① 用项目自己的 `ensure_schema` 建基础表（1024 维）② 补应用要的四列（`对话id` / `对话时间` / `角色` / `来源id`）+ 时间线索引 ③ 跑 `skill/rag/scripts/迁移JSON到PG.py` ④ `skill/search/scripts/corpus.py schema`
- 每一步都幂等，照 `首次部署.md` 整段贴

**三、凭据与模型服务**
- 从 `.env.example` 抄一份填模型/库/外援（本地 llama.cpp 就填 `http://127.0.0.1:8790/v1`）
- 模型服务不在包里：本机用 `./start_models.sh start`，或指向任意 OpenAI 兼容服务

**验收**
- `collaplex-agent 自检`（30 项：配置 / 模型 / 依赖 / 库 / 代码 / 结构 / 定时）
- `printf '你好\n' | collaplex-agent chat`　一问一答，看有没有真回答

**备注**：干净机器上"缺 `DEEPSEEK_*` / `MIMO_*`、缺 `carve`、二层三层库读不到"**属于正常**，不是装坏了。

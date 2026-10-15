# 首次部署（全新机器）

deb 装完**不启动任何服务**，也不替你写配置。要在新机器上真跑起来，还差三件事 —— 缺哪件
`collaplex-agent 自检` 都会点名。

## 一、记忆库：PostgreSQL + pgvector

两层记忆（二层热 RAG / 三层冷 RAG）落在 **PostgreSQL** 的 `rag_chunks` 表，向量列用的是
**pgvector** 类型 —— 少这个扩展，建表直接报 `类型 "vector" 不存在`。

```bash
sudo apt-get install -y postgresql postgresql-<版本>-pgvector      # Debian: postgresql-17-pgvector
sudo -u postgres psql -c "CREATE ROLE collaplex LOGIN PASSWORD '自己定';"
sudo -u postgres psql -c "CREATE DATABASE collaplex_rag OWNER collaplex;"
sudo -u postgres psql -d collaplex_rag -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

## 二、★ 空库要先建表（这块有坑，照着贴）

**为什么不能靠程序自己建**：`embed.py` 先 `store.load_existing()` **读**表（第 405 行），
再到 `store.ensure_schema()` **建**表（第 430 行）—— 空库上读这一步就撞 `关系 "rag_chunks" 不存在`，
于是**永远走不到建表那步**。也就是说：代码里的建表函数是好的，但顺序上自举不起来（自检里
「记忆 检索失败」、日志里「嵌入失败」都是它）。

**照这个顺序贴一遍就通了**（三步都幂等）：

```bash
cd /usr/share/collaplex-agent-os

# ① 建基础表（用应用自己的 ensure_schema，1024 维 = Qwen3-Embedding-0.6B）
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "."); sys.path.insert(0, "skill/rag/scripts")
from dotenv import load_dotenv; load_dotenv(".env")
import store, refine
cfg = refine.rag_config(); conn = store.connect(cfg)
store.ensure_schema(conn, cfg, 1024); conn.commit()
print("rag_chunks 就绪")
PY

# ② 补应用要用的四列 + 时间线索引（照 skill/rag/scripts/ingest_history_layer.py 的 加列()）
#    这几列 store.py 会读会写，但 ensure_schema 不建 —— 不补就是 "字段 对话id 不存在"
sudo -u postgres psql -d collaplex_rag <<'SQL'
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS "对话id" text;
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS "对话时间" timestamptz;
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS "角色" text;
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS "来源id" text;
CREATE INDEX IF NOT EXISTS "rag_chunks_时间线" ON rag_chunks ("对话id","对话时间");
SQL

# ③ 让迁移脚本把该补的补齐（幂等；它同时会认领老 JSON 索引，没有就写 0 条）
.venv/bin/python skill/rag/scripts/migrate_json_to_pg.py

# ④ search skill 自己的表（search_hot / search_corpus，1024 维）
.venv/bin/python skill/search/scripts/corpus.py schema
```

> ★ 建议：`ensure_schema` 与读表的顺序问题值得在代码里修一次（比如在读之前先
> `CREATE TABLE IF NOT EXISTS`，或把 `ensure_schema` 提到 `load_existing` 前面），
> 那样新机器就不用照这份文档手工建表了。

## 三、凭据与模型服务

```bash
sudo -u <你的用户> cp /usr/share/collaplex-agent-os/.env.example /etc/collaplex-agent-os/env
# 填：OPENAI_BASE_URL / OPENAI_MODEL / OPENAI_API_KEY（本地 llama.cpp 就填 http://127.0.0.1:8790/v1）
#     EMBEDDING_BASE_URL / EMBEDDING_MODEL（嵌入服务，向量维度必须与建表时的 1024 一致）
#     RAG_PG_DSN=postgresql://collaplex:口令@127.0.0.1:5432/collaplex_rag
#     DEEPSEEK_* / MIMO_*（只有 skill/mtp、skill/outsource 用，不填那两个 skill 会报缺）
```

模型服务不在包里（本地 llama.cpp 用项目里的 `start_models.sh`，或指向任意 OpenAI 兼容服务）。

## 四、验收

```bash
collaplex-agent 自检                     # 30 项：配置/模型/依赖/库/代码/结构/定时
printf '你好\n' | collaplex-agent chat   # 一问一答，看有没有真回答
```

自检里这三条在**干净机器上属于正常**，不是装坏了：

| 自检项 | 为什么 |
|---|---|
| 缺 `DEEPSEEK_*` / `MIMO_*` | 付费外援，按需再填 |
| 缺 `carve` | file skill 的外部工具，只影响它那几条命令 |
| 二层/三层库"读不到" | 库刚建还是空的（跟上面第 ② 步有没有做也有关） |

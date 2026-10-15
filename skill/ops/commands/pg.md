# 记忆库 · PostgreSQL 与两个实例

**用途**：记忆库用的是 **PostgreSQL**（向量列用 **pgvector**）；三层记忆（`tier` 1/2/3）全落在那张 **PG 表** `rag_chunks` 里，连接串是项目根 `.env` 的 `RAG_PG_DSN`。它跟模型一样**不是开机自启**。

**用法**
- 起（系统簇）：`echo <sudo密码> | sudo -S pg_ctlcluster 18 main start`
- 判活：`pg_lsclusters`（18-main 要 `online`）+ 数一下各层条数：
  `psql -h /var/run/postgresql -U collaplex -d collaplex_rag -Atc "select tier, count(*) from rag_chunks group by tier order by tier"`
- 连接串形态：`host=/var/run/postgresql dbname=collaplex_rag user=collaplex password=…`

**备注**
- ★ **两个 PG 实例别混**：系统实例（`/var/run/postgresql`，5432）才有 `collaplex_rag`；用户实例（`~/pgdata/socket`，免密）是老孤儿表。`psql -h <哪个 socket> -l` 一看就知道是哪个。
- ★ PG 没起时的症状**不是"库连不上"**，而是 `psycopg.OperationalError: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed: No such file or directory` —— **socket 文件都不在**。看到这句直接去起 PG，别去查 DSN、别去查表。web 那侧表现为"历史空"，清洗表现为整轮失败。
- 查 DSN 别按 `/` 切（`host=/var/run/postgresql` 里那个斜杠会被切错）。
- ★ 认这几句问法：**"记忆库用的是什么数据库" / "记忆存在哪"** → PostgreSQL（pgvector），表 `rag_chunks`，`tier` 列分三层。

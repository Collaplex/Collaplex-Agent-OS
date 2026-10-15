# 排错对照表 · 症状 → 真因 → 怎么办

**用途**：这套系统"看着坏了"的常见几种。**先按症状对到真因，别按第一直觉查**。

**对照表**
- `psycopg.OperationalError … socket "/var/run/postgresql/.s.PGSQL.5432" failed: No such file or directory` → **PG 没起**（socket 文件都不在，不是 DSN 错、不是表不存在）→ 起系统簇；web 那侧表现为"历史空"，清洗表现为整轮失败
- **记忆 0 条 / 问到本机情况开始编**（把本机答成"虚拟机"、把热库答成"冷冻库"）→ **嵌入服务 :8199 没起**（检索抛错被吞成"检索不到候选"→ 回落自己答）→ 起向量模型；`main.py` 的 preflight 会把这条说出来，看不到警告等于没做
- **加了 skill / 改了 description 后检索不到它** → **索引没重扫**（静默失效，不报错）→ `skill/skill_search/main.py index`（命令库则 `skill/<名>/main.py index`）
- **模型加载失败、日志只报显存不足** → **旧的那份没停干净，两份权重抢一块 8G 卡**（不是模型坏了）→ 停完必查 `pgrep -af llama-server` + `ss -ltnp | grep -E ':(8790|8199)'`，按 `/proc/<pid>/cmdline` 确认归属再杀
- **一问就 401 / 网关报"无效的 API key"** → key 与端点不匹配（网关是单 key 派发）→ 比 `.env` 的 KEY 与网关 `state/keys.json`；云端就看 401（Key 不对）/ 403（被拒）
- **一轮过程跑完了，但没答案** → 模型把**整段回答塞进了末尾那个 json 围栏** → `main.捞正文()` 按键把内容捞回来端出来（不许让一轮问答静默消失）
- **exec 交回的是一篇"该用哪个 skill"的理由书、用户问的一个字没答** → 派活派到了**元技能**（`skill_search` / `outsource` / `mtp`）→ 看 `config/sub_agent.json` 的 `不可交办`；判据：那一轮 `logs/exec/` 里只有一条命令、且与某 skill 的 SKILL.md 逐字一致
- **长跑"看着断了"** → 见"清洗的症状与坑"那条（日志增量、心跳没收尾、算力跑到云上三种）。
- **端口能握手但应用层全死**（SSH banner 超时 / HTTP 无响应）→ 机器**内存 commit 100% + 可用只剩几百兆**的僵死（云服上真发生过；真凶是 `vm.swappiness=0` 死磕回收）→ 判死活必须**打 HTTP**，别只看端口；处置见运维档案。

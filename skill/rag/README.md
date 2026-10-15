# rag — 资料检索

一个自包含 skill：**查询进，原文片段出**。只读，不做推理、不做总结。

## 目录

```
skill/rag/
├── SKILL.md            给模型看的说明书（什么时候调 / 怎么调 / 返回什么）
├── metadata.json       给程序读的元信息（入口、命令、依赖）
├── main.py             统一入口（唯一露在 scripts/ 外面的东西）
├── scripts/            代码区：全部实现 + skill 自己管的两层库
│   ├── chunker.py      切片
│   ├── store.py        索引存取层：PostgreSQL(pgvector) / JSON 双后端
│   ├── embed.py        切片 → 向量 → 落库
│   ├── search.py       单层检索
│   ├── recall.py       两级检索
│   ├── refine.py       清洗（读回原话 → 抽概述/知识/别名 → 下沉冷库）
│   ├── embed_server.sh 向量服务起停
│   ├── vector-index.json  二层热库（仅 store.backend=json 时用）
│   ├── memory-index.json  三层冷库（仅 store.backend=json 时用）
│   └── _deprecated/          早期版本，别用
├── resources/
│   ├── embed.json      算法参数 + 两层定义 + 命中阈值 + 别名路
│   └── alias.json      别名表（清洗管线产出，检索第二路用）
├── examples/           真实调用样例
├── tests/              检索质量回归用例
├── README.md
└── CHANGELOG.md
```

## 数据流

两层库，共用同一套切片/向量逻辑：

```
                   ┌─ 二层 · 热 RAG（原始未清洗）  rag_chunks.tier=2 ─┐
文件 --切片--> 块 --┤                                                     ├--> 余弦排序 --> 原文
                   └─ 三层 · 冷 RAG（完整记忆与知识）rag_chunks.tier=3 ─┘
```

落点由 `store.py` 决定：默认 PostgreSQL（pgvector，向量留库、走 HNSW），`store.backend=json` 时退回
`scripts/vector-index.json` / `memory-index.json`（全量读内存、numpy 暴力比）。业务逻辑两边一样，换后端零改动。

检索走 `recall.py`：**先查二层，top1 相似度 ≥ 阈值就直接返回；不命中才落到三层**。
对应 `diagrams/rag-memory.drawio`：

```
模型调用 --no--> 二层rag --yes--> 模型调用
                   |
                  no
                   v
                 三层rag --yes--> 模型调用
```

## 跑法

```bash
.venv/bin/python skill/rag/main.py                          # 列出所有功能
.venv/bin/python skill/rag/main.py chunk <文件>               # 看切片长什么样
.venv/bin/python skill/rag/main.py embed <文件或目录> ...      # 建二层(热 RAG)索引
.venv/bin/python skill/rag/main.py embed <知识目录> --tier 3   # 建三层(冷 RAG)索引
.venv/bin/python skill/rag/main.py search "查询" -n 5         # 单层检索(默认二层)
.venv/bin/python skill/rag/main.py recall "查询" -n 5         # 两级检索: 二层 -> 三层
```

`main.py` 只负责找到功能件、把参数原样递过去 —— 输出不截断不加工，退出码原样带回。
每个功能件也能**单独跑**（`.venv/bin/python skill/rag/scripts/search.py "查询"` 一样能用）。

## 清洗管线（二层 → 三层）

```bash
.venv/bin/python skill/rag/scripts/refine.py            # 立刻清一次
.venv/bin/python skill/rag/scripts/refine.py --看守      # 常驻, 到点自己清
.venv/bin/python skill/rag/scripts/refine.py --干跑      # 只看要清什么, 不动库
.venv/bin/python skill/rag/scripts/refine.py --待重洗    # 只看洗不了的账
.venv/bin/python skill/rag/scripts/refine.py --回填      # 把三层里的半成品补洗一遍
.venv/bin/python skill/rag/scripts/refine.py --安静      # 没活干不出声(cron 用)
```

三步顺序**不能变**：① 原文**原样**搬进三层 → ② 清洗（概述 / 知识 / 别名）→ ③ 清空二层 + 删语料。
cron 每分钟用 `--安静` 拉一次（`flock` 防重）。

### 洗不动的时候怎么办（2026-10-06 修）

实测踩过：`②` 读不到 corpus 文件时旧代码直接放过（"原文已进三层, 不丢"），
结果那批**只有原文、没有概述/知识/别名**，没重试也没账 —— 三层里留下 5 批 22 片半成品。
现在：

- **文件没了先回填**：`①` 是"一字不改"搬的，三层里那批 `kind='原文'` 就是原文 ——
  `②` 拿它接着洗（日志标 `[从三层原文回填清洗]`），重复问同一句话不会再留半成品。
- **两边都空才记账**：写进 `state/refine-待重洗.json`，日志明说，不许静默当"洗过了"；
  哪轮洗成了自动从账上划掉，`--待重洗` 只看账。
- **旧账用 `--回填` 收尾**：扫"有原文、没概述"的 source，拿三层原文补洗。

### 看不到进度的问题（同批修）

- 每轮开头打 `[2026-10-06 18:25:13]`，收尾带耗时 —— 日志是 cron 追着写的，没时间戳对不上账。
- 每趟（**含没活的时候**）落一次心跳 `state/refine-心跳.json`：
  日志只在有活时才有行，平时靠心跳看它到底还在不在跑。

## 向量服务

```bash
.venv/bin/python skill/rag/scripts/embed_server.sh start|stop|status|log
```

llama.cpp + `Qwen3-Embedding-0.6B-Q8_0`，端口从 `.env` 的 `EMBEDDING_BASE_URL` 解析，只定义一处。

## 配置在哪

| 什么 | 在哪 |
|---|---|
| 模型凭据 | 项目根 `.env`：`EMBEDDING_BASE_URL` / `EMBEDDING_MODEL`（跨 skill 共用，不放这儿） |
| 算法参数 | `resources/embed.json`：切片大小 / 批量 / 格式白名单 / 排除目录 / 累积模式 / 别名路开关 |
| 两层定义 | `resources/embed.json` 的 `tiers` 段：每层名字 + 索引路径；`tier` 是默认层 |

## 命中阈值

`resources/embed.json` 的 `hit_threshold` = **0.53**，实测标定（Qwen3-Embedding-0.6B + 338 条库）：

### 别名路（检索的第二路）

检索不只走向量 —— 查询里**字符串包含**某个概念时，还会把该概念的别名池各检索一遍，
按 index 合并去重保留最高分。别名表是清洗管线从对话里产出的（`scripts/alias.json`），
**不嵌向量**，这条路几乎不花算力。

补的是语义盲区：用户问「网络设备」，语料里答的是「软路由 / 交换机」。
实测同一条查询，关别名 top1 = 0.5178（未命中），开别名 top1 = 0.8163（命中）。

参数在 `resources/embed.json` 的 `alias` 段：`enabled` / `base_k` / `max_aliases` / `per_alias`。

| | top1 相似度 |
|---|---|
| 相关查询（6 条） | 最低 **0.559**，均值 0.659 |
| 无关查询（6 条） | 最高 **0.491**，均值 0.375 |

中间这条缝就是阈值。**样本只有 12 条、余量约 ±0.04** —— 换模型或语料规模大变后必须重标，
做法见 `tests/eval.yaml` 末尾。回归用例就在 `tests/`。

## 索引表结构

```json
{"meta": {...}, "items": [{"index": 0, "vector": [...1024维...], "text": "原文", "hash": "切片哈希", "source": "源文件"}]}
```

- `hash` = 切片文本 sha256 前 16 位，用于增量判重
- `source` = 源文件（相对项目根的路径，不在项目里就存绝对路径）。**累积模式按它做替换**：
  本次碰过的源文件，旧切片整批清掉再放新的 —— 文件改了/删了都不留残片
- 累积模式：单跑一个文件不会覆盖整个索引（`mode: accumulate`，可切 `replace`）
- 格式白名单外的文件 → 默认 **整批拒绝执行**，退出码 2，索引不做任何改动
  （`on_unsupported` 设成 `skip` 就只跳过那些文件，适合直接喂整个目录）

## scripts/_deprecated/

早期版本，已无人引用，保留备查（不要直接拿去跑）：

- `rag.py` — 简版 Markdown 扫描器 `split_markdown_scanner`，功能已被 `chunker._split_markdown` 覆盖
- `indexer.py` — 转向量毛坯；依赖 `sentence-transformers`（本机未装），字段结构已过时，被 `embed.py` 取代

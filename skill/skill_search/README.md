# skill_search — skill 检索

一句话进去，**该用哪个 skill** 出来 —— 连同它的描述和相对目录。

## 目录

```
skill/skill_search/
├── SKILL.md            给模型看的说明书（什么时候调 / 怎么调 / 返回什么）
├── metadata.json       给程序读的元信息（入口、命令、语料定义）
├── main.py             统一入口（唯一露在 scripts/ 外面的东西）
├── scripts/            代码区：实现 + skill 自己管的库
│   ├── core.py           共用底座：配置 / 请求向量 / 余弦 / 读写索引
│   ├── index_skills.py   扫 skill 目录，建/刷新索引
│   ├── find_skill.py     检索，返回描述 + 相对目录
│   ├── embed_server.sh   向量服务起停（跟 rag 同一个服务）
│   └── skill-index.json  库（skill 自己管）
├── resources/
│   └── skill_index.json  配置（语料根 / top_k / 阈值 / 批大小）
├── examples/           真实调用样例
├── tests/              回归用例
├── README.md
└── CHANGELOG.md
```

## 数据流

```
skill/<名>/SKILL.md 的 frontmatter ──> 一个 skill 一条 ──> 向量 ──> skill-index.json
                                                                            │
                         一句话 ──> 向量 ──> 余弦排序 ──> top-k {描述, 相对目录, 分数}
```

**不切片。** 一个 skill 就是一条 —— frontmatter 本来就短，切了反而丢上下文。

## 语料是 frontmatter，所以 frontmatter 就是检索信号

取 `<skill>/SKILL.md` 开头 `---` 与 `---` 之间那段 YAML 的**原文**。

这意味着：`description` 和 `trigger_keywords` 写得越具体，检索越准。
想加一个 skill 进去？**不用改任何代码** —— 在 `skill/` 下建目录、写 `SKILL.md` 带 frontmatter，
跑一次 `index` 就能被检索到。

## 怎么跑

```bash
# 1. 向量服务（跟 rag 共用，起一次就够）
.venv/bin/python skill/skill_search/scripts/embed_server.sh start

# 2. 建/刷新索引
.venv/bin/python skill/skill_search/main.py index

# 3. 检索
.venv/bin/python skill/skill_search/main.py find "我要查点资料"
.venv/bin/python skill/skill_search/main.py find "..." -n 5 --json
.venv/bin/python skill/skill_search/main.py find          # 交互模式
```

## 配置（`resources/skill_index.json`）

| 键 | 含义 |
|---|---|
| `skill_root` | 语料根，留空 = 本项目 `skill/`（即本 skill 的上一级） |
| `index` | 库文件路径，相对本 skill 目录 |
| `exclude_dirs` | 扫的时候跳过的目录名 |
| `top_k` | `find` 默认返回几条 |
| `hit_threshold` | `null` = 不过滤（默认）；给数字就只返回 ≥ 它的 |

## 索引表结构

```json
{"meta": {...}, "items": [{"index": 0, "vector": [...1024维...], "text": "frontmatter 原文", "hash": "切片哈希", "source": "skill/rag"}]}
```

- `source` = skill 的**相对目录**，正是返回给调用方、让它去读 `SKILL.md` 正文的那个路径
- `hash` = frontmatter 原文 sha256 前 16 位。**没变就复用旧向量**，改过的才重算
- 每次 `index` **全量重建**（语料就几个，省得留残片）

## 跟 rag 的关系

两个独立的 skill，共用两样东西：

- **同一个向量服务**（`:8199`，端口从 `.env` 的 `EMBEDDING_BASE_URL` 解析）
- **同一套表结构**（`index / vector / text / hash / source`）

`core.py` 是从 rag 那套实现里精简出来的（去掉切片、两层、白名单 —— skill 检索不需要）。
刻意**不 import rag 的代码**：skill 各自独立，抽走任一都还能跑。

## 阈值

`hit_threshold` 默认 `null`（不过滤）。

实测（3 条语料，12 条探针）：相关最低 **0.5416** / 无关最高 **0.4440** —— 交界在 **0.49** 附近，
分离度 ±0.05，比 rag 那边（±0.03）还宽。**但样本是 3 个 skill 不是 3 个文档**：
skill 多了之后"总有最近的一个"，无关侧会被推上去，这个数必须重标，所以默认不设。

想现在就开：把 `resources/skill_index.json` 的 `hit_threshold` 设成 `0.49`，代码不用动。

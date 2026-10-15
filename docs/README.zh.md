```
                 ●───●───●
                / \ / \ / \
               ●───●───●───●
                \ / \ / \ /
                 ●───●───●
                      │
        ╭─────────────┴─────────────╮
        │  COLLAPSE · COMPLEX · AI  │
        ╰─────────────┬─────────────╯
                      ▼
   ██████  ██████  ██     ██     █████  ██████  ██     ██████ ██  ██
  ██      ██    ██ ██     ██    ██   ██ ██   ██ ██     ██      ████
  ██      ██    ██ ██     ██    ███████ ██████  ██     ████     ██
  ██      ██    ██ ██     ██    ██   ██ ██      ██     ██      ████
   ██████  ██████  ██████ ██████ ██   ██ ██      ██████ ██████ ██  ██

      █████  ██████  ██████ ███    ██ ████████
     ██   ██ ██     ██     ████   ██    ██
     ███████ ██ ███ █████  ██ ██  ██    ██
     ██   ██ ██  ██ ██     ██  ██ ██    ██
     ██   ██ █████ ██████ ██   ████    ██
```

# Collaplex Agent

**程序管记忆，模型管推理。** —— 一个把上下文从模型手里拿回来、交给程序组装的 Agent。

[![Python](https://img.shields.io/badge/python-3.11%2B-4ade80?style=flat-square)](#快速开始)
[![依赖](https://img.shields.io/badge/直接依赖-3%20个-4ade80?style=flat-square)](#快速开始)
[![许可](https://img.shields.io/badge/license-AGPL--3.0-blue?style=flat-square)](../LICENSE)

---

## 〇、它是什么

一个**跑在本地的 Agent 运行时**，三个常驻角色：

| 角色 | 干什么 |
|---|---|
| **主 agent** | 判断 + **声明**（要交办什么活），不自己动手 |
| **子 agent** | 拦住问题 → 分析 → 检索记忆 → 按标准拼成 skill |
| **执行 agent** | 拿声明 + 检索到的 skill，**带手**去跑命令 |

配上**两层记忆库**（热库装原话、冷库装清洗后的知识）和一套**声明式 skill**（`SKILL.md` 给模型看，`metadata.json` 给程序读）。

跑起来就是一个终端对话界面，流式输出、中文、可 Ctrl-C：

```bash
./selfcheck.py          # 30 项自检通过就直接进主程序
```

## 一、为什么做（痛点）

主流 Agent 框架把**上下文**当成模型的私事：模型自己总结、自己取舍、自己记住。这带来三个税：

| 税 | 怎么来的 | 代价 |
|---|---|---|
| **压缩税** | 窗口满了让**模型**总结历史 | 每次压缩都烧 token，而且**越压越糊涂** —— 模型不知道什么以后还要用 |
| **试错税** | 工具调用靠模型猜参数 | 猜错的调用进上下文，**错误污染**后面所有推理 |
| **噪声税** | 检索结果、历史原文一股脑塞 | 有效 token 占比低，大部分算力在"管自己" |

滚雪球是这样的：**聊几轮 → 压缩 → 丢细节 → 答错 → 再压缩**。到后面模型连自己刚说过什么都记不清。

还有本地部署的现实约束：**8GB 显存跑 14B 模型只剩 8K 上下文**，而一个像样的 Agent 系统提示就要 13K+。靠模型撑窗口，本地根本不可行。

**结论：上下文不该由模型管。** 模型负责"想"，程序负责"记"。

## 二、架构

**一条主线，两条链。**

```
        用户提问
            │
            ▼
    ┌───────────────┐
    │    子 agent    │ ◀── 右链（功能1）：分析 / 检索记忆 / 按标准拼 skill
    └───────┬───────┘
            │ 拼好的 skill
            ▼
    ┌───────────────┐
    │    主 agent    │ ◀── 判断：够不够？要交办什么？ 然后**声明**（不留手）
    └───────┬───────┘
            │ 声明：要干什么
            ▼
    ┌───────────────┐
    │   执行 agent   │ ◀── 左链（功能2）：手在它身上，真去跑命令
    └───────┬───────┘
            │ 产出
            ▼
       入二层热库 ──▶ 下一轮能被检索到
```

### 两层记忆

底层索引的存取走 **`store.py` 抽象层**，后端在 `skill/rag/resources/embed.json` 的 `store` 段选：

| 后端 | 落点 | 什么时候用 |
|---|---|---|
| `pg`（当前） | PostgreSQL 表 `rag_chunks`，`tier` 列分二层/三层 | 要"性能 + 会长大"：向量留在库里走 pgvector HNSW 索引，进程内存与库大小无关 |
| `json` | `scripts/vector-index.json` / `memory-index.json` | 小规模、零依赖：全量读进内存用 numpy 暴力比 |

连接串从环境变量 `RAG_PG_DSN` 读（写项目根 `.env`，密钥不落代码）；`store.connect()` 自己会去补 `.env`，调用方不必各自 `load_dotenv`。

| 层 | 装什么 | 什么时候动 |
|---|---|---|
| **二层 · 热库**（`tier=2`） | 这一轮对话的**原话**，切片后直接嵌向量 | 每次产出，实时追加 |
| **三层 · 冷库**（`tier=3`） | **清洗后**的东西，每条带 `kind`：原文 / 概述 / 知识 | 静默 20 分钟后自动下沉 |

**热库会越积越多，所以必须有下水道**：任务结束 + 静默 20 分钟（或静默 2 小时兜底）→ 后台清洗：

```
① 先复制 —— 热库切片原样搬进冷库（标 kind=原文，一字不改，向量直接复用）
② 再清洗 —— 读回原话，跑三遍小模型抽 概述 / 知识 / 别名
③ 清空热库 —— 只清刚清洗过的那批对话产出，项目语料不动
```

顺序不能变：**先落地，才敢清**。中间任何一步挂了，重跑一次就补上（幂等）。

### 检索的第二路：别名路

向量检索有个盲区：用户问「**网络设备**」，语料里答的是「**软路由**」—— 机器看不出这层对应。

清洗时会顺手产一张**别名表**（`概念 → 其他叫法`，纯字符串表，不嵌向量所以几乎不花算力）。检索时两路并走：

```
查询 ──┬── 第一路：纯向量
       └── 第二路：字符串包含命中概念 → 该概念的别名池各检索一遍
                     │
                     ▼
              按 index 合并去重，保留最高分
```

实测（同一条查询，控制变量）：

| | top1 | 判定 |
|---|---|---|
| 关别名 | 0.5178 | 未命中 |
| **开别名** | **0.8163** | **命中**，召回「软路由是 x86 小主机」 |

### 子 agent 定：主 agent 这轮要不要开思考

思考（长链路推理）**不是全程都该开**。国际基准实测：同一道题开思考，deepseek-flash 的 GSM8K 90.0→85.0、
HumanEval 91.7→83.3，输出 token 却涨 **5.2 倍**；而 Qwen3-VL-8B-Instruct 干脆没有思考模式
（chat template 里 `think` 出现 0 次）。所以开关按**任务**路由，不按模型的全局档位。

三层，先硬后软：

1. **关键词硬规则**（`config/think_routing.json`）—— 命中即定，不花模型调用。
   开：多步数值推理 / 代码生成与调试 / 长链规划 / 多约束。关：检索问答 / 翻译改写 /
   格式转换 / 读写文件跑命令 / 闲聊。
2. **子 agent 分析步兜底**（`config/skills/plan.md`）—— 规则没命中时，模型在这步多输出
   `think` + `reason`，判据写在提示词里（拿不准给 false）。
3. **默认档（保守 = 关）** —— 规则与模型都没结论时用它，且来源会标成「默认」（判定不许静默降级）。

**子 agent 判、主 agent 用**：判定随 `prepare_skill` 的返回值一起交出去，主 agent 按它拼
各家的思考方言（DeepSeek `thinking.type` / llama.cpp `chat_template_kwargs` / MiMo 默认即开），
方言表也在 `config/think_routing.json` 里。**子 agent 自己那六步 JSON 调用永远不开思考** ——
思考会把 JSON 输出撑爆（实测均长 879 token、12/15 题撞满上限）。

### 卡住了就摇人：外援 → 交叉验证（二级），再加自动触发

本地模型答不动时，按**两级**往云端借力；两级都花真钱，所以**默认关**，开关都在配置里，不在代码里。

1. **外援**（`skill/outsource`，一级）—— 摇**一家**强模型干活。默认 DeepSeek（余额宽裕），MiMo 当第二路。
   实测对照（6 道题，本地 GLM 开思考 vs 外援 DeepSeek）：本地 **5/6、396 秒**；外援 **6/6、7.9 秒**、
   总共 **0.00738 元**（一道约 1.2 厘）。→ 它换来的主要是**速度**，真正兜住的是**「要成段、要能跑的代码」**；
   纯推理题本地自己就行，摇了是白花钱。
   ★ 同一批题补跑的**关思考**对照：本地 **3/6 · 45 秒** —— 长推理 3 道错 2 道、一道 0.7 秒，
   **不是"一样准但更快"，是"快但答错"**（`effect_probe.py --思考 关`）。
2. **交叉验证**（`skill/mtp`，二级）—— 外援也不行才用：**同一题问多家**，各答各的，程序判出
   **一致 / 分歧**分组，把材料交回去当参考。★ 它**不替调用方下结论**（哪份对由主 agent 自判），
   也**不另开钱袋子**（家的凭据 / 价目 / 预算 / 记账全沿用外援，流水行用 `来自` 区分）。

**自动触发**（`outsource_hook.py`）—— 不用你喊，程序判「摇不摇」：

- 落点**只有一处**：左链没接住、本来要「回落自己答」那一站。摇来的东西**贴进主 agent 的 skill 里**，
  由它自己综合 / 呈现 —— **不替它下结论**。实测贴了参考那一轮，输入 token **1435 → 2267**。
- 三条判据（`config/outsource_trigger.json`，可调）：**要成段代码** / **左链检索不到** / **卡了明显时间**（默认 45 秒）；
  外加一张**否决词表**（看日志 / 端口 / 重启 / 闲聊 → 不摇）。★ **程序判，不许模型自己说「拿不准」**。
- ★ **「要成段代码」是两道，缺一不摇**：① 强命中词单独命中即真（报错 / 调试 / 重构 / 写代码 / 死锁）
  ② 否则要 **动作词 × 代码名词 同句出现**（写 + 函数、改 + 脚本）。
  原先一层词表时，裸的 `函数` / `写个` / `代码` 也算命中 —— 13 题误触发对照里，边界组
  「解释一下函数和方法」「帮我写个请假条」「代码里的注释用中文还是英文」**3/3 全被误摇**（本地明明答得上）。
  收窄后复测 **误触发 0/10**（探针 `skill/outsource/tests/misfire_probe.py`，不花钱）。
- **接不上就退**：外援空答 / 报错 / 答得太短 → 升交叉验证 → 还不行就**维持原样**（该说没有就说没有），
  绝不静默换成别的东西。
- 记账行带 `来自`（`outsource` 手动 / `hook` 自动 / `mtp` 交叉验证），每次真摇另写一行
  `logs/outsource/触发.jsonl`（判据 / 家 / 金额 / 秒 / 题）—— 以后数误触发率就靠它。

### 目录

```
collaplex_agent/
├── cli.py               ★ 总入口：`collaplex-agent web / 自检 / 模型 / chat` —— 一个命令管住所有启动方式
├── main.py              主程序：对话循环 + 流式渲染 + 末尾 JSON 拦截
├── sub_agent.py         子 agent：检索记忆 / 拼 skill / 上下文预算 / 入二层（分析 / 判断两步都带"上一轮"的上文块）
├── exec_agent.py        执行 agent：声明 → 跑命令（黑名单 + 宽目标 + 复读掐断）
├── outsource_hook.py    ★ 外援自动触发：程序判「摇不摇」（要成段代码 / 左链检索不到 / 卡了明显时间）
├── 定时.py              ★ 定时任务的框架接缝：启动重挂 / 开场取到点的 / 阻塞式就在这一轮里等（读秒吐给界面）
├── 待注入.py            ★ 「下一轮开场说什么」的通道（冷库 PG 表 `inbox`）：定时和编排都往这一个口子丢
├── 清单.py              ★ 编排的活儿单（冷库 PG 表 `orchestra`，按对话分行）+ 账（`对话账`：exec 次数 / 重策划次数）
├── 库.py                ★ 冷库公用层：连接复用 / 文档表 / 执行查询 / `COLLAPLEX_DB_PREFIX` 沙盒前缀
├── native_marks.py      ★ 各家原生工具调用标记（小米 MiMo 的 XML / DeepSeek 的 DSML 方言 / DeepSeek 官方模板那套 <｜tool▁…｜>）：一处认全，exec 抠命令 / 落语料 / 导会话三处共用；另有 StreamFilter（边流边吐时把协议块整段扣住，web 的答案草稿走它）
├── tokenizer.py         ★ 本地分词器：纯 stdlib 复刻那份 tokenizer.json（`~/models/deepseek-v4-tokenizer/`），离线精确数 token —— 上下文预算不再靠"一字符一 token"粗估
├── 算token.py           ★ 算 token 的命令行：文件 / 文本 / 目录 / 超上限标 ⚠ / `--在线` 跟 API 报的 prompt_tokens 对一下
├── watchdog.py          ★ 看门狗：盯 8790 / 8199 / 8791 / PG，挂了拉回来
├── selfcheck.py         30 项自检（过了就直接拉起 main；含定时那 3 项）
├── start_models.sh      拉本地模型（主模型 + 向量模型）
├── 本地兜底.sh          ★ 主路不通 → 自动落本地那支
├── pack_bundle.sh       打"解压即用"包（见 §八）
├── push_gitea.sh        按 skill 拆仓推 Gitea（见 §十一）
├── pyrightconfig.json   类型检查口径（strict；入口列全，新文件按目录自动纳入）
├── icon.txt             ASCII 图标（自检头部打印它）
├── skill/               ★ 程序区：每个 skill 一个目录
│   ├── seek/            SKILL.md —— 主 agent 的提示词（含 `任务结束` 键）
│   ├── rag/             两层记忆检索（chunk / embed / search / recall / **refine**）
│   ├── skill_search/    按问题找 skill（扫所有 SKILL.md 的 frontmatter）
│   ├── linux/           ★ 本机操作：命令库（commands/*.md 63 条）+ 检索件 + **exec 的执行规范**
│   ├── file/            ★ 读写代码文件：命令库（16 条，carve 的结构化读写）+ 检索件 + 同款执行规范
│   ├── math/            ★ 算数：命令库（12 条，算数/方程/矩阵/多项式/微积分/统计/概率/钱/单位/出图/日期）+ 检索件
│   │                    —— 有理数精确(Fraction) + 高精度(Decimal)，ast 白名单求值；★ 模型不许硬算，计算需求一律走这里
│   ├── search/          ★ 联网搜索：命令库（7 条，搜/取/正文/汇总/缓存/状态/截图）+ 真浏览器抓取 + 清洗 + 检索件
│   ├── vision/          ★ 看图：一张本地图片 → 文字（主路云端 / 兜底本地 qwen3-vl-8b）
│   │                    —— 只在要用的时候看一眼；图不寄存（不留库 / 不进会话历史）；两条路都不通就照实说，绝不编
│   ├── timer/           ★ 定时任务：闹钟 + 倒计时。给时长或时刻，到点回来提醒主 agent
│   │                    —— 阻塞式就在这一轮对话里等（逐秒读秒，硬上限 180 分钟），非阻塞式主 agent 先走、到点注入它下一轮；
│   │                       表落**冷库**（PG 表 `timers`，按进程键分行：web/cli 各一行），跨重启重挂 + 过期补一次；★ 它只提醒，不替主 agent 干业务
│   ├── orchestra/       ★ 任务编排：先攒活成立单，再逐条推进（doing/done/blocked/retry/收工）
│   │                    —— 判断归主 agent（干活的模型不许自判自己）；重试 3 次到顶标「卡住」留痕；
│   │                       清单落冷库、每推完一件就往「待注入」丢一条把主 agent 叫回来推下一件；全好了自动收工（web 面板自己消失）
│   ├── outsource/       ★ 外援：卡住了摇云端强模型（默认 DeepSeek）干活（开关默认关 / 预算 + 记账 / ★ 误触发对照）
│   ├── mtp/             ★ 交叉验证：同一题问多家模型，并排给答案 + 挑分歧（只在外援之后用）
│   └── ops/             ★ **这套系统自己的使用与维护手册**（28 条）：起服务 / 网页与设置页 / 模型 / PG / 三层记忆与预算 / 清洗与嵌入 / 命令库与 skill 清单 / 外援·定时·编排·看图·搜索·长活 / 日志 / 自检与看门狗 / 配置 / 加 skill / 打包发布 / 排错对照
├── web/                 ★ 浏览器入口（同一条链）：server / bridge / 启动.py ＋ 自带 tests
│                        —— 编排清单显示在**输入框上面**（`GET /api/清单`，没清单整块 hidden、全好了自己消失）
├── config/              ★ 配置区：不写死在代码里
│   ├── agent.json       skill 路径 / 超时 / 生成上限 / 黑名单 / 宽目标名单 / 界面文字
│   ├── sub_agent.json   子 agent 的检索参数 + 四个角色的提示词
│   ├── think_routing.json      思考路由：哪种任务才值得开思考（三层：硬规则 → 模型 → 默认档）
│   ├── outsource_trigger.json  ★ 外援自动触发：三条判据 + 否决词表（默认关）
│   └── skills/*.md      提示词（plan / judge / pick / exec + 三份清洗）
├── tests/               顶层回归 19 个 + 真跑探针 12 个（见 §五）
├── diagrams/            架构图（4 页）+ 设计稿
└── state/               运行时的账（活动时间 / 清洗心跳 / web 对话存档），不进 git
```

**约定**：`SKILL.md` 给**模型**看（frontmatter + 正文），`metadata.json` 给**程序**读（命令清单）。两库由 skill 自己管，所以也在代码区里。

## 三、架构区别

### vs 第一代：上百节点的超级状态机

想用**确定性**穷举**不确定性** —— 把每条路径都写成节点。结果是路径组合爆炸，异常分支永远举不完，**直接炸**。

> 教训：不确定性只能靠"在有限状态里选"来消化，不能靠穷举。

### vs 第二代：RAG 模拟状态机（`Collaplex-Agent-驱动`）

用 RAG 的读写当状态迁移：`注入 skill → 判断 → 写热库 → 声明取 → 注入 skill → 规划 → 声明执行 → …`

跑通过，本地小模型未开思考 **BFCL 94%**。但 **RAG 一身兼三职**（记忆 / 知识库 / 日志）导致：

- **写入放大** —— 什么都往里写
- **检索噪声** —— 日志和知识混在一起搜
- **流程线性** —— 状态机只能顺着走，不能按需跳
- **定时脆弱** —— 靠 timer 触发，挂了没人知道

> 教训：**一个东西不能既是记忆又是日志**。这就是第三代分两层、并且必须"下沉清洗"的原因。

### vs 主流框架（Hermes / DSH 这类）

| | 主流框架 | 本项目 |
|---|---|---|
| 上下文 | 模型总结 → **压缩税** | 程序归档 → 零 token |
| 工具调用 | 模型试错 → **试错税** | 先检索 skill、主 agent 声明 → 错误不进主线 |
| 记忆 | 压缩后**丢掉** | 下沉冷库，**可检索回来** |
| 检索 | 纯向量 | 向量 + **别名路**（补上位词盲区） |
| 模型 | 绑死一个 | `.env` 一改就换（本地 / 云 API） |
| 平台 | 绑 Linux（碰内核 KV） | 只用 HTTP + 文件，**平台无关** |

**能力边界也诚实说**：Agent 框架跑在推理引擎**之上**，碰不到引擎内部的 KV——所以"双缓冲 KV"这类优化**做不到**，只能靠"稳定前缀 + 程序组装"逼近。

## 四、优势

只列**实测过**的（不是设计目标）：

| # | 优势 | 证据 |
|---|---|---|
| 1 | **上下文按预算分配，不靠"尽量塞"** | 现向 API 要窗口，`skill 预算 = 窗口 × 40%`，扣除输出与只读区余下的才是记忆可用量 |
| 2 | **热库自动落冷库，不会烂在路上** | 端到端实测：热库 377 → 375，冷库 12 → 18，时间戳自动更新，全程 cron 自动触发 |
| 3 | **上位词提问也能召回** | 别名路实测 0.5178（未命中）→ **0.8163**（命中） |
| 4 | **模型可插拔** | `.env` 改 `OPENAI_BASE_URL` 即可切本地 llama.cpp / 云 API，**零代码改动** |
| 5 | **提示词全外置** | `grep '^[A-Z_]*_SYSTEM =' *.py` → **0 处**，全在 `config/skills/*.md` |
| 6 | **错误显式降级，不静默** | 端点不通 / key 不对 / 模型名不对 → 四种明说，不甩 traceback |
| 7 | **自检 30 项可当守门** | `./selfcheck.py` 退出码：全好 `0` / 有错 `1`，可直接接 CI 或启动脚本 |
| 8 | **清洗幂等** | 中途被掐断，重跑一次补上，不重复堆积 |

## 五、核心代码量

**Python 合计 33,661 行 / 138 个**（按目录列全；口径：框架 ＋ 解析器 ＋ 顶层 `tests/` ＋ skill 区 ＋ diagrams ＋ mvp_os，不含 venv / `__pycache__` / `_deprecated` / `state` / `dist` / `build-nuitka` / `vendor` / `web` / `实验`，行数按 `wc -l`）：

```
框架与回归（三个 agent + 总入口 + 自检 + 分词器 + 外援触发 + 看门狗 + 回归/探针）  10,861 行
  sub_agent.py   1,546      检索 / 拼 skill / 预算 / 思考路由 / 入库（含给 exec 的命令库预检索）+ ★ 给分析/判断两步拼"上一轮"的上文块（追问题不断档）+ ★ 检索毛病攒成"这轮检索的实况"塞进主 agent 的 prompt（嵌入挂了不许答"我没有记忆"）
  main.py        1,076      对话循环 / 流式 / ★ 末尾 json 拦截与兜底（`捞正文` 已是同名薄壳 —— 真逻辑在 `解析器/`：整段被围栏吃掉时也把内容捞回来, 绝不留下空答案）/ 递交 exec / ★ 外援自动触发的落点 / ★ 挑 skill 前先剔掉不可交办的件（元技能 · 花钱的）
  selfcheck.py   1,048      30 项自检（配置 / 模型 API GET / skill 依赖 / 库 / 代码 / 结构 / ★ 索引 / ★ 定时）
  tests/         5,055      回归 19 个（复读掐断 / 流式渲染（★ 含"整段被围栏吃掉也要捞回正文"）/ ★ 协议标记边流边吐 / 左链兜底（★ 含"不可交办的件不许派"）/ 清洗兜底（★ 已修 2026-10-11：夹具原来拿 8 维假向量直连生产表 —— expected 1024 dimensions, not 8，整份用例从第一条起全红；现把存储后端钉在 JSON 上，一个字节都不碰生产库）/ 自检依赖 / 思考路由 / ★ 定时接缝 / ★ 外援触发 / ★ DSML 标记 / ★ 官方模板标记 / ★ 本地分词器 / ★ 追问上文 / ★ 作业播报 / ★ 检索降级（把 `EMBEDDING_BASE_URL` 指到死端口：不许整条塌成 0 命中、要落关键词兜底、实况要带出去）/ ★ 库双后端（沙盒前缀 + 连接复用）/ ★ 清洗失败即停 / ★ 清洗并发文件（索引锁：去掉锁当场丢概述）/ ★ 拦截简报（自答那条出口也得带记忆，界面不许假报"记忆 0 条"））
                            ＋ 真跑探针 8 个（多轮 / 搜索四轮 / ★ 看图四轮 / 判断件 / 思考路由 / ★ DSML 复现 / ★ 解析层真机集成 —— 临时端口起 web、真模型跑一轮、核正文无 json 泄漏与存档 +1 / ★ 自回声对照 —— 3 题 × 2 版材料 × 2 支模型各答一遍，判"这是模型的锅还是供给的锅" / ★ skill 写法对照 —— 5 组 28 题 × 2 版写法 × 2 支模型，判"判别件吃不吃人格化" / ★ 输出形态观察 —— 4 版写法 × 4 个"说"场景 × 2 模型，看钢印式会不会自言自语 / ★ 叙事版（背景故事 + 零元话）：三版对照，潜暗示成立但契约被吃掉 / ★ 翻译件三级读回（叙事→结构化结论：87% / 73% / 57%）/ ★ 专用读回件（不用 JSON 契约也能到 96%））
  exec_agent.py    668      声明 → 执行 / 护栏（黑名单 + 宽目标 + 复读掐断）/ 输出落盘 / ★ 回合用尽兜底
  tokenizer.py     280      ★ 本地分词器：纯 stdlib 复刻 DeepSeek V4 那份 tokenizer.json，离线精确数 token（逐 id 与官方实现一致）
  native_marks.py  377      ★ 各家原生工具调用标记一处认全（小米 MiMo / DSML 方言 / ★ 官方模板那套）+ 语料防污染清法 + ★ 边流边吐过滤器（StreamFilter：草稿进正文区前把协议块整段扣住）
  outsource_hook.py 244     ★ 外援自动触发（程序判：要成段代码（两道）/ 左链检索不到 / 卡了明显时间）
  watchdog.py      273      ★ 看门狗：盯 8790 / 8199 / 8791 / PG，挂了拉回来
  算token.py       179      ★ 算 token 的命令行：文件 / 文本 / 目录 / 超上限标 ⚠ / --在线 跟 API 报的 prompt_tokens 对一下
  cli.py           115      ★ 总入口：`collaplex-agent web / 自检 / 模型 / chat` —— 一个命令管住所有启动方式

解析器（★ 两层：一家一件的适配件 ＋ 模型无关的外壳）                       452 行
  外壳.py            89      模型无关的最后一道：正文不许空 / 捞不回就端原文 / 一个字没吐就明说（找尾部JSON起点 · 围栏内容 · 从JSON里捞正文 · 把关 · 捞正文）
  适配件/__init__.py  66      ★ 登记表（deepseek / mimo / qwen3）＋ 关键词匹配（`config/解析.json`；命中不了 → 只走外壳，不炸）
  自测.py           120      ★ 逐家 × 逐样本对期望正文（11 条）＋ 关键词命中（6 条）；不用起 web、不用起模型
  __init__.py        60      `取干净(原文, 模型) → 结果(正文 / 说明 / 走了 / 家族)`；顺序 ①适配件 → ②外壳
  适配件/deepseek.py  35      DeepSeek：DSML 标记族 / 官方模板标记（识别与清洗归 `native_marks.py`，这里只记习惯 + 样本）
  适配件/mimo.py      32      小米 MiMo：整段回答被包进 json 围栏（★ 兜底归外壳）/ XML 那套工具调用
  适配件/qwen3.py     32      qwen3：思考走独立字段 `reasoning_content` / 偶尔吐空 · 复读（空正文由外壳兜底）
  适配件/形状.py      18      适配件长什么样 = 一个 dataclass（家族 / 已知产出侧习惯 / 特化）

  运行时几件      1,021      库.py 324（库名/表名自动挂沙盒前缀）· 定时.py 138（到点提醒）· 作业.py 291（★ 长活后台跑完再汇报）· 清单.py 209（对话内任务编排的清单）· 待注入.py 59（到点把主 agent 叫回来）

skill 区（程序）                     19,222 行 / 75 个
  rag/           4,746      chunker / embed / search / recall（★ 语义路不可用时落关键词兜底 ILIKE, 并把实况带出去） / refine（两层记忆 + 下水道）
  math/          3,086      engine（Fraction/Decimal + ast 白名单求值）/ cli / compute / convert / main / retrieve / tests ×2（★ 72 条真跑对拍）
  search/        3,004      main（命令库入口）/ browser（真浏览器抓取）/ serp / fetch / article（清洗）/ retrieve / ★ corpus（搜索语料层：热库 search_hot ＋ 冷库 search_corpus ＋ 去重 ＋ TTL ＋ 体积闸）
  outsource/     1,301      main / budget（开关+预算+记账）/ ask（真调用+落盘）/ status / tests ×4（含 ★ 误触发对照）
  vision/        1,222      main（命令库入口）/ vision_core（查图 ＋ 单轮闸 ＋ 发那一发请求）/ see（看图）/ status（★ --真读 验本地能不能读图）/ retrieve / tests ×2
  timer/         1,192      ★ 定时/事件类 skill：到点提醒 ＋ 就在这等着读秒 ＋ 与主 agent 的接缝（tests 含接缝测）
  linux/           993      main（命令库入口）/ retrieve（检索件）/ tests（左链 · 护栏 · 四路对照）
  kali/            788      ★ 安全检查工具命令库（15 条）：与 linux 同一个形状 —— 检索逻辑一行未改，只换语料
  file/            730      main（读写命令库入口）/ retrieve（检索件）/ tests（四路对照）
  mtp/             597      main / panel（并行问多家 + 一致/分歧比对 + run_panel 共用入口）/ status / tests ×2
  skill_search/    593      core / find_skill / index_skills
  orchestra/       177      ★ 任务编排 skill：主 agent 给自己排活儿单、推着往下走
  ops/             793      ★ 这套系统自己的使用与维护手册：命令库 28 条 + 检索件（与 linux 同形状，只换语料）
  seek/              0      只有 SKILL.md —— 提示词形态的能力声明，没有代码

附带                                2,146 行
  diagrams/*.py  2,104      gen_product 439 · gen_联网搜索skill_补全版 333 · gen_drawio 272 · gen_看图skill 248 · gen_定时任务 228 · gen_任务编排skill审计 204 · gen_linux_skill 201 · 审计-设计对照 180
  mvp_os.py         42      最早的单轮原型，留着当起点存档
```

另有 shell 脚本 **857 行**（`push_gitea.sh` 236 推仓库/发 release · `pack_bundle.sh` 175 打"解压即用"包 · `start_models.sh` 141 管两个 llama.cpp 服务 · `本地兜底.sh` 43 主路不通自动落本地 · ★ `编译.sh` 27 用 Nuitka 编独立可执行件（自己 setsid 脱离会话, 长活不挂在 agent 下）· ★ `挂数据.sh` 54 把 config/state/logs/skill/.env 等挂进编译产物；skill 里另有 `自动灌语料.sh` 63 ＋ `embed_server.sh` ×2 共 118 行）。
提示词与文档（Markdown）**10,788 行**（含命令库；口径：`config/skills/` ＋ skill 文档（不含 `commands/`、`corpus/`）＋ `diagrams/*.md` ＋ 顶层（README ＋ CHANGELOG ＋ ★ 设计-思考路由 ＋ ★ 设计-外援与交叉比对）＋ `web/README.md` ＋ 命令库，2026-10-13 按同口径重数）：`config/skills/` 506（9 份）· skill 文档 2,360（34 份 —— 14 份 `SKILL.md` ＋ 各自的 README / CHANGELOG / 示例 / 用例）· 架构图与设计稿 1,718（`diagrams/*.md`）· 顶层 2,557（README 678 ＋ CHANGELOG 1543 ＋ ★ 设计-思考路由 116 ＋ ★ 设计-外援与交叉比对 220）· `web/README.md` 154 · **命令库 3,493 行 / 145 条**（`skill/linux/commands/*.md` 63 条 ＋ `skill/kali/commands/*.md` 15 条 ＋ `skill/file/commands/*.md` 16 条 ＋ `skill/math/commands/*.md` 12 条 ＋ `skill/search/commands/*.md` 9 条 ＋ `skill/vision/commands/*.md` 2 条 ＋ `skill/ops/commands/*.md` 28 条，一命令一文件）。

**另有 `web/` 那层壳 5,746 行 / 11 个**（口径：`web/*.py` ＋ `web/static/*` 自己的件，**不含 `web/static/vendor/`（katex 26 个文件 2,329 行，第三方）** 与 `web/tests/`；`web/tests/` 是 14 个自测脚本、另 1,877 行，其中 ★`回归导入面.py` 把"往输入框塞本机路径"那一面 34 条一次跑全）—— 浏览器里那条入口（见 §七），按上面口径单列。

**骨架很小**：整套运行时的 Python 就 **31,557 行**（= 合计 33,661 − diagrams 2,104，设计稿生成器不算运行时），其中真正"框架"的部分 **12,334 行**（框架与回归 10,861 ＋ 解析器 452 ＋ 运行时几件 1,021）—— 剩下都是各管一摊、可单独替换的 skill。

### 编译成独立可执行件（Nuitka，★ 不含 skill）

```bash
bash 编译.sh     # 自己 setsid 脱离会话跑（长活不挂 agent 下），日志 logs/编译.log，约 25 分钟
bash 挂数据.sh    # 把数据树挂进产物目录（见下），一次就够，重编后要再跑一次
编译产物/cli.dist/collaplex-agent 自检          # 编译版自检
编译产物/cli.dist/collaplex-agent web --端口 8791
```

- **skill 不编译**：`--nofollow-import-to=skill`，产物里 `skill` 是指回源目录的软链 —— **skill 改动即时生效，不用重编**。
- **★ 挂数据这一步是必须的**：Nuitka 编译后每个模块的 `__file__` 都指向 dist 里的虚拟位置（实测 `<dist>/web/bridge.py`、`<dist>/解析器/适配件/__init__.py`），
  而项目里一律用"自己文件所在目录"往上数来定项目根 ⇒ **dist 就是"项目根"**。所以把该在根下的东西（config / state / logs / skill / vendor / .venv / .env / icon.txt /
  几个要被子进程调用的 `.py`）软链进 dist，**代码一行都不用改**；`web/static`、`web/vendor` 同理挂到 `<dist>/web/` 下。这就是 `挂数据.sh` 干的事。
- **★ 必须 `--include-package` 的那几个**：`openai / pydantic / anyio / jiter / sniffio / h11`（另加原有的 `numpy / psycopg / websocket`）。
  漏了 `openai` 的真实现：编译能过、首页也能开，但**真打一轮就炸** —— `ModuleNotFoundError: No module named 'openai.resources.chat.chat'`
  （openai 3.x 的懒加载子模块，`--follow-imports` 追不到），界面上表现为"模型一个字都没吐"。
- **实测（2026-10-11）**：`兼容 C 文件 2,996 个`、二进制 **191 MB**、dist 目录 238 MB；`自检` 与 `web` 两条都通
  （编译版 web 临时端口起、首页 200、真打一轮有正文、存档 `+1`）。
- **★ 本机 bash 不认中文变量名**（`根=/tmp` 会当成命令跑 ⇒ `没有那个文件或目录`）：脚本里变量名一律 ASCII，注释和提示语随便中文。

## 六、快速开始

### 1. 装依赖

```bash
uv venv && uv pip install -r requirements.txt
```

下面命令里的 **`PY`** 就指你这份 `.venv/bin/python`（也可以先 `source .venv/bin/activate`，那就直接用 `python`）。

### 2. 配模型

建 `.env`（**所有模型调用都从这里读**）：

```ini
# 主线（主 agent / 执行体 / 子 agent 共用这一套）—— 这份 .env 现指云端 MiMo，一发 1~2 秒
OPENAI_BASE_URL=https://api.xiaomimimo.com/v1
OPENAI_MODEL=mimo-v2.6-flash
OPENAI_API_KEY=sk-...

# 换本地就改这三行（llama.cpp，见下一节；./start_models.sh start 起的就是它）
#   OPENAI_BASE_URL=http://127.0.0.1:8790/v1
#   OPENAI_MODEL=qwen3-vl-8b
#   OPENAI_API_KEY=local

# 向量模型（本地另起一个服务，跟主线走哪家无关）
EMBEDDING_BASE_URL=http://127.0.0.1:8199/v1
EMBEDDING_MODEL=qwen3-embedding-0.6b

# ★ 两层记忆的库（store 后端选 pg 时必填，见 §二）
RAG_PG_DSN=host=/var/run/postgresql dbname=collaplex_rag user=collaplex password=你自己设的

# 可选：给执行 agent（exec）/ 子 agent（分析/判断）单独挂一支 —— 有 EXEC_* / SUBAGENT_* 就用它，
# 没有就跟主线共用一套（这份 .env 两组都没配 = 主线三支全走上面那套）。
# 场景：本地那支太慢/太小，就把这两组指到云端。
# EXEC_BASE_URL=… / EXEC_MODEL=… / EXEC_API_KEY=…
# SUBAGENT_BASE_URL=… / SUBAGENT_MODEL=… / SUBAGENT_API_KEY=…

# 外援 / 交叉验证（skill/outsource、skill/mtp）要的云端凭据 —— 跟主线无关，删主线那几行不影响它
DEEPSEEK_API_KEY=sk-...             # 外援主力（默认家）：余额宽裕、价低
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
MIMO_API_KEY=sk-...                 # 第二路 + 交叉验证用（余额紧，别当主力）
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
```

换模型就改 `OPENAI_BASE_URL` / `OPENAI_MODEL` / `OPENAI_API_KEY` 三行，**代码一行不动**。

### 3. 拉模型（本地模式）

```bash
./start_models.sh start     # 主模型 :8790 + 向量模型 :8199
./start_models.sh status
./start_models.sh stop
```

### 4. 自检 + 开跑

```bash
./selfcheck.py              # 30 项全过 → 直接进主程序
./selfcheck.py --只查        # 只体检，不拉起
```

### 5. 让热库自动下沉（可选）

```cron
* * * * * cd "/path/to/collaplex_agent" && flock -n /tmp/collaplex-refine.lock \
          ./.venv/bin/python skill/rag/scripts/refine.py --安静 >> logs/refine.log 2>&1
```

`flock -n` 防重叠（清洗要 1~3 分钟，比 cron 周期长）；`--安静` = **没活干不出声**。

## 七、命令

下面用 `PY` 代表你自己环境的解释器（`./.venv/bin/python`，或 `source .venv/bin/activate` 之后就是 `python`）：

```bash
# ★ 总入口（推荐）—— 一个命令管住所有启动方式
#   （本机靠 ~/.local/bin/collaplex-agent 转发脚本在跑；没装就用 `PY cli.py …`，两个写法等价）
collaplex-agent web                       # 起 web（浏览器打开先是启动页，页面上选怎么启动）
collaplex-agent web --本地                 # 起 web 并自动走「以本地模型启动」（启动链丢后台，页面显示进度）
collaplex-agent web --端口 9000 --不打开    # 换端口 / 不自动开浏览器
collaplex-agent 自检                       # 只跑自检（30 项，不拉起主程序）
collaplex-agent 模型 start|stop|status     # 单独管本地模型服务
collaplex-agent chat                      # 命令行对话

# 主程序（老样子，分开来）
./selfcheck.py                                    # 自检（过了进主程序）

# 记忆检索（skill/rag）
PY skill/rag/main.py recall "问题" -n 5        # 两级检索（热库 → 冷库），默认入口
PY skill/rag/main.py search "问题" --tier 2    # 单层检索
PY skill/rag/main.py embed 文件 --tier 3       # 建库（tier 3 = 冷库）
PY skill/rag/main.py chunk 文件                # 切片预览

# 清洗（skill/rag）
PY skill/rag/scripts/refine.py                 # 立刻清一次
PY skill/rag/scripts/refine.py --看守           # 常驻，到点自己清
PY skill/rag/scripts/refine.py --干跑           # 只看要清什么，不动库
PY skill/rag/scripts/refine.py --待重洗         # 只看洗不了的账（文件没了、三层也没原文）
PY skill/rag/scripts/refine.py --回填           # 把三层里的半成品（有原文没概述）补洗一遍
PY skill/rag/scripts/refine.py --安静           # 没活干不出声（cron 用）

# 找 skill（skill/skill_search）
PY skill/skill_search/main.py find "问题"      # 按问题找 skill
PY skill/skill_search/main.py index            # 加了/改了 skill 后重扫注册（扫 SKILL.md）

# 命令库（skill/linux）
PY skill/linux/main.py find "磁盘还剩多少空间"  # 查该用哪条命令（用途/用法/示例 → 出处 + 分）
PY skill/linux/main.py index                   # 建/更新命令库索引（按 hash 复用向量）

# 读写命令库（skill/file）—— carve 的结构化读写
PY skill/file/main.py find "把 add 改成乘法"    # 查该用哪条 carve 子命令
PY skill/file/main.py index                    # 建/更新索引（按 hash 复用向量）
PY skill/file/tests/retrieval_check.py         # 四路检索对照（34 例该命中 + 3 例库里没有）

# 这套系统自己的手册（skill/ops）—— 怎么起 / 怎么用 / 怎么维护 / 怎么排错
PY skill/ops/main.py find "清洗怎么跑"             # 查手册条目（用途/用法/示例/备注 → 出处 + 分）
PY skill/ops/main.py index                        # 建/更新手册索引（按 hash 复用向量）
PY skill/ops/tests/retrieval_check.py             # 四路检索对照（43 例该命中 + 4 例库里没有）

# 外援（skill/outsource）—— 卡住了摇云端强模型，会花钱
PY skill/outsource/main.py status                     # 看开关 / 今天花了几毛 / 凭据在不在
PY skill/outsource/main.py ask "写个把 GBK 转 UTF-8 的脚本"   # 干一件活（产出落盘 + 记账）
PY skill/outsource/tests/test_budget.py               # 预算/记账回归（纯逻辑，不联网）
PY skill/outsource/tests/smoke_ask.py                 # 真跑一发（真花钱，几厘）
PY skill/outsource/tests/misfire_probe.py             # 误触发对照：13 道本地能答的题，数白摇几次（不花钱）
PY skill/outsource/tests/effect_probe.py              # 效果对照：本地 vs 外援（6 道题，程序判分）
PY skill/outsource/tests/effect_probe.py --思考 关     # 同一批题的关思考对照（本地 5/6 → 3/6）

# 交叉验证（skill/mtp）—— 同一题问多家，并排 + 挑分歧（只在外援之后用）
PY skill/mtp/main.py status                           # 看开关 / 用哪几家 / 今天花多少
PY skill/mtp/main.py ask "这段代码为什么死锁？<贴代码>"      # 出参考材料（各家答案 + 一致/分歧）
PY skill/mtp/tests/test_panel.py                      # 比对逻辑回归（指纹 / 分组 / 渲染）
PY skill/mtp/tests/smoke_panel.py                     # 真跑一发（真调两家）

# 外援自动触发（outsource_hook.py）—— 程序判「摇不摇」，默认关
PY outsource_hook.py "写个判断回文数的函数" --秒 0        # 只看判据（不花钱）
PY tests/test_outsource_hook.py                       # 触发判据回归 34 例（开关 / 否决词表 / 三条判据 / 边界组 / 材料包装）

# 左链与护栏自测（skill/linux/tests）
PY skill/linux/tests/left_chain_probe.py       # 判断→检索skill→挑选/声明，看路由对不对
PY skill/linux/tests/retrieval_check.py        # 四路检索对照（--cases eval 可换用 rag 的标注题）
PY skill/linux/tests/guard_check.py            # 护栏自测：44 条命令过一遍拦/放

# 界面回归（tests）
PY tests/test_render_stream.py                 # 流式渲染：逐字符喂，量"最长卡顿"（反引号密集的回答不许整段扣着不打）
PY tests/test_exec_nudge.py                    # 复读掐断 / 回合用尽补收尾（不许交白卷、不许编）
PY tests/test_left_chain_fallback.py           # 左链兜底：判定/挑选那步坏了，活还得派出去（模型用假的、检索用真的）
PY tests/test_job_notes.py                     # 作业播报：账是跨轮跨进程留的，「过程」里不许把上一轮就跑完的旧活当新闻念（开场只报在跑）

# 类型检查（strict，与编辑器里的 Pylance 同一套口径）
uvx pyright                                    # 覆盖 133 个 py 文件（按 pyrightconfig.json 的 include/exclude 数：入口 ＋ web ＋ tests ＋ diagrams ＋ 全部 skill），要求 0 errors / 0 warnings / 0 informations
                                               # 配置在 pyrightconfig.json（目录级 include，新文件自动纳入）+ .vscode/settings.json
```

### 网页版（`web/`）—— 同一条链，浏览器里说话

```bash
PY -m web.server                  # 起服务，默认 http://127.0.0.1:8791
PY -m web.server --端口 8791      # 换端口（纯标准库，零第三方依赖）
```

`web/` 只做**搬运**：判定、挑 skill、递交 exec、入二层库统统调 `main.py` / `sub_agent.py` 里现成的函数，
**`main.py` 一行没改** —— 命令行和网页共用同一条链，网页上没有第二套业务规则。

**往输入框里塞本机路径的两条路**（2026-10-11 加；细节与坑见 `web/README.md`）：

- **拖**：把文件/文件夹从文件管理器拖到窗口上，输入栏自动写入**带引号**的路径（写多路径就空格隔开），
  输入框亮一下绿 + 顶部浮层提示。从**浏览器下载栏**拖只给得到文件名（浏览器不给真路径），会红字说明。
- **导入按钮**（输入框右侧那个回形针，`Ctrl+O`）：弹窗里逐层翻本机目录，点文件就把带引号的路径填进去。
  ★ 浏览器出于安全不给 `<input type=file>` 的真实路径，所以这里让**本机服务**去列目录：
  只认本机来源（回环地址 + Host 头都是本机名，挡外机也挡 DNS rebinding），**只读**，不写不删。
  ★ **动了 `server.py` 必须重启 web 进程**（静态页 F5 没用）；没重启时面板会自己写明"这个 web 进程里还没有这个接口"。
  ★ 键盘走位（2026-10-11 补）：`↑↓` 换行 · `PageUp/PageDown` 一屏 · `Home/End` 头尾 · `Enter` 进目录或选文件
    · `Backspace` 回上一级 · `Esc` 关。走位行左边一道绿条 + 绿调底，**跟鼠标悬停的灰底区分开**
    （一眼看得出现在是键盘在选还是鼠标在指）。`Tab` 锁在弹窗里转，不会摸到背景的输入框/发送。

界面上叫 **Collaplex Agent OS**：左栏是"图标 + 历史记录 + 设置"，右栏是对话。

- **历史记录**：一打开就把最新一批对话摆进正文（默认 6 轮），往上翻到顶自动再取 6 轮（懒加载）；
  左栏那份清单是**全量跳点**，点哪条滚到那一轮。存档 `state/web-对话.jsonl`（每轮 **问 + 答 + 过程** 一行）。
  ★ **作业播报只报这一轮的事**（2026-10-09 补）：长活的账（`state/作业.json`）是跨轮跨进程留着的，
    每轮开场那一遍**只报「在跑」的**，上一轮（甚至昨天）就跑完的旧活不当新闻念 —— 不这么挡，
    旧活会在每次开场被念一遍，秒数（止于−起于）是终值不会动，看着像硬编码，老板就是这么抓出来的。
  ★ **过程步骤也入库**（2026-10-09 补）：关掉页面再开，那轮的过程还在（默认折起来的「过程」面板）；
  单步文字封顶 4000 字，截断处写明全文去哪看（单步文字封顶的道理与口径见 `web/README.md`）。
- **设置页**：读数从现成配置**现算**，可改两片 —— ① 四条接口（主线/子agent/执行体/向量模型）写 `.env`（改前自动备份）；
  ② 五个开关写进各自 json。**写入逐字节精确**（只替换目标字面量，不重排 JSON），且**只递交真改过的项**；
  开关每轮现读，下一问就按新值走。

前端 md 渲染照 18 家 AI 产品扒来的四条硬规矩（细节见 `web/README.md` 与技能 `web-frontend-teardown`）：

- 每帧把**整段 buffer** 丢给 CommonMark 解析器，**不自己写正则切 markdown**（未闭合的围栏/半截表格/公式由它容错）
- **块级复用 DOM 节点**（key = 抛光前的原始 HTML），只有尾部在长
- **新块淡入**（`.md-新`）；这轮结束挂 `.md-完成` 把动画全关
- **后处理走 DOM**（代码头/复制按钮/表格外壳/外链），不碰字符串、跳过 `code`/`pre`

### 界面上的两条约定（都踩过坑）

- **`input()` 的行编辑要靠 `import readline`**：不 import 时方向键会被当普通字符打进行里（实测回显 `ab^[[C`），
  退格只由终端擦最后一个字符、跟光标脱节 —— 看着就是"方向键没用 / 退格有 bug"。main.py 已显式 import，
  输入历史存 `~/.cache/collaplex_agent/history`（上下键能翻到上次会话）。
- **exec agent 的过程全程可见**：`run_task(..., on_event=…)` 发四类事件（思考 / 说的话 / 马上要跑的命令 /
  命令输出前 10 行 + 全文路径），main.py 用 `ExecStream` 边发生边打，前缀文案在 `config/agent.json` 的 `ui.exec_tag`。

## 八、打包 —— 解压即用

不编译，但把**解释器和依赖**一起打进去：另一台 x86_64 Linux 解压就能跑，不用装 Python、不用装依赖。
项目代码一行不改（`Path(__file__)` 那套定位照旧能用）—— 这正是它比编译成单文件省事的地方。

```bash
./pack_bundle.sh      # 约 2 分钟 → dist/collaplex-agent-<日期>.tar.zst（48 MB，解开 188 MB）
```

- 基座是 **python-build-standalone**（uv 管的 install_only 版，107 MB）：自带 libpython，不碰系统 python。
  ★ 别用 `~/.hermes/tools` 那份 401 MB 的，更**别对它 `strip`** —— 那个 build 的 ELF 布局特殊
  （`.dynstr` 不在 segment 里），削一次就 `symbol lookup error / undefined symbol`。
- 依赖走 `uv pip install --target runtime/deps` + 启动器塞 `PYTHONPATH` —— **不建 venv**：
  venv 的 `bin/python` 是软链、`pyvenv.cfg` 写死绝对路径，搬机器就废。
- 包里**没有**：`.env`（★凭据不进包，只给键名留 `.env.example`）、向量服务、网络、`carve`。
  linux skill 会照**目标机器**的实情回答 —— 正常，本来就是这意思。
- 验收（把压缩包解到别处、配 `.env` 实跑）：自检 **24/24**（当时口径；现 30 项）；问「8790 端口是哪个进程」
  → 检索命中 linux → exec 读包里的 `ss.md` → `ss -ltnp | grep 8790` → `llama-server pid 13660` ✓
  （证据 `logs/打包验收-解压即用-20261006.txt`）

## 九、成品架构图（按现在真跑着的这套画的）

`diagrams/成品架构.drawio` 是**成品图**（4 页）—— 脚本生成，改一行重跑即可，图上的数字都取自当前库：

```bash
./.venv/bin/python diagrams/gen_product.py   # 生成 成品架构.drawio（自带断链 / 重复 id 校验）
                                             # ★ 用带 psycopg 的解释器：图里"库里的数"是现查 PG 的
for i in 1 2 3 4; do drawio -x -f png --no-sandbox -o "diagrams/成品-p$i.png" --page-index $i "diagrams/成品架构.drawio"; done
```

![成品总览](diagrams/成品-p1.png)
*页 1 · 成品总览 —— 谁在哪层*

| 页 | 名称 | 内容 |
|---|---|---|
| 1 | 成品总览 | ① 入口（`cli.py` 总入口 / `selfcheck` 30 项 / `start_models` / `watchdog`）② 三个 agent ③ **skill 区（清单跟盘走**，扫 SKILL.md 现列）④ 两层记忆（PG 表 `rag_chunks`）⑤ 四份配置 ⑥ 后台与外围（清洗 / 状态 / web / 兜底 / 打包 / 开源） |
| 2 | 一轮对话 | 用户提问 → 渲染/拦截 → 子 agent 备料 → 拼 skill → 模型 → 判断 → 执行 agent 动手 → 产出入热库（**标了真函数名**） |
| 3 | 记忆与清洗 | 二层热库 → 静默 20 分钟 → 清洗三步 → 三层冷库 ＋ 别名表 → 两路检索；兜底与 cron（**数字现查库**） |
| 4 | 启动·自检·打包 | `cli.py` → `selfcheck` 30 项（是 / 否两条分支）→ 起模型 → `main.py`；`pack_bundle` → `push_gitea` |

![一轮对话](diagrams/成品-p2.png)
*页 2 · 一轮对话 —— 主链 + 两条链*

（页 3、4 见 `diagrams/成品-p3.png` / `diagrams/成品-p4.png`）

### 当年那份设计稿 vs 现在这份成品

`diagrams/` 里还留着**设计稿**（"Agent 即 OS" 的大版本：内核 / 生成器 / 三线流水线 / SQLite 状态 / 双缓冲 KV）。
本仓库落地的不是那个大版本，是它的**最小可跑子集** —— 逐条对照：

| 设计稿 | 现成品 |
|---|---|
| 内核 / 驱动 / 会话三层 | 三个入口：`main.py` / `sub_agent.py` / `exec_agent.py` |
| SQLite 当状态存储 | PG 表 `rag_chunks`（`tier` 分两层）＋ `alias.json`（见 §二） |
| 三线流水线（小模型 LoRA 路由） | 一条主线 + 两条链（备料 / 声明执行） |
| 生成器统一分配窗口 | `ContextBudget` 按 40% 预算 |
| 独立标记块 `<!--AGENT_META_V1` | json 围栏尾块（`find_tail_json` 正则匹配） |
| 双缓冲 KV | 未做（框架层碰不到引擎 KV） |

设计稿没删：演进记录与取舍理由在 `diagrams/summary.md`，架构补全说明在 `diagrams/architecture.md`，
四页设计图仍在 `diagrams/p1..p4.png`（`diagrams/1.drawio` 可编辑）。

## 十、许可

AGPL-3.0 — 见 [../LICENSE](../LICENSE)。

★ 2026-10-15 由 MIT 换成 **GNU AGPL-3.0**：允许自用、改造、再分发（含对外提供网络服务），
条件是**通过网络使用它的人能被提供对应源码**。要在别的条款下基于它做产品，另谈。

## 十一、开源仓库布局（Gitea）

全部公开：[collaplex.me/git/edgevoid](https://collaplex.me/git/edgevoid)

| 仓库 | 是什么 |
|---|---|
| `collaplex-agent` | 整个项目（这份 README 所在） |
| `collaplex-skill-rag` | `skill/rag/` —— 两层 RAG 记忆（切片 / 嵌入 / 检索 / 别名 / 清洗） |
| `collaplex-skill-linux` | `skill/linux/` —— 本机命令库 63 条 |
| `collaplex-skill-file` | `skill/file/` —— 读写代码命令库 16 条（底下是 `carve`） |
| `collaplex-skill-seek` | `skill/seek/` —— 主 skill（对话规范 + "手头没有的能力"怎么说） |
| `collaplex-skill-router` | `skill/skill_search/` —— 技能检索（技能路由；原名 `-search`，2026-10-09 让给联网搜索） |
| `collaplex-skill-search` | `skill/search/` —— 联网搜索（bing+百度 跨站去重 / 真浏览器取页 / 热库回查） |
| `collaplex-skill-outsource` | `skill/outsource/` —— 外援：摇云端强模型干活（开关 + 预算 + 记账） |
| `collaplex-skill-mtp` | `skill/mtp/` —— 交叉验证：同一题问多家模型，并排答案 + 挑分歧（只在外援之后用） |
| `collaplex-skill-math` | `skill/math/` —— 算数命令库 12 条（不让模型自己硬算） |
| `collaplex-skill-vision` | `skill/vision/` —— 看图：一张本地图片 → 文字（主路云端 / 兜底本地 `qwen3-vl-8b`；★ 图不寄存：那一次请求发出去就散了，不落库、不进会话历史） |
| `collaplex-skill-ops` | `skill/ops/` —— ★ 这套系统自己的使用与维护手册（28 条）：起服务 / 网页与设置页 / 模型 / PG / 三层记忆与预算 / 清洗与嵌入 / 命令库与 skill 清单 / 外援·定时·编排·看图·搜索·长活 / 日志 / 自检与看门狗 / 配置 / 加 skill / 打包发布 / 排错对照 |

★ **skill 独立仓是给阅读和引用用的**：几个 skill 之间有互相 import（linux / file 借 rag 的切片与检索函数），
**拆开单独跑不动** —— 要连着跑就放回本项目的 `skill/` 底下。

推法：`./push_gitea.sh`（全推）· `./push_gitea.sh main`（只推主仓）· `./push_gitea.sh rag`（只推某个 skill）。
脚本用 `git subtree split` 把每个 skill 的历史拆出来，**不复制粘贴**；凭据从本机现成的带凭据 remote 里现取，
不写在脚本里（见脚本头部注释）。

---

**Collaplex 克拉普莱克斯工作室** · *Collapse · Complex · AI*

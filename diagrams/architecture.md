# 第三代 Agent OS · 架构补全说明（v2）

> 配套图：`1.drawio`（4 页）｜ 生成器：`gen_drawio.py` ｜ 底稿：`design.md`
> 本文件只记录**相对设计稿补了什么、为什么**，不重抄设计稿。

---

## 一、三处 🔴 定案（设计稿悬空、必须钉死）

### 1. 并发模型 —— 单进程 + asyncio，阻塞驱动一律 `to_thread`
设计稿自相矛盾（决策表写 asyncio，正文写多线程），且 `main.py` 直接把同步阻塞调用放进了 event loop。
- **定案**：单进程 + asyncio 事件循环作为唯一调度中枢；所有**阻塞驱动**（llama.cpp 推理、requests/API、paramiko、sqlite3）通过 `loop.run_in_executor` / `asyncio.to_thread` 执行，绝不裸 `await`。
- **理由**：驱动库全是同步阻塞式；直接 await 会卡死整个 loop，"二线三线并行"不成立。
- **命令**：二线/三线是**按需工作单元**（kernel 提交到线程池），不是常驻线程；后台（预取/归档/keepalive）另起 daemon task。

### 2. 输出协议 —— 正文 Markdown + 末尾唯一标记块 JSON
`_parse(output)` 到处在调，但设计稿没定模型输出长什么样。
- **定案**：
  ```
  {正文 Markdown，直接流式渲染给用户}

  <!--AGENT_META_V1
  {"delta": {"add": {...}, "update": {...}, "remove": [...]},
   "needs": [{"kind": "tool", "target": "weather", "args": {...}}]}
  -->
  ```
- **展示层**：匹配到 `<!--AGENT_META_V1` 即停止渲染，用户只看到正文。
- **数据层**：解析标记块 → delta / needs。标记必须**唯一**（不用 ```json，防正文代码块误判）。
- **约束**：provider 支持 Structured Outputs 就用 JSON Schema 约束标记块内容；否则用 GBNF；再否则正则 + 容错 + 失败重试一次。

### 3. 事务边界 —— 先全量校验 → 单事务写入 → 失败整体回滚
设计稿 `apply_delta` 在循环中 `return False` 提前返回，但已 `execute` 的语句**未 rollback**，下次 commit 会一起落库 → 状态被"半应用"。
- **定案**：
  ```
  def apply_delta(delta):
      # 1) 先全量校验（含只读 key 表），任一不过 → 直接返回 False，DB 不碰
      # 2) with self.conn:   # 事务
      #        执行全部 add/update/remove
      #    异常 → 自动 rollback
  ```
- **理由**：SQLite 未提交语句属于当前事务，必须显式回滚，否则脏数据静默落库。

---

## 二、新增模块（设计稿缺件）

| 模块 | 职责 | 为什么必须独立 |
|---|---|---|
| `kernel/protocol.py` ★ | 输出协议解析/编码：正文与标记块分离、约束解码封装、容错重试 | 回归最初"标签 vs JSON"的核心契约，散在 main_worker 里会重复实现 |
| `kernel/budget.py` ★ | 真实 token 计数（本地模型自带 tokenizer / tiktoken），替代设计稿拍脑袋的 2000/500/300/100 | 硬编码估算必偏 → 窗口溢出或浪费 |
| `drivers/base.py` 补 | 基类加**超时契约 + 标准错误返回**（`{ok,data,error}`），metadata 含 params_schema | 每级超时回退是设计目标，但基类没体现 |

## 三、接口契约（冻结后不许随意改）

```python
# 驱动
class Driver(ABC):
    def execute(self, input: dict, timeout: float | None = None) -> dict: ...   # {ok, data, error}
    @property
    def metadata(self) -> dict: ...    # {name, description, params_schema, kind}

# 状态增量
@dataclass
class StateDelta:
    add:    dict[str, Any] | None = None
    update: dict[str, Any] | None = None
    remove: list[str] | None = None

# 生成器
class Generator:
    def build(self, blocks: list[ContextBlock]) -> str: ...   # 只拼字符串，不碰网络/DB

# 主线单步
class MainWorker:
    def step(self, question: str) -> dict: ...   # {answer, delta, needs}
```

## 四、与设计稿的差异清单

| 项 | 设计稿 | v2 补全 |
|---|---|---|
| 并发 | asyncio / 多线程 混说 | 单进程 + asyncio，阻塞驱动 to_thread |
| 输出协议 | 未定义 | 正文 + `<!--AGENT_META_V1-->` 尾块 |
| apply_delta | 循环中提前 return（脏数据风险） | validate-then-apply + 单事务 |
| token_estimate | 硬编码常数 | `budget.py` 真实 tokenizer |
| Skill 索引 | 三处（index.json / SQLite / kernel） | **SQLite 为权威**，index.json 仅导入种子 |
| 驱动契约 | 仅 execute/metadata | + timeout + 标准错误结构 |
| 模块 | 缺 protocol.py / budget.py | 已补（图中标 ★） |

## 五、图页索引

| 页 | 名称 | 内容 |
|---|---|---|
| 1 | 分层总览 | Boot / Kernel / Workers / Drivers / Sessions + Memory，OS 映射 |
| 2 | 内核流程（单轮） | 组装→主线→解析→needs分支(左)→delta分支(右)→输出；后台线程旁挂 |
| 3 | 生成器 | 权限分级 / 位置排序 / 预算降级 / 拼接 |
| 4 | 关键决策与契约 | 14 条决策表（🔴 标三处必先定） |

## 六、仍待定 / 待验证

- [ ] 输出标记块在**流式**下的部分匹配缓冲（`` / `<!-` / `<!--A` 中间态）
- [ ] 向量库与 SQLite **双写一致性**（写路径单点 + 对账，或向量只存不可变语料）
- [ ] `sessions/ssh.py` 持久 pty 的平台差异（内核跨平台，工具驱动需按平台重写）
- [ ] Skill 执行沙箱（与"执行要隔离"要求对齐）
- [ ] 三线 LoRA 路由数据构造 + 评估口径（路由/参数/格式/拒答 四项准确率）
- [ ] 最小可跑版：`boot + kernel + main.py` + 假 driver，走通一轮

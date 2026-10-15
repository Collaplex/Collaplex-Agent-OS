# 第三代 Agent OS 架构设计（设计稿）

> 存档：`~/桌面/collaplex_agent/diagrams/design.md`
> 来源：老板 2026-10-04 粘贴的设计稿，配套对话记录见 `1.txt`

## 第三代 Agent OS 架构设计

### 一、核心理念

**Agent 即 OS。** 不是"用 OS 思想做 Agent"，而是 Agent 本身就是操作系统。

- **CPU** = 模型（本地小模型 / API 大模型）
- **RAM** = 上下文窗口
- **磁盘** = SQLite + 向量库
- **设备** = Skill / 工具 / 持久会话
- **内核** = 生成器 + 状态管理 + 权限控制
- **进程** = 主线 / 二线 / 三线
- **系统调用** = 模型声明需求，内核解析执行

---

### 二、目录结构

```
agent_os/
├── boot/
│   ├── __init__.py
│   ├── config.py          # 加载配置、API Key、模型路径
│   ├── selfcheck.py       # 自检：模型、数据库、向量库、网络
│   └── registry.py        # 驱动注册表，加载所有 Skill / 工具
│
├── kernel/
│   ├── __init__.py
│   ├── core.py            # 内核主类，调度一切
│   ├── generator.py       # 生成器：权限 + 位置 + 预算
│   ├── state.py           # 状态管理：结构化状态 + 增量更新
│   ├── timeline.py        # 时间线：事件追加 + 冷热分离
│   ├── permission.py      # 权限模型：只读/可写/注入/可选
│   └── scheduler.py       # 进程调度：主线/二线/三线生命周期
│
├── memory/
│   ├── __init__.py
│   ├── store.py           # SQLite 封装：state / timeline / skill_index
│   ├── vector.py          # 向量库封装：ChromaDB / LanceDB
│   └── archive.py         # 冷归档：按需检索，不做摘要
│
├── drivers/
│   ├── __init__.py
│   ├── base.py            # 驱动基类：execute(input) -> output
│   ├── llm/
│   │   ├── local_3b.py    # 本地 3B + LoRA，路由专用
│   │   ├── local_8b.py    # 本地 8B Qwen3-VL，二线/主线备用
│   │   └── api.py         # API 大模型，主线推理
│   ├── retrieval/
│   │   ├── rag.py         # RAG 检索驱动
│   │   └── skill_search.py # Skill 索引检索
│   ├── tools/
│   │   ├── ssh.py         # 持久 SSH 会话
│   │   ├── comfyui.py     # 持久 ComfyUI 会话
│   │   ├── calculator.py  # 计算下沉
│   │   └── ...
│   └── skill_loader.py    # Skill 加载器：索引 + 全文
│
├── skills/
│   ├── index.json         # Skill 索引：名称 + 描述 + 触发条件
│   ├── frozen/            # 冻结 Skill，只读，放最前
│   └── dynamic/           # 动态 Skill，按需加载
│
├── workers/
│   ├── __init__.py
│   ├── main_worker.py     # 主线：推理 + 生成
│   ├── secondary.py       # 二线：筛选 + 校验 + 精炼
│   └── tertiary.py        # 三线：路由 + 参数填充 + 清洗
│
├── sessions/
│   ├── __init__.py
│   ├── manager.py         # 会话池：SSH / ComfyUI / 浏览器
│   └── base.py            # 会话基类：connect / execute / keepalive
│
├── main.py                # Boot 入口，拉起内核
└── config.yaml            # 全局配置
```

---

### 三、内核核心：生成器

生成器是整个架构的心脏。它决定**什么内容能进上下文、以什么权限进、放在哪个位置、占多少预算**。

```python
# kernel/generator.py

from dataclasses import dataclass, field
from enum import Enum

class Permission(Enum):
    READONLY = "readonly"      # 只读：核心指令、冻结 Skill
    WRITABLE = "writable"      # 可写：状态、时间线
    INJECTED = "injected"      # 程序注入：RAG、Skill 全文
    SELECTABLE = "selectable"  # 模型可选：从候选中选

class Position(Enum):
    FRONT = "front"            # 最前：只读区，KV 永久命中
    MIDDLE = "middle"          # 中间：状态、检索结果
    BACK = "back"              # 最后：当前问题、输出格式

@dataclass
class ContextBlock:
    content: str
    permission: Permission
    position: Position
    priority: int              # 越大越优先保留
    token_estimate: int
    source: str                # 来源标识，用于调试
    cacheable: bool = False    # 是否可被 KV 缓存

@dataclass
class ContextBudget:
    total: int                 # 总窗口
    output_reserve: int        # 输出预留
    readonly_reserve: int      # 只读区固定占用
    available: int = 0         # 动态可用

    def __post_init__(self):
        self.available = self.total - self.output_reserve - self.readonly_reserve

class Generator:
    def __init__(self, budget: ContextBudget):
        self.budget = budget

    def build(self, blocks: list[ContextBlock]) -> str:
        # 1. 按 position 分组
        front = [b for b in blocks if b.position == Position.FRONT]
        middle = [b for b in blocks if b.position == Position.MIDDLE]
        back = [b for b in blocks if b.position == Position.BACK]

        # 2. 只读区不计入动态预算，直接放最前
        # 3. 中间区按优先级分配预算
        middle_sorted = sorted(middle, key=lambda b: -b.priority)
        selected_middle = []
        used = 0
        for b in middle_sorted:
            if used + b.token_estimate <= self.budget.available:
                selected_middle.append(b)
                used += b.token_estimate
            else:
                # 放不下，降级：如果是 Skill 全文，换成索引
                degraded = self._degrade(b)
                if degraded and used + degraded.token_estimate <= self.budget.available:
                    selected_middle.append(degraded)
                    used += degraded.token_estimate

        # 4. 按 position 顺序拼接
        parts = []
        for group in (front, selected_middle, back):
            for b in group:
                parts.append(b.content)
        return "\n\n".join(parts)

    def _degrade(self, block: ContextBlock) -> ContextBlock | None:
        """放不下时的降级策略：全文 -> 索引，RAG -> Top-1"""
        if block.source.startswith("skill_full:"):
            skill_id = block.source.split(":")[1]
            return ContextBlock(
                content=f"[Skill 索引] {skill_id}: 详见索引",
                permission=Permission.INJECTED,
                position=Position.MIDDLE,
                priority=block.priority - 1,
                token_estimate=50,
                source=f"skill_index:{skill_id}",
            )
        return None
```

---

### 四、内核核心：状态管理

```python
# kernel/state.py

import json
import sqlite3
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class StateDelta:
    """模型输出的增量更新，不是全量重写"""
    add: dict[str, Any] = None
    remove: list[str] = None
    update: dict[str, Any] = None

class StateStore:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS timeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT,
                category TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS skill_index (
                skill_id TEXT PRIMARY KEY,
                name TEXT,
                description TEXT,
                trigger TEXT,
                frozen INTEGER DEFAULT 0
            );
        """)

    def apply_delta(self, delta: StateDelta) -> bool:
        """应用增量更新，带校验"""
        if delta.add:
            for k, v in delta.add.items():
                if not self._validate(k, v):
                    return False
                self.conn.execute(
                    "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                    (k, json.dumps(v))
                )
        if delta.update:
            for k, v in delta.update.items():
                if not self._validate(k, v):
                    return False
                self.conn.execute(
                    "UPDATE state SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
                    (json.dumps(v), k)
                )
        if delta.remove:
            for k in delta.remove:
                self.conn.execute("DELETE FROM state WHERE key = ?", (k,))
        self.conn.commit()
        return True

    def _validate(self, key: str, value: Any) -> bool:
        """校验：字段合法、值合理、不冲突"""
        # 只读区字段不能改
        if key in self._readonly_keys():
            return False
        # 类型校验
        if key == "city" and not isinstance(value, str):
            return False
        return True

    def _readonly_keys(self) -> set:
        return {"system_prompt", "tool_definitions", "frozen_skills"}

    def snapshot(self) -> dict:
        rows = self.conn.execute("SELECT key, value FROM state").fetchall()
        return {k: json.loads(v) for k, v in rows}

    def append_timeline(self, event: str, category: str = "general"):
        self.conn.execute(
            "INSERT INTO timeline (event, category) VALUES (?, ?)",
            (event, category)
        )
        self.conn.commit()

    def recent_timeline(self, n: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT event, category, created_at FROM timeline ORDER BY id DESC LIMIT ?",
            (n,)
        ).fetchall()
        return [{"event": r[0], "category": r[1], "time": r[2]} for r in reversed(rows)]
```

---

### 五、三层流水线

```python
# workers/tertiary.py

class TertiaryWorker:
    """三线：路由 + 参数填充 + 清洗。本地 3B + LoRA。"""

    def __init__(self, llm_driver, skill_index):
        self.llm = llm_driver
        self.skills = skill_index

    def route(self, need: str) -> dict:
        """根据需求，选出工具 + 参数"""
        candidates = self.skills.search(need, top_k=5)
        prompt = self._build_routing_prompt(need, candidates)
        output = self.llm.generate(prompt, constrained=True)
        return self._parse(output)

    def clean(self, raw_output: str) -> dict:
        """清洗原始工具返回"""
        prompt = self._build_clean_prompt(raw_output)
        return self.llm.generate(prompt, constrained=True)

# workers/secondary.py

class SecondaryWorker:
    """二线：筛选 + 校验 + 精炼。本地小模型或规则。"""

    def __init__(self, llm_driver, state_store):
        self.llm = llm_driver
        self.state = state_store

    def refine(self, cleaned: dict, need: str) -> dict:
        """从清洗结果中筛选最相关的"""
        # 先用规则过滤
        filtered = self._rule_filter(cleaned, need)
        # 再用模型精选
        if len(filtered) > 5:
            filtered = self._model_select(filtered, need, top_k=5)
        return {"items": filtered, "count": len(filtered)}

    def validate(self, delta: StateDelta) -> bool:
        """校验状态变更是否合法"""
        return self.state.apply_delta(delta)

# workers/main_worker.py

class MainWorker:
    """主线：推理 + 生成。API 大模型。"""

    def __init__(self, llm_driver, generator, state_store):
        self.llm = llm_driver
        self.generator = generator
        self.state = state_store

    def step(self, question: str) -> dict:
        # 1. 组装上下文
        blocks = self._collect_blocks(question)
        prompt = self.generator.build(blocks)

        # 2. 调用模型
        output = self.llm.generate(prompt)

        # 3. 解析输出
        parsed = self._parse(output)

        # 4. 返回：回答 + 状态变更 + 需求声明
        return {
            "answer": parsed["answer"],
            "delta": parsed.get("delta"),
            "needs": parsed.get("needs", []),
        }

    def _collect_blocks(self, question: str) -> list[ContextBlock]:
        blocks = []
        # 只读区
        blocks.append(ContextBlock(
            content=self._readonly_content(),
            permission=Permission.READONLY,
            position=Position.FRONT,
            priority=100,
            token_estimate=2000,
            source="readonly",
            cacheable=True,
        ))
        # 状态
        state = self.state.snapshot()
        blocks.append(ContextBlock(
            content=self._format_state(state),
            permission=Permission.WRITABLE,
            position=Position.MIDDLE,
            priority=80,
            token_estimate=500,
            source="state",
        ))
        # 最近时间线
        recent = self.state.recent_timeline(5)
        blocks.append(ContextBlock(
            content=self._format_timeline(recent),
            permission=Permission.INJECTED,
            position=Position.MIDDLE,
            priority=60,
            token_estimate=300,
            source="timeline",
        ))
        # 当前问题
        blocks.append(ContextBlock(
            content=f"【当前问题】\n{question}",
            permission=Permission.INJECTED,
            position=Position.BACK,
            priority=100,
            token_estimate=100,
            source="question",
        ))
        return blocks
```

---

### 六、驱动基类

```python
# drivers/base.py

from abc import ABC, abstractmethod

class Driver(ABC):
    """所有驱动的基类。无状态、可替换、即插即用。"""

    @abstractmethod
    def execute(self, input: dict) -> dict:
        """执行驱动，返回结果"""
        pass

    @property
    @abstractmethod
    def metadata(self) -> dict:
        """驱动元数据：名称、描述、参数 schema"""
        pass
```

---

### 七、会话管理（持久 SSH / ComfyUI）

```python
# sessions/base.py

class PersistentSession(ABC):
    """持久会话基类。像文件描述符一样，长期持有。"""

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def execute(self, command: str) -> str: ...

    @abstractmethod
    def keepalive(self) -> bool: ...

    @abstractmethod
    def close(self) -> None: ...

# sessions/manager.py

class SessionManager:
    """会话池：内核管理生命周期，模型只发指令。"""

    def __init__(self):
        self.sessions: dict[str, PersistentSession] = {}
        self.idle_timeout = 300  # 5 分钟空闲超时

    def get_or_create(self, session_id: str, factory) -> PersistentSession:
        if session_id not in self.sessions:
            session = factory()
            session.connect()
            self.sessions[session_id] = session
        return self.sessions[session_id]

    def execute(self, session_id: str, command: str) -> str:
        session = self.sessions.get(session_id)
        if not session:
            return f"[错误] 会话 {session_id} 不存在"
        try:
            return session.execute(command)
        except Exception as e:
            # 自动重连
            session.connect()
            return session.execute(command)

    def cleanup(self):
        """清理空闲会话"""
        for sid, session in list(self.sessions.items()):
            if not session.keepalive():
                session.close()
                del self.sessions[sid]
```

---

### 八、主循环

```python
# main.py

import asyncio
from boot.config import load_config
from boot.selfcheck import self_check
from boot.registry import load_drivers
from kernel.core import Kernel

async def main():
    # 1. Boot：加载配置、自检
    config = load_config("config.yaml")
    if not self_check(config):
        print("[Boot] 自检失败，退出")
        return

    # 2. 加载驱动
    drivers = load_drivers(config)

    # 3. 初始化内核
    kernel = Kernel(config, drivers)

    # 4. 启动后台线程
    asyncio.create_task(kernel.background_worker())

    # 5. 主循环
    print("[Agent OS] 启动完成，输入问题开始对话")
    while True:
        question = input("\n> ")
        if question.strip() in ("exit", "quit"):
            break
        result = await kernel.step(question)
        print(f"\n{result['answer']}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

### 九、启动流程（Boot → Kernel → Drivers）

```
main.py
  │
  ├── boot/config.py      加载配置
  ├── boot/selfcheck.py   自检：模型/DB/向量库/网络
  ├── boot/registry.py    加载驱动表
  │
  ▼
kernel/core.py            初始化内核
  ├── kernel/state.py     状态存储就绪
  ├── kernel/timeline.py  时间线就绪
  ├── kernel/generator.py 生成器就绪
  ├── kernel/permission.py 权限模型就绪
  └── kernel/scheduler.py 调度器就绪
  │
  ▼
workers/
  ├── main_worker.py      主线启动
  ├── secondary.py        二线启动
  └── tertiary.py         三线启动
  │
  ▼
sessions/manager.py       会话池就绪
drivers/                  所有驱动注册完成
  │
  ▼
主循环开始
```

---

### 十、关键设计决策总结

| 决策 | 选择 | 理由 |
|---|---|---|
| 进程模型 | 单进程 + asyncio | 避免 IPC 开销，调试简单 |
| 状态存储 | SQLite | 跨平台、零配置、事务安全 |
| 向量库 | ChromaDB / LanceDB | 纯 Python、本地、无服务 |
| 权限模型 | 四级：只读/可写/注入/可选 | 防止模型污染核心指令 |
| 位置策略 | 外圈优先，只读区最前 | KV 缓存永久命中 |
| 预算管理 | 硬约束 + 优先级降级 | 窗口不爆，放不下就降级 |
| 压缩策略 | 程序归档，模型不参与 | 零压缩税，不滚雪球 |
| 路由策略 | 三线 LoRA 专用 | 主线不试错，错误不进上下文 |
| 会话管理 | 持久会话池 | 像文件描述符一样长期持有 |
| 平台策略 | 纯 Python + 跨平台库 | 内核无关，驱动适配 |

---

### 十一、和 Hermes / DSH 的本质区别

| | Hermes / DSH | 第三代 Agent OS |
|---|---|---|
| 架构 | 单线程 + 模型自管 | 多线程 + 内核管 |
| 上下文 | 模型压缩，会滚雪球 | 程序组装，零压缩税 |
| 工具调用 | 主线试错，错误进上下文 | 三线路由，错误不进主线 |
| 状态 | 散落在 prompt 里 | 结构化存储，增量更新 |
| 权限 | 无 | 四级隔离 |
| 缓存 | 靠自觉 | 强制外圈优先 |
| 平台 | 绑 Linux | 跨平台 |
| 成本 | 10 块 30 轮 | 10 块 60～100 轮 |
| 体验 | 聊几轮降智 | 无感上下文窗口 |

---

**核心一句话：内核管资源，模型管推理，驱动管执行，会话管持久。**
先从 `boot/` + `kernel/` + `main.py` 开始，把一轮对话跑通，再逐步加驱动和会话。

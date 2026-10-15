# 三层记忆 · tier 1 / 2 / 3

**用途**：程序管记忆那一层。全落 PG 表 `rag_chunks`，用 `tier` 分三层。**tier 越大越"熟"**。

**三层是什么**
- **tier 1 历史对话层**：所有场次的原文底档，逐条消息落（带 `对话id` / `对话时间` / `角色`），**只增不减**
- **tier 2 热层**：当前这场会话的活记忆（也放项目语料）
- **tier 3 经验层**：从对话提炼的概述 / 知识，每条挂 `来源id` 指针指回 tier 1 的原话（提炼歪了能回原文核对）

**怎么查（检索侧）**
- `./.venv/bin/python skill/rag/main.py recall "问题" -n 5`　**两级检索**：先热层，命中就回；不命中才落经验层（返回带 `tier` 与每层 state/top1 的 trace）
- `./.venv/bin/python skill/rag/main.py search "问题" --tier 2`　只查一层
- `./.venv/bin/python skill/rag/main.py embed <文件...> --tier 3`　建库入库
- 还有一路**别名路**（同义说法），在检索里自动带上

**备注**
- ★ **两种写入语义用错会静默抹掉底档**：`store.upsert()` 是**整层删了重插**（只适合可重算的派生层）；历史对话层这类底档必须走 `store.append_history()`（按 `source` 先删后插）。验收 = 沉一批后总数 `+N`，再跑一遍总数不变。
- "命中" = top1 相似度 ≥ `hit_threshold`，阈值**必须实测标定**（相关/无关两组探针取缝，见 `skill/rag/tests/eval.yaml`）；语料一变要重标，旧基线只当参照。
- ★ 读/写索引**一律过 `store.py`**，别直接摸文件/表；后端一换就分裂成两套真相。

# nproc · 看 CPU 核数

**用途**：打印当前可用的处理单元数 —— **问"有几个核 / 几核"就用它**，别去数 lscpu 的字段。

**用法**：nproc [选项]

**常用选项**
- `--all`　按系统全部处理单元算（不受当前 cgroup / 绑核限制）
- `--ignore=N`　少算 N 个

**示例**
- `nproc`　直接给总数
- `nproc --all`　容器或绑核环境里看物理总数

**备注**：★ **核数的唯一权威就是这条命令**。`lscpu` 那几行很容易看错：`Core(s) per socket` 是
**每一路（socket）的物理核**、`Socket(s)` 是**路数**、`CPU(s)` 才是**逻辑核总数**；把 per-socket
的数当总数是最常见的错法。要物理核就 `Core(s) per socket` × `Socket(s)`，要逻辑核直接 `nproc`。

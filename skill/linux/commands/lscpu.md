# lscpu · 看 CPU 详情

**用途**：列出 CPU 架构、路数、每路核心、线程、频率、缓存、虚拟化支持等。

**用法**：lscpu [选项]

**常用选项**
- `-e`　每个逻辑 CPU 一行（认绑核、认哪些是超线程）
- `-p`　可解析格式（逗号分隔，适合再加工）
- `--all`　连离线的 CPU 一起列
- `-C`　只列缓存层级

**示例**
- `lscpu`　全套信息
- `lscpu | grep -E 'Model name|Socket|Core|Thread'`　只挑要知道的几行
- `lscpu -e=CPU,CORE,SOCKET,NODE`　逻辑 CPU 到物理核的映射

**备注**：★ **别把 `Core(s) per socket` 当总核数** —— 那是"每一路里的物理核"。
逻辑核总数看 `CPU(s)`，或直接用 `nproc`；物理核总数 = `Core(s) per socket` × `Socket(s)`；
`Thread(s) per core` 是每核线程数。用户问"几个核"而没指定口径时，先给 `nproc` 的总数并说明它是逻辑核。

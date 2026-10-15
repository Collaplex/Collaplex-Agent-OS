# carve show · 看一个节点的源码、位置和引用

**用途**：把某个函数/类/方法的**源码原文**拿出来看，顺带给出它在哪、被谁引用。要读代码、要确认"这个函数现在是怎么写的"、想知道改动前长啥样，都用它。想知道**这个函数在第几行**、在文件里什么位置，也用它（带 `--metadata`）。

**用法**：`carve -p <文件> show <节点ID> [--metadata]`

**常用选项**
- `--metadata`　连元数据一起打（位置、类型等）

**示例**
- `carve -p app.py show 'module::add'`　读这个函数
- `carve -p app.py show 'module::Counter::bump'`　读类方法（注意是双冒号两级）
- `carve -p app.py show 'module::add' --metadata`　带位置信息

**备注**：①ID 写错了会返回 `Node not found`，先用 `carve ls` 把 ID 拿到手。②想连着上下文一起看用 `carve tree`；想知道"改它会影响谁"用 `carve refs`。③输出是 JSON，`source` 字段就是源码原文。

# carve rm · 删掉一个函数/方法/类

**用途**：把某个节点整个**删掉** —— 没用的函数、废弃的方法、整个类。按结构删，不会像按行删那样留下半截。

**用法**：`carve -p <文件> rm <节点ID> [--notes '为什么删']`

**常用选项**
- `--notes`　记一句为什么删（写进旁车日志）

**示例**
- `carve -p app.py rm 'module::unused_helper'`　删掉没人用的函数
- `carve -p app.py rm 'module::Counter::bump' --notes '改用 reset 了'`

**备注**：①**删之前先 `carve refs <节点ID>` 查一遍** —— 如果还有别处引用它，返回里会带警告（`references the deleted node`），那是提醒你删完会断链。②返回 `success` + `backup`，删错了 `carve undo` 能退回来。③删的是**代码节点**；删整个文件、删目录这类不是它的活（那是 shell 的 `rm`，而且宽目标会被拦）。④删完回读自查（`carve ls` 或 `grep -c` 确认真的没了）。

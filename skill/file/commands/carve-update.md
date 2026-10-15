# carve update · 改一个函数/方法的实现（换掉整个节点）

**用途**：把一个函数、方法或类的**实现换掉** —— 重写代码、改逻辑、加参数、改返回值。定位靠节点 ID 不靠搜字符串，不会误伤同名的别处。

**用法**：`carve -p <文件> update <节点ID> [--code '…' | --code-file 文件 | < 文件]`

**常用选项**
- `--code '…'` 给新代码（传 `-` 表示读管道）/ `--code-file 文件` 从文件读
- （都不给）　自动读管道：`carve … update ID < 新实现.py`
- `--prompt` / `--model` / `--notes`　写进旁车日志，记这次改动是怎么来的

**示例**
- `carve -p app.py update 'module::add' --code 'def add(a, b):
    return a + b'`
- `carve -p app.py update 'module::add' < 新实现.py`　代码从文件喂
- `carve -p app.py update 'module::add' --prompt '把 add 简化'`

**备注**：①新代码要**是整个节点**（连 `def` 行一起），不是片段。②★参数只有**位置参数 + `--code`**（或 `--code-file`/管道）—— 没有 `--id`、`--source` 这种写法，别猜。③返回 `success` + `backup`，写前自动备份。④**改完必须回读自查**（再 `show` 或 `grep -c` 数一下）。⑤纯文本替换别用它，用 `sed`。

# carve batch · 一次做多个改动（批量改）

**用途**：一趟把好几处改动一起做掉 —— 同一次调用里先建后改、连删带加。整批算一次写操作，备份和回退也算一步。

**用法**：`carve -p <文件> batch <操作JSON文件 | -> [--notes '…']`

**操作数组**：JSON 数组，每个元素长这样 `{"tool": "子命令名", "kwargs": {…}}`。例如下面两个（插一个新函数 + 删一个旧函数）要缩进成一行行的 JSON 存进 ops.json：

    [
      {"tool": "insert", "kwargs": {"parent_id": "module",
         "position": "end", "code": "def f():\n    return 1"}},
      {"tool": "delete", "kwargs": {"node_id": "module::old"}}
    ]

**常用选项**
- 参数文件传 `-` 表示从管道读
- `--notes`　给整批记一句

**示例**
- `carve -p app.py batch ops.json`
- `carve -p app.py batch - < ops.json`

**备注**：①`tool` 用子命令名（`insert`/`update`/`delete`/`move`），`kwargs` 跟单条命令一样。②**先拿一条试**，改完逐处回读自查。③`carve undo` 退一步就把整批退掉。

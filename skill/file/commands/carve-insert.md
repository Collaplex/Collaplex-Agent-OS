# carve insert · 加新函数/新方法，或新建一个文件

**用途**：往已有的结构里**加东西** —— 在模块里加个新函数、往类里加个方法、在某个位置插入代码；父节点是目录时就是**新建文件**。

**用法**：`carve -p <文件或目录> insert <父节点ID> <位置> [--code '…' | 管道] [--name 文件名]`

**常用选项**
- `位置`　`start`（最前面）/ `end`（最后面）/ `before:<节点ID>` / `after:<节点ID>`
- `--code` / `--code-file` / 管道　要插进去的代码
- `--name 新文件.py`　父节点是目录时用（新建文件）
- `--language`　语言覆盖
- `--prompt` / `--model` / `--notes`　旁车溯源

**示例**
- `carve -p app.py insert module end --code 'def helper() -> int:
    return 1'`
- `carve -p app.py insert 'module::Counter' end --code '    def reset(self) -> None:
        self.n = 0'`　往类里加方法（注意缩进要按类里的来）
- `carve -p 目录 insert . --code '…' --name 新文件.py`　新建文件

**备注**：①`end` 是加在最后，`after:某节点` 是紧跟着它。②往类里插方法，**缩进要自己写对**（跟类里别的方法齐）。③加完回读自查（`carve ls` 看它在不在）。

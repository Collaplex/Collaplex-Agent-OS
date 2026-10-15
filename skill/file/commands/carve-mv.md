# carve mv · 把一个函数/方法挪到别处

**用途**：把一个节点**搬到另一个父节点下** —— 把函数挪进某个类、把一个方法从类里挪到另一个类、调整代码里的先后位置。

**用法**：`carve -p <文件> mv <节点ID> <新父节点ID> <位置> [--notes '…']`

**常用选项**
- `位置`　`start` / `end` / `before:<节点ID>` / `after:<节点ID>`
- `--notes`　记一句为什么挪

**示例**
- `carve -p app.py mv 'module::helper' 'module::Utils' end`　把函数挪进 Utils 类
- `carve -p app.py mv 'module::b' module start`　把 b 挪到文件最前面

**备注**：①挪进类里时，缩进由工具按新位置调（不用自己重排）。②挪完**回读自查** —— `carve path <ID>` 看它的祖先链变了没有。③跨文件挪不在它的射程内（一个进程只管一个目标）；跨文件请用 `insert` + `rm` 两步。

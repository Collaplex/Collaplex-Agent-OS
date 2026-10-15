# carve tree · 看一个节点的子树结构

**用途**：看某个节点**底下**的结构 —— 一个类里有哪些方法、一个模块里有哪些顶层语句。想看清一个类或模块的**整体结构**（它由什么组成、往下长什么样）就用它；比 `show` 更偏"结构"，比 `ls` 更偏"展开看"。

**用法**：`carve -p <文件> tree <节点ID> [--depth N] [--source]`

**常用选项**
- `--depth N`　看几层（默认 2）
- `--source`　连源码一起打（默认只给结构）

**示例**
- `carve -p app.py tree module --depth 1`　看文件顶层都有什么
- `carve -p app.py tree 'module::Counter'`　看这个类里有什么
- `carve -p app.py tree 'module::Counter' --source`　连源码一起看

**备注**：①要的是"某个节点自己的源码"就用 `show`，别用 tree。②层级给太深输出会很大，从 `--depth 1` 开始看。③跟 `ls` 的区别：`ls` 是找（可按名字/类型搜），`tree` 是"就这个节点，展开给我看"。

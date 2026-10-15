# carve ls · 列节点：这文件里有哪些函数/类/方法

**用途**：看一个文件（或一个节点底下）定义了哪些东西 —— 有哪些函数、哪些类、类里有哪些方法。想读代码结构、想知道某个东西叫什么，先用它。也支持按名字或类型搜。

**用法**：`carve -p <文件> ls [--pattern 名字] [--type 节点类型] [--scope 某个节点] [--depth N]`

**常用选项**
- （不带过滤）　展示顶层结构，默认两层（`--depth` 调层数）
- `--type function_definition`　只列函数/方法（类用 `class_definition`）
- `--pattern 名字`　按名字找（子串就行）
- `--scope 'module::Counter'`　限定在某个节点里面找

**示例**
- `carve -p app.py ls --type function_definition`　列出所有函数和方法
- `carve -p app.py ls --pattern add`　找名字里带 add 的节点
- `carve -p app.py ls`　看整体结构（顶层有哪些东西）

**备注**：①列出来的是**节点 ID + 类型 + 签名**，拿到 ID 才能用 `show` / `update` / `rm` 那些。②不带过滤时根节点会把整个文件源码一起吐出来（嫌吵就用 `--type`）。③类方法的 ID 是 `module::类名::方法名`，不是并列的。

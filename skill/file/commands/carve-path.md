# carve path · 看一个节点在结构里的位置（祖先链）

**用途**：问"这个东西属于谁 / 它在哪个类里 / 它在结构的什么位置" —— 给出从该节点一路到根的祖先链。拿到一个光秃秃的方法名，想知道它挂在哪个类下，就用它。

**用法**：`carve -p <文件> path <节点ID> [--levels N]`

**常用选项**
- `--levels N`　只看上面几层（默认全部）

**示例**
- `carve -p app.py path 'module::Counter::bump'`　看这个方法挂在哪
- `carve -p app.py path 'module::Counter::bump' --levels 2`　只看最近两层

**备注**：①返回是从节点自己往上排的（自己 → 所在 block → 所在类 → module）。②其实是 `上游 ancestors` 的用法 —— "这个函数在哪个类里"这类问法全靠它。③ID 记不准时可以先用 `ls --pattern` 反查。

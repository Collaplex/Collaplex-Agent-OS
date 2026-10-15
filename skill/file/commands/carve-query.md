# carve query · 按语法模式找代码（tree-sitter 查询）

**用途**：按**语法模式**捞代码 —— 找出所有 return 语句、所有 f-string、所有带某个装饰器的函数、所有调用了某函数的行。比 `grep` 准：它认语法，不会把注释和字符串里的同名字算进来。

**用法**：`carve -p <文件> query '<tree-sitter 查询>' [--scope 节点ID]`

**常用选项**
- `--scope 'module::Counter'`　只在某个节点里找

**示例**
- `carve -p app.py query '(function_definition name: (identifier) @n)'`　列出所有函数名
- `carve -p app.py query '(return_statement) @r'`　找出所有 return
- `carve -p app.py query '(call function: (identifier) @f)'`　找出所有被调用的函数名
- `carve -p app.py query '(class_definition name: (identifier) @c)'`　列出所有类

**备注**：①查询是 tree-sitter 那套语法（S 表达式），`@名字` 是给命中项起的标签，结果里按标签给。②模式写错了会报 `invalid pattern`，退回用 `ls --pattern` 也能凑合找。③每条命中都带 `node_id` —— 可以直接接着拿去 `update` / `rm`。

# xargs · 把输入变成命令行参数

**用途**：把上一条命令的输出当参数喂给下一条 —— "一批东西逐个处理"。

**用法**：xargs [选项] 命令

**常用选项**
- `-n 1`　一次传 1 个参数（逐条跑）
- `-I{}`　占位符（`find … | xargs -I{} cp {} /目标/`）
- `-0`　★ 用 NUL 分隔（**配 `find -print0`**，文件名带空格/换行也不出错）
- `-P 4`　并行 4 个
- `-r`　输入为空就不跑（不加会跑一次空的）

**示例**
- `find . -name "*.log" -print0 | xargs -0 rm`　★ 安全批删
- `find . -name "*.md" | xargs -n1 wc -l`　逐个文件数行
- `find . -name "*.txt" -print0 | xargs -0 -P4 md5sum`　并行算哈希
- `cat 列表.txt | xargs -I{} mkdir -p 输出/{}`

**备注**：★ **不带 `-0` 时文件名里的空格会把参数切错** —— 配 `find` 就固定用 `find -print0 | xargs -0`。★ 参数多到报 "Argument list too long" 时，xargs 正是解法。★ **批删之前先 `| head` 看一眼要删什么**。

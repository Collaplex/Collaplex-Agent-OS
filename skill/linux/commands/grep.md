# grep · 按内容搜文本

**用途**：在文件或输入流里按模式（正则）搜索，输出匹配的行。

**用法**：grep [选项]... 模式 [文件]...

**常用选项**
- `-i`　忽略大小写
- `-r`　递归搜目录
- `-n`　显示行号
- `-l`　只出文件名
- `-v`　反向，不匹配的行
- `-E`　扩展正则（`-P` Perl 正则）
- `-A/-B/-C N`　带后 / 前 / 前后 N 行上下文

**示例**
- `grep -rn "save_to_tier2" --include='*.py' skill/`　这个函数在哪被用
- `grep -i error logs/*.log | tail -20`　日志里的报错
- `grep -rn "旧名字" --include='*.md' .`　哪些文档还留着旧名字
- `tail -f log | grep --line-buffered 关键字`　边跟边过滤

**备注**：搜代码记得排除噪音：`--exclude-dir={.git,__pycache__,node_modules}`。本机 grep 是 GNU 版（中文提示），跟 ls / tail 那些 Rust 版不是一套。★改完代码用 `grep -rn` 扫一遍旧名字是这项目的硬规矩。

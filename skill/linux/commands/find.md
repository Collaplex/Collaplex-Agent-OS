# find · 按条件找文件

**用途**：按名字、时间、大小、权限等条件递归查找文件，并能直接对结果执行动作。

**用法**：find [路径...] [表达式]

**常用选项**
- `-name '模式'`　按名字（区分大小写；`-iname` 不区分）
- `-maxdepth N`　只往下找 N 层
- `-type f|d|l`　只要文件 / 目录 / 符号链接
- `-size +100M`　大于 100M（`-100k` 小于）
- `-mtime -7`　7 天内改过的（`+30` 更早）
- `-exec 命令 {} +`　对每个结果执行命令

**示例**
- `find ~/桌面 -maxdepth 3 -name '*.md'`　找 md 文件
- `sudo find /mnt/data -type f -size +1G`　大文件在哪
- `find . -name '*.py' -mtime -1`　今天改过的 py
- `find ~/归档 -type f -name '*.tar'`　先看一眼，确认了再加 `-delete`

**备注**：★别一上来就 `find /` —— 本机 `/mnt/data` 是 VM 盘、`/proc` 和 `/sys` 是虚拟的，全盘扫又慢又刷一屏无权限。先用 `-maxdepth` 限深度、缩到具体目录再往广了搜。

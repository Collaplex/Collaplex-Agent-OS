# ss · 看端口和连接

**用途**：查看当前网络连接、监听端口、socket 统计（netstat 的现代替代品）。

**用法**：ss [选项] [过滤器]

**常用选项**
- `-l`　只看监听中的端口
- `-t` / `-u`　TCP / UDP
- `-n`　不解析服务名和域名（数字直出，更快）
- `-p`　显示占用端口的进程（别人的进程要 sudo）
- `-a`　所有 socket
- `-s`　汇总统计

**示例**
- `ss -ltnp`　哪些端口在监听、谁在听
- `ss -ltnp | grep 8789`　8789 被谁占了
- `ss -tn state established`　已建立的连接
- `sudo ss -lunp`　UDP 监听（要 sudo 才看得到别人的进程）

**备注**：`-p` 显示的是**打开这个 socket 的进程**，不一定是你以为的那个服务（filter-chain、systemd socket 激活都会出现在这）。本机常见端口：8789 音效面板、43953 LM Studio、8199 嵌入服务、5432 PostgreSQL、8788 空间音频面板。

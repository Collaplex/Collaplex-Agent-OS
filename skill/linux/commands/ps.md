# ps · 看进程

**用途**：列出当前进程快照 —— **现在跑着哪些进程**、谁在跑、占多少 CPU 和内存、用什么参数启动的。

**用法**：ps [选项]

**常用选项**
- `aux`　所有用户的全部进程（最常用）
- `-ef`　另一种常用格式（带 PPID、完整命令行）
- `--sort=-%mem`　按内存降序（`-%cpu` 按 CPU 降序）
- `-o pid,comm,%cpu,%mem,args`　自选列
- `-p PID`　只看某个 PID
- `--forest`　按父子关系画树

**示例**
- `ps aux --sort=-%mem | head -12`　谁最吃内存
- `ps aux --sort=-%cpu | head -12`　谁最吃 CPU
- `ps -o pid,ppid,etime,args -p 1234`　某个进程跑了多久、什么参数
- `ps --forest -o pid,args`　看父子关系

**备注**：★ **`ps aux` 的 `TIME` 列是累计 CPU 时间、不是运行时长**（多核跑满会远大于墙钟）—— 要答"**跑了多久**"得用 `etime`（`ps -o pid,etime,args -p PID`）。实测把 5 小时 14 分的进程读成"已累计运行 1616 分钟"。★杀进程前必须先 `ps aux` 看**完整路径**认归属 —— 本机上 snap 版 Blender 和 `~/Applications` 里的 Blender 是两个东西，杀错就杀了老板正在用的窗口。★统计进程别用 `ps w | grep`（会截断，还把你自己的 grep 算进去），判存活看 `/proc/<PID>/cmdline`。

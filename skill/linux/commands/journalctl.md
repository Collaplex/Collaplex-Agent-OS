# journalctl · 看系统和服务日志

**用途**：查 systemd 的日志（内核、服务、用户会话都在里面），支持时间过滤和实时跟踪。

**用法**：journalctl [选项] [匹配...]

**常用选项**
- `-u 单元`　只看某个服务的日志
- `-f`　实时跟踪（类似 `tail -f`）
- `-n 100`　只出最后 100 行
- `--since '10 min ago'` / `--until`　时间窗
- `-p err`　只看 error 及以上
- `-b`　本次开机以来（`-b -1` 上一次开机）
- `--no-pager`　不分页（脚本里必加）

**示例**
- `journalctl -u nginx -n 50 --no-pager`　nginx 最近 50 行
- `journalctl -f -u 单元名`　盯着看
- `journalctl --since '2026-10-06 13:00' -p err`　今天下午的错误
- `journalctl -b -1 -u ssh`　上次开机 ssh 出了什么

**备注**：看别的服务的日志要 `sudo`（或把用户加进 `systemd-journal` 组）。★脚本里调 journalctl **必须带 `--no-pager`**，否则会挂在分页器上不动。

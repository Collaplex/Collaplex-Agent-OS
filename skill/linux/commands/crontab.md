# crontab · 管定时任务

**用途**：列出、编辑、删除当前用户的定时任务表。

**用法**：crontab [-u 用户] [-n] 文件　|　crontab [-u 用户] [-i] {-e | -l | -r}

**常用选项**
- `-l`　列出当前任务
- `-e`　编辑（用默认编辑器）
- `-r`　删除全部（★危险）
- `-i`　删除前先问一句
- `-n`　只检查语法，不安装
- `-u 用户`　指定用户（要 sudo）

**示例**
- `crontab -l`　看自己的定时任务
- `sudo crontab -l`　看 root 的
- `crontab -l > /tmp/bak.cron`　改之前先备份
- `crontab /tmp/new.cron && crontab -l`　换一份任务表再确认

**备注**：★这台机器 root crontab 里有每分钟跑的（`flock -n ... refine.py --安静`），历史上还出过 `*/2 分钟重建静态页` 把删掉的页面又变回来的坑 —— **动 crontab 前先 `-l` 看全，改前先备份**。★定时任务跑失败是静默的，排查看日志或 `grep CRON /var/log/syslog`。

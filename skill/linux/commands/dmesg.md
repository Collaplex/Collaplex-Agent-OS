# dmesg · 看内核日志

**用途**：内核和驱动打的日志 —— 硬件识别、USB/显卡报错、OOM 杀进程、网卡异常。

**用法**：dmesg [选项]

**常用选项**
- `-T`　时间显示成人话（不是开机秒数）
- `-l err,warn`　只看错误和警告
- `-H`　带分页
- `-k`　只看内核消息

**示例**
- `journalctl -k -n 50 --no-pager`　★ 本机走这条（见备注）
- `journalctl -k -p err -n 30 --no-pager`　内核错误
- `journalctl -k | grep -iE "usb|nvme|oom"`　找某类

**备注**：★ **本机 `dmesg` 直接跑会被拒**（实测 `读取内核缓冲区失败: 不允许的操作`，即 dmesg_restrict=1），而 sudo 走不通（护栏拦 sudo）—— 要看内核日志请用 **`journalctl -k`**（实测免 sudo 可用 ✓，内容等价）。这条单列出来，就是为了让"想看 dmesg"的时候有个走得通的路。

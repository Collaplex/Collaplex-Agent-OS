# mount · 挂载文件系统 / 看当前挂载

**用途**：挂载文件系统；不带参数单独跑时，列出当前所有已挂载的文件系统。

**用法**：mount [-lhV]　|　mount -a [选项]　|　mount [选项] <源> <目录>

**常用选项**
- 不带参数　列出所有已挂载的文件系统
- `-t 类型`　只看（或只挂）指定类型
- `-o 选项`　挂载选项（ro / rw / noexec / uid=…）
- `-l`　顺带显示文件系统标签
- `-a`　按 /etc/fstab 全部挂载
- `-f`　假装挂载（dry run，不真调 mount(2)）

**示例**
- `mount | grep nvme`　看 NVMe 上挂了什么
- `mount | column -t`　对齐好看
- `sudo mount /dev/sdb1 /mnt/disk`　挂一块盘
- `sudo mount -o remount,rw /`　根分区改回可写

**备注**：普通用户不能挂载，要 `sudo`。本机插移动硬盘/U 盘的省事办法是 `udisksctl mount -b /dev/sdX`（免 sudo，但挂载点由 udisks 定，挂上常是 root:root 不可写，要补一句 `sudo chown lou:lou <挂载点>`）。卸载命令是 `umount`（是 umount，不是 unmount）。

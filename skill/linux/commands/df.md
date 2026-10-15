# df · 看磁盘空间

**用途**：显示每个挂载点（文件系统）的空间使用情况，默认列出所有已挂载的文件系统。

**用法**：df [选项]... [文件]...

**常用选项**
- `-h`　以 1024 为基底显示大小（1023M）
- `-H`　以 1000 为基底显示（1.1G）
- `-T`　顺带显示文件系统类型
- `-i`　看 inode 用量，而不是块用量
- `-t 类型`　只显示指定类型的文件系统
- `--output=字段列表`　自定义列：source, fstype, size, used, avail, pcent, target
- `--total`　末尾加一行总计

**示例**
- `df -h`　所有挂载点，人类可读
- `df -h /home`　只看这个目录所在的盘
- `df -hT`　带文件系统类型（认 ext4 / tmpfs / ntfs）
- `df --output=target,size,avail,pcent | sort -k4 -r`　按占用百分比排

**备注**：六列是 Filesystem / Size / Used / Avail / Use% / Mounted，**看 Use% 那列**（>80% 留意，>95% 快满）。本机盘况（2026-10-06 实测）：根 `/` = nvme0n1p3 686G（用 36%）、`/mnt/data` 251G 是给 Windows VM 的（用 67%）、`/tmp` 和 `/dev/shm` 是 tmpfs 内存盘（会被清空，大文件别放）。外接硬盘平时不挂，插上要手动挂。

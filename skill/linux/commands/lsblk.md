# lsblk · 看有哪些盘和分区

**用途**：看磁盘和分区 —— 插的 **U 盘 / 移动硬盘 / 新硬盘认到没**、有几块盘、分区怎么分、型号容量、挂载点、文件系统类型。

**用法**：lsblk [选项] [<设备> ...]

**常用选项**
- `-f`　显示文件系统类型、UUID、挂载点
- `-o 列名`　自定义列：NAME, SIZE, TYPE, FSTYPE, MOUNTPOINT, LABEL, MODEL
- `-l`　列表格式（不画树）
- `-p`　显示完整设备路径（/dev/sda1）
- `-d`　只看盘，不列分区
- `-e 7`　排除主设备号为 7 的设备（本机就是那几十个 snap loop）
- `-J`　JSON 输出

**示例**
- `lsblk`　树形看盘和分区
- `lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT | grep -v loop`　干净版本
- `lsblk -e 7 -f`　排除 loop，带文件系统信息
- `lsblk -d -o NAME,SIZE,MODEL`　只看有几块物理盘、什么型号

**备注**：本机 `lsblk` 默认会吐几十个 `loop` 设备（都是 snap 包的 squashfs），**别以为盘挂了**，用 `-e 7` 滤掉。实测（2026-10-06）：nvme0n1 是唯一一块内置 NVMe —— p1 300M `/boot/efi`、p2 251G `/mnt/data`（Windows VM）、p3 686G `/`；外接盘平时不插。

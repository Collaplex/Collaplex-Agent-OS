# lspci · 看 PCI 设备

**用途**：列出 PCI/PCIe 设备 —— 显卡、网卡、存储控制器、声卡，以及它们用的**内核驱动**。

**用法**：lspci [选项]

**常用选项**
- `-k`　★ 每个设备用的内核驱动 + 模块（排查"驱动没上"必看）
- `-v`　详细信息（`-vv`/`-vvv` 更细）
- `-nn`　同时显示名字和 ID
- `-t`　设备树
- `-d 厂商:设备`　筛指定设备

**示例**
- `lspci | grep -iE "vga|3d|display"`　显卡
- `lspci -k | grep -A3 -i vga`　★ 显卡 + 它当前用的驱动
- `lspci | grep -iE "ethernet|network"`　网卡
- `lspci -nn | grep -i nvidia`　NVIDIA 设备（带 ID）

**备注**：★ 判"这块卡有没有驱动管"看 **`lspci -k`** 里的 `Kernel driver in use:` 那行（没有就是没驱动）。★ 本机显卡：AMD 核显 + NVIDIA RTX 5060（两块都会列出）。★ 外接屏认没认要另看 `/sys/class/drm/cardX-DP-Y/status`，**不是** lspci 能判的。★ `-xxx` 那些十六进制转储要 root，别用。

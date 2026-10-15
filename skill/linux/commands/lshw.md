# lshw · 看硬件清单

**用途**：把整机硬件列成树 —— 主板、CPU、内存条、硬盘、网卡、显卡的型号与能力。

**用法**：lshw [选项]

**常用选项**
- `-short`　★ 精简列表（H/W path + 类别 + 描述），一眼看全
- `-C 类别`　只看某类：`cpu` `memory` `disk` `network` `display` `system`
- `-businfo`　按总线列（和 `lspci`/`lsusb` 对得上）
- `-json` / `-html` / `-xml`　结构化输出

**示例**
- `lshw -short`　★ 硬件总览（本机**免 sudo 可用** ✓）
- `lshw -C memory -short`　内存条槽位与容量
- `lshw -C disk -short`　硬盘型号
- `lshw -C network -short`　网卡

**备注**：★ 免 sudo 能跑，但**详细信息（序列号、完整描述）需要 root**，会打警告 —— 正常现象。★ 想一口气说清"这台机器什么配置"，用它比 `lspci`+`lsusb` 更整机视角（CPU 型号/核数、内存槽位都在这）。★ 内存**槽位**看 `-C memory`（本机 B 槽空着、只有一条 16G，就是在这看出来的）。

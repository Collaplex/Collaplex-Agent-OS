# ip · 看网卡 / 地址 / 路由

**用途**：看和改网络 —— 网卡状态、IP 地址、路由表、邻居（ARP）。

**用法**：ip [-brief] 对象 [命令]

**常用对象**
- `ip -br a`　★ 一行一块网卡：状态 + IP（最常用）
- `ip link`　链路层（网卡开没开、MAC）
- `ip r`　路由表（默认网关走哪）
- `ip neigh`　ARP 表（同网段谁在线）
- `ip -s link`　收发统计（丢包/错误计数）

**示例**
- `ip -br a`　所有网卡的地址一览
- `ip r | head -5`　默认路由是哪块网卡
- `ip -s link show enp3s0`　这块网卡的收发统计（有 errors/dropped 才疑似线路问题）
- `ip -br a | grep -v DOWN`　只看起来的网卡

**备注**：★ 老教程里的 `ifconfig` / `netstat` 在新系统已退役（本机没有）—— 一律换 `ip`（连接/端口统计用 `ss`）。★ 本机网卡：有线 `enp3s0`、无线 `wlp4s0`（AP 是 GL-MT3000）。★ 判无线延迟必须 `ping -I wlp4s0`：有线插着时默认走有线，得到的是假数据。

# nmap · 端口与服务扫描

**用途**：扫目标主机哪些端口开着、上面跑什么服务、什么版本 —— 侦察第一步。也被叫「网络地图」（Network Mapper），能扫单机、整个网段，支持 TCP/UDP/SCTP，还能跑脚本（NSE）做漏洞探测。

**用法**：nmap [扫描类型] [选项] 目标

目标写法：`127.0.0.1`、`192.168.10.1`、`192.168.10.0/24`、`10.0.0-255.1-254`、`scanme.nmap.org`。

**常用选项**

扫描类型
- `-sT`　TCP connect 扫描（走完整三次握手）　★ **不需要 root**，本机默认用这个
- `-sS`　SYN「半开」扫描（快、隐蔽、不发完整握手）　**需要 root**：实测本机普通用户跑直接报 `You requested a scan type which requires root privileges. QUITTING!`
- `-sU`　UDP 扫描（查 DNS/SNMP 等 UDP 服务）　**需要 root**，本机实测同样被拒
- `-sA`　ACK 扫描（专用来探防火墙规则，不判开/关）　需要 root
- `-sN` / `-sF` / `-sX`　Null/FIN/Xmas 扫描（绕过部分过滤，结果常是 `open|filtered`）　需要 root
- `-sn`　只做主机存活探测（ping 扫描），不扫端口
- `-sL`　只列目标、不发包（List scan）

端口
- `-p 22,80,443`　指定端口；`-p 1-1024` 范围；`-p-` 全 65535 个端口
- `-p T:80,U:53`　分别指定 TCP / UDP 端口
- `-F`　快速模式，只扫最常用的一小撮端口
- `--top-ports 100`　扫最常见的 100 个端口
- `--exclude-ports 1-1024`　排除某些端口

探测内容
- `-sV`　探服务与版本（**判断「真是什么服务」靠它，别信默认服务名**）
- `--version-intensity 0~9`　版本探测强度（默认 7）；`--version-light`(=2) 快、`--version-all`(=9) 全探
- `-O`　猜操作系统　**需要 root**：实测报 `TCP/IP fingerprinting (for OS scan) requires root privileges.`
- `--osscan-guess`　OS 猜得更激进
- `-sC`　跑默认类 NSE 脚本（等同 `--script=default`）
- `--script <名|类别|文件>`　跑指定脚本（如 `http-title`、`vuln`、`discovery`）
- `--script-args n1=v1,n2=v2`　给脚本传参
- `--script-help <名>`　看某个脚本干什么
- `-A`　「全家桶」= `-O -sV -sC --traceroute` 一起上（**含 -O，所以要 root**）

主机发现与性能
- `-Pn`　跳过 ping 存活探测（对禁 ICMP 的主机**必须加**，否则可能直接报 host down）
- `-n`　不做 DNS 反解（快很多）；`-R` 反过来强制反解
- `-T0~5`　时序档位（越高越快，局域网内用 `-T4`）
- `--min-rate 500` / `--max-rate`　每秒最少/最多发包数（想快用 `--min-rate`）
- `--host-timeout 30s`　单主机超时就放弃
- `--traceroute`　顺带做路由追踪

输出与其它
- `--open`　只显示开着的端口
- `-v` / `-vv`　啰嗦模式；`-d` / `-dd` 调试模式
- `--reason`　显示判定每个端口状态的依据（如 `syn-ack` / `conn-refused`）
- `-oN 文件` / `-oX 文件` / `-oG 文件`　分别输出普通 / XML / grep 三种格式
- `-oA 前缀`　一次生成三种格式（写 `前缀.nmap`/`.xml`/`.gnmap`）
- `--resume 文件`　从被中断的扫描继续
- `-6`　扫 IPv6
- `-iL 文件`　从文件读目标列表；`--exclude 主机` / `--excludefile 文件` 排除目标

**示例**（★ 标出的都是在本机/自有设备实测跑过的）

- `nmap -sT -p 22,80,443 127.0.0.1`　扫本机常用端口　→ ★ 实测：22/tcp **open**（ssh），80/tcp 与 443/tcp **closed**（http/https）
- `nmap -sT -p 22,80,443,8199,8789 127.0.0.1`　看几个本机服务　→ ★ 实测：8199 被标 `vvr-data`、8789 被标 `unknown`，**服务名是猜的，不可信**（见「备注」）
- `nmap -sT --open --reason -p 1-100 127.0.0.1`　只列开着的并显示判定理由　→ ★ 实测：只剩 `22/tcp open ssh`，REASON 列是 `syn-ack`
- `nmap -sV -sT -p 22 127.0.0.1`　探版本　→ ★ 实测：`OpenSSH 10.2p1 Ubuntu 2ubuntu3.7`，**这才是真信息**
- `nmap -sT -Pn -p 22,53,80,443,8080 192.168.10.1`　扫自有软路由的几个端口　→ ★ 实测（主机名 `doh.lan`）：全部 **filtered** —— 路由器把探测包丢了，说明有防火墙
- `nmap -sT -T4 -Pn -p 80,443 192.168.10.0/24`　扫自有整个网段（**只对自有网段**）
- `nmap -sC -sV -p 22 127.0.0.1`　对 SSH 跑默认脚本 + 版本探测
- `nmap -sT -p- --open -T4 -oA 扫描结果 目标`　全端口、只列开着、结果落三份
- `nmap -sT --script http-title -p 80,443 目标`　顺手把网页标题抓回来

**备注**

- ★ 本机 nmap 是 **7.98**（`nmap --version` 可看）。**不加 sudo 也能扫**，但只能用 `-sT`；写 `-sS` / `-sU` / `-O` / `-A` / `-sA` / `-sN`-`-sF`-`-sX` 会因权限直接失败、报 `requires root privileges`。要权限的扫描标注「需要 root，得人手动 sudo 跑」。
- ★ **服务名是 nmap 自己的指纹库猜的，不可信**：实测扫本机，8199 端口被标成 `vvr-data`、8789 标成 `unknown`，实际一个是向量服务、一个是音效面板。默认服务名只按端口号对 `/etc/services` 查表或按指纹粗判；要判断真是什么，得 `-sV` 探版本，再自己 `curl` / 连一下确认。
- ★ **端口状态有六种**（官方 Reference Guide，`https://nmap.org/book/man-port-scanning-basics.html`）：`open`（有程序在听）、`closed`（能收到包、回 RST，但没人听）、`filtered`（探测包被防火墙/路由规则挡了，nmap 判不出开还是关 —— 本机实测扫软路由 `192.168.10.1` 全是这个）、`unfiltered`（可达但判不出开/关，只有 ACK 扫描给这个状态）、`open|filtered`（判不出是开还是被滤，UDP/FIN/NULL/Xmas 会给）、`closed|filtered`（判不出是关还是被滤，只有 idle 扫描给）。**这些状态描述的是「nmap 怎么看它」，不是端口本身的属性** —— 同一端口，同网段扫是 open，跨防火墙扫可能就变 filtered。
- ★ `filtered` 会**显著拖慢**扫描：nmap 会反复重试以区分「真被挡」和「只是丢包」，遇到一片 filtered 要有耐心，或加 `--host-timeout` 封顶。
- ★ 默认扫的是**最常见的 1000 个 TCP 端口**，不是全 65535；要全覆盖得显式 `-p-`。
- ★ 扫之前先确认**是自有或已授权目标**；本库只用于本机与自有设备。

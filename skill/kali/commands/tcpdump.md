# tcpdump · 抓包

**用途**：把一块网卡上过的包抓下来看 —— 排查握手、DNS、谁在跟谁说话。基于 libpcap，抓的是原始链路层帧；`-w` 存成 `.pcap` 就能丢给 Wireshark 慢慢拆。

**用法**：tcpdump [选项] [过滤表达式]

**常用选项**

选网卡与范围
- `-i <网卡|any>`　抓哪块网卡（`any` = 所有网卡；`-D` 列出所有网卡）
- `-D`　列出可用网卡就退出（**实测：无需抓包权限也能跑**）
- `-c 10`　抓够 10 个包就停
- `-p`　不进入混杂模式（只看发给本机的流量）
- `-Q in|out|inout`　只抓进 / 只抓出 / 双向

显示格式
- `-n` / `-nn`　不做域名 / 端口名反解　**必加**，否则会卡在反解上
- `-e`　显示链路层头（能看 MAC 地址）
- `-A`　载荷按 ASCII 显示（看 HTTP 文本）
- `-X` / `-XX`　载荷按 hex + ASCII 显示（`-XX` 连链路层头一起）
- `-x` / `-xx`　载荷按纯 hex 显示
- `-s 0`　抓完整包（改 snaplen；新版本默认已抓全，老版本默认截断）
- `-q`　精简输出（每行更短）
- `-t` / `-tt` / `-tttt`　不显时间戳 / 显 Unix 秒 / 显完整日期时间
- `-v` / `-vv` / `-vvv`　越加越啰嗦（`-v` 出 TTL、长度等，`-vv` 再解 SMB/NFS）
- `-#`　每行前加包序号

落盘与读回
- `-w 文件.pcap`　把原始包写盘（给 Wireshark 看）
- `-r 文件.pcap`　读回之前存的 pcap（可配过滤表达式复用）
- `-C 100`　写满 100 MB 就换下一个文件（配合 `-w`）
- `-G 60`　每 60 秒轮转一个新文件（文件名的 `-w` 里可带 strftime 时间格式，配合 `-W 10` 限个数）
- `-U`　每抓到一个包立刻写盘（默认是攒够缓冲才写）；`-l` 让 stdout 行缓冲（边抓边看）

其它
- `-B 4096`　设内核抓包缓冲（单位 KiB）
- `-K`　跳过校验和验证
- `-d`　把过滤表达式编译成汇编打出来（调试过滤用）
- `-F 文件`　从文件读过滤表达式
- `-Z 用户`　抓包后丢弃到指定用户权限跑（默认已启用）

**过滤表达式**（BPF / pcap-filter 语法，写在选项后面）

- 主机：`host 8.8.8.8`、`src 192.168.10.1`、`dst host 10.0.0.5`
- 网段：`net 192.168.10.0/24`、`net 10.0.0.0 mask 255.0.0.0`
- 端口：`port 53`、`portrange 8000-9000`、`tcp port 443`、`udp dst port 67`
- 协议：`icmp`、`arp`、`tcp`、`udp`、`ip6`
- 组合：`and` / `or` / `not`（或 `&&` / `||` / `!`），如 `tcp and port 443 and not host 10.0.0.1`
- 位运算：`tcp[tcpflags] & (tcp-syn|tcp-fin) != 0`（抓带 SYN 或 FIN 标志的包）、`tcp[13] & 2 != 0`
- 长度：`greater 1000`、`less 60`、`len > 576`

**示例**（★ 标出的都在本机实测跑过）

- `tcpdump -D`　列出本机网卡　→ ★ 实测：输出 `1.enp3s0`、`2.wlp4s0`、`3.any`、`4.lo` 等，**这一步不需要抓包权限**
- `tcpdump -i any -nn icmp`　看谁在 ping　→ ★ 实测（无 sudo）：`tcpdump: any: You don't have permission to perform this capture on that device`，直接失败
- `tcpdump -i wlp4s0 -nn -c 20 port 53`　抓 20 个 DNS 查询
- `tcpdump -i any -nn 'tcp port 443'`　抓本机所有 HTTPS 流量
- `tcpdump -i any -nn -w 输出.pcap tcp port 443`　存下来再拿 Wireshark 拆
- `tcpdump -r 输出.pcap -nn -X`　读回已存的包并按 hex+ASCII 显示（`-r` 不需要抓包权限）
- `tcpdump -i any -nn -e arp`　看 ARP（带 `-e` 能看到 MAC）
- `tcpdump -i any -nn -w cap.pcap -C 100 -W 10 host 192.168.10.1`　抓与自己软路由的流量，每 100 MB 切一个、最多留 10 个

**备注**

- ★ 本机 tcpdump **4.99.6**（`tcpdump --version`; 过滤表达式语法见 `man 7 pcap-filter`）。
- ★ **普通用户跑 tcpdump 会被拒**：`tcpdump: any: You don't have permission to perform this capture on that device`（要 `CAP_NET_RAW`）。实测本机就是这样 —— **真正抓包在本机跑不了**，要看连接状态改用 `ss -tnp` / `lsof -i`（都在 linux 技能里）。
- ★ 想让它能用（**需要 sudo，得人手动来**）：`sudo setcap cap_net_raw,cap_net_admin+eip /usr/bin/tcpdump`，之后普通用户也能抓。
- ★ **例外**：`tcpdump -D`（列网卡）和 `tcpdump -d '<过滤>'`（编译过滤表达式看汇编）**不需要抓包权限**，实测都能在普通用户下跑 —— 想先确认过滤写法对不对可以先用 `-d`。
- ★ **`-w` 落盘 vs 屏幕显示**：`-w` 写的是**原始包**（含链路层头、按 snaplen 截断），不能同时再往屏幕打印；过滤表达式仍照常生效。想给 Wireshark 用就 `-w`，想眼睛直接看就别 `-w`。读回用 `-r`。
- ★ **过滤表达式是 BPF 语法**（man 7 pcap-filter）：端口名要能在 `/etc/services` 里查到，主机名要能解析；`and/or/not` 可省成 `&&/||/!`，连续同前缀可省写。**表达式记得加引号**，否则 shell 会把 `>`、`|`、`(` 当重定向/管道吃掉。语法记不清先 `tcpdump -d '你的表达式'` 验证。
- ★ `-e` 才能看 MAC 和判断二层来源；`-Q in/out` 区分进/出方向；`-nn` 连主机名和端口名都不解析，脚本里必加，否则卡在反解。
- ★ **必须限定范围**：裸 `tcpdump -i any` 会刷屏还吃内存，至少带 `-c` 或具体过滤。

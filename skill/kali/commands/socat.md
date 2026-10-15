# socat · 端口转发 / 搭任意通道

**用途**：比 nc 强的"万能管道" —— 端口转发、TLS 包装、Unix socket 与 TCP 互转、串口读写。把任意两个"数据流"对起来，一侧是文件、管道、串口、socket 都行。

**用法**：socat [选项] <地址1> <地址2>

**常用地址形式**
- `TCP-LISTEN:8080`　本地监听（写 `TCP-LISTEN:8080,fork` 才能接多个）
- `TCP:主机:端口`　连出去
- `UDP-LISTEN:53` / `UDP:主机:端口`　UDP 版
- `OPENSSL:主机:端口,verify=0`　包一层 TLS（客户端）
- `OPENSSL-LISTEN:8443,cert=sv.crt,key=sv.key`　起个 TLS 服务端
- `UNIX-CONNECT:/tmp/x.sock` / `UNIX-LISTEN:/tmp/y.sock`　Unix socket
- `FILE:文件`　写/读普通文件；`EXEC:命令`、`SYSTEM:命令`　执行命令
- `STDIO` / `STDIN` / `STDOUT`　标准输入输出（配合 `-` 简写）
- `/dev/ttyUSB0,rawer,b9600`　串口（见下方 TERMIOS 选项）

**常用选项**

通用命令行选项：
- `fork`　每个连接开一个子进程（★ 不加只能接**一个**连接）
- `reuseaddr`　端口能立刻重用（重启不报 `Address already in use`）
- `-d -d`　打印更详细日志（排障必用；可到 `-d -d -d -d`）
- `-v`　把双向数据文本 dump 到 stderr；`-x`　十六进制 dump
- `-t<秒>`　关第二条通道前等几秒（把传输尾巴排空，别截断）
- `-T<秒>`　总空闲超时，超时自动退出
- `-u` / `-U`　单向模式（只左→右 / 只右→左，做个"只发"的管道）
- `-b<字节>`　缓冲区大小（默认 8192）
- `-s`　sloppy，出错继续不退出
- `-lf<文件>`　日志写文件；`-ly` 进 syslog；`-ls` 到 stderr（默认）

地址选项（写在地址后面用逗号连着）：
- `bind=<ip>`　绑源地址；`sourceport=<端口>`　绑源端口
- `keepalive`　开 TCP keepalive；`nodelay`　关 Nagle（小包低延迟）
- `range=<网段>`　只允许这个来源网段连进来；`tcpwrap[=名]`　走 hosts_access 校验
- `retry=<次数>` / `forever`　连接失败重试 / 永不放弃
- `readbytes=<n>`　读满 N 字节就断开；`ignoreeof`　遇到 EOF 不关通道（打交互程序用）
- TLS：`verify=0`　不校验对端证书；`cafile=`、`cert=`、`key=`　指定 CA / 证书 / 私钥
- 串口 TERMIOS：`raw`/`rawer`　原始模式、`echo=0`　关回显、`b9600`　波特率（全表 `socat -hh | grep ' b[1-9]'`）、`cs8`　8 数据位

**示例**
- `socat TCP-LISTEN:8080,fork,reuseaddr TCP:127.0.0.1:80`　把本机 8080 转发到本机 80（经典端口转发）
- `socat -d -d TCP-LISTEN:9000,fork FILE:日志文件`　收到的全写进文件，且打详细日志
- `socat TCP-LISTEN:2375,fork UNIX-CONNECT:/var/run/docker.sock`　Unix socket ↔ TCP 互转（★ 别在公网开）
- `socat - OPENSSL:example.com:443,verify=0`　从标准输入连一个 TLS 端口，敲 HTTP 手写请求
- `socat OPENSSL-LISTEN:8443,cert=sv.crt,key=sv.key,fork TCP:127.0.0.1:80`　给一个明文服务套上 TLS 壳
- `socat - /dev/ttyUSB0,rawer,b9600,echo=0`　串口读写，终端上直接对着设备敲
- `socat TCP-LISTEN:4444 EXEC:/bin/bash,pty,stderr,setsid,sigint,sane`　反连 shell 的原理（★ 只在自有设备上做）
- `socat - TCP:8.8.8.8:53`　手工构造 DNS 查询用（配 `-x` 看二进制）

**备注**：
★ 本机 socat **1.8.1.1**（`socat -V` 看版本与编入的特性，本机带 OPENSSL / TUN / UNIX / SOCKS5 / SYSTEM 等）。
★ **忘了 `fork` 就只能接一个连接**，第二次连直接卡住 —— 最常见的坑。实测本机 `socat TCP-LISTEN:18080,fork,reuseaddr TCP:127.0.0.1:8642` 能把本机服务正常转发，`-d -d` 日志会打出 `listening` → `accepting connection` → `forked off child` → `opening connection` → `starting data transfer loop` → `socket ... is at EOF` → `exiting with status 0` 一整条生命周期。
★ 转发不通先加 `-d -d`，socat 会把 bind / listen / accept / connect 每一步都打出来，比猜快。
★ 地址选项是**逗号**分隔、不是空格；写成 `TCP-LISTEN:8080 fork`（空格）会被当成第二个地址，直接报错。地址里的主机/端口用**单冒号**分隔（`TCP:host:port`），别和选项的 `=` 混了。
★ `EXEC:` / `SYSTEM:` 能执行命令，这正是"反连 shell"的原理 —— **只在自有设备上做**。`EXEC` 走的是 `execvp`（不经 shell，逗号当参数分隔），`SYSTEM` 走 `/bin/sh -c`（能写管道重定向）。
★ EOF 处理：默认一侧读到头就关整个通道；打交互程序（bash、编辑器）常挂，加 `ignoreeof` 或 `-t<秒>` 缓冲一下就不容易断。
★ `-u`/`-U` 单向模式很容易被忽略：只发不收时它能防止 socat 等回程数据而卡住。

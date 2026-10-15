# hydra · 在线口令爆破

**用途**：对**真实在跑的服务**挨个试账号口令 —— ssh、ftp、rdp、http 表单、smb、数据库等几十种协议。和 hashcat 的区别：hashcat 是拿现成的哈希**离线**算，hydra 是拿着账号口令一遍遍**联网去问服务端对不对**（每试一次就是一次真实登录请求）。

**用法**：`hydra [[[-l 用户|-L 用户表] [-p 口令|-P 口令表]] | [-C 冒号表]] [选项] 服务://目标[:端口][/路径]`

**常用选项**（本机 `hydra -h` 实测存在）
- `-l 单个用户` / `-L 用户表文件`
- `-p 单个口令` / `-P 口令表文件`
- `-C 文件`　一行一个 `用户:口令`，替代 -L/-P
- `-t TASKS`　每个目标并发连接数，**默认就是 16**（比想象激进，调小更安全）
- `-T TASKS`　所有目标合计并发（配 -M 批量时，默认 64）
- `-f` / `-F`　找到一个就停（-M 批量时 `-f` 每台停、`-F` 全局停）
- `-s 端口`　服务在非默认端口时指定
- `-e nsr`　额外试三种：`n`=空口令，`s`=口令等于用户名，`r`=用户名倒过来
- `-o 文件`　结果写文件（配合 `-b json` 可输出 json / jsonv1）
- `-M 目标列表文件`　批量，一行一个目标（`主机:端口` 可带端口）
- `-u`　按用户轮转而不是按口令轮转（配合 -x 时自动开）
- `-x MIN:MAX:字符集`　内置暴力枚举生成口令（不想用词表时；`hydra -x -h` 看细分）
- `-w 秒` / `-W 秒`　单次响应等待 / 每次连接间隔
- `-V`　把每次尝试的 用户+口令 都打出来（默认只打成功的）；`-v` 详细、`-d` 调试
- `-4` / `-6`　走 IPv4（默认）/ IPv6
- `-K`　不重试失败的尝试（配合 -M 做大范围扫描时有用）
- `-q`　不打印连接错误信息
- `-U`　打印某协议模块的用法帮助（如 `hydra -U http-post-form`）
- `-m OPT`　给某个模块传私有参数（见该模块 `-U` 输出）

**支持的协议**（`hydra -h` 实测列出的模块，节选）：`ssh` `ftp[s]` `rdp` `smb` `smb2` `mysql` `mssql` `postgres` `mongodb` `redis` `smtp[s]` `pop3[s]` `imap[s]` `vnc` `telnet[s]` `snmp` `ldap2[s]` `ldap3` `sip` `rtsp` `socks5` `http[s]-{head|get|post}` `http[s]-{get|post}-form` `http-proxy` `cisco` `cisco-enable` 等。

**http[s]-{post|get}-form 写法**（联网表单登录最常用，`hydra -U http-post-form` 实测）
- 三段式：`"路径:表单参数:失败条件"`，都用冒号隔开
  - `路径`：登录接口，如 `/login.php`
  - `表单参数`：把用户名/口令位置换成占位符 `^USER^` 和 `^PASS^`
  - `失败条件`：判定「这一对是错的」的字符串。默认裸写字符串表示**出现它就判失败**；也可写 `S=字符串`（出现它判**成功**）
- 可选修饰（夹在第三段条件里，也用冒号隔分）：`1=`(401 视为失败) `2=`(302 视为成功) `M=`(multipart 表单) `C=/uri`(先去别的页拿 cookie) `g=`(跳过预请求) `H=Header: 值`(自定义请求头，`^USER^`/`^PASS^` 也能塞进去)
- 例子（来自 `-U` 输出）：
  - `"/login.php:user=^USER^&pass=^PASS^:incorrect"`（出现 incorrect 判失败）
  - `"/login.php:user=^USER^&pass=^PASS^:S=result=success"`（出现 result=success 判成功）
  - `"/:user=^USER^&pass=^PASS^:H=Cookie\: sessid=aaaa"`（带自定义 Cookie，头里的冒号要 `\` 转义）

**示例**（口令表要自备 —— 本机 `/usr/share/wordlists` 不存在，下面演示怎么**自己造几行**）
```
# 造两张自己的小表（只在本机/自有靶机上用）
printf 'admin\nroot\ntest\n'        > 用户.txt
printf '123456\npassword\nletmein\n'> 口令.txt

# ssh：一行用户一行口令，找到一个就停
hydra -L 用户.txt -P 口令.txt -t 4 -f ssh://127.0.0.1

# http 表单登录（自建靶机）
hydra -l admin -P 口令.txt -t 4 127.0.0.1 http-post-form \
  "/login:user=^USER^&pass=^PASS^:F=密码错误"

# 批量 + 全局找到即停 + 结果写文件
hydra -L 用户.txt -P 口令.txt -M 目标.txt -F -o 命中.txt ssh
```

**备注**
- ★ 本机 **Hydra v9.6**。启动就打印一大段"别用于军事/秘密机构/非法用途"的横幅 —— **正常现象，不是报错**。
- ★ ★ **这是本库里最"重"的一条**：在线爆破会在目标日志里留一整片失败登录，**极易触发 fail2ban 封 IP、账号锁定、告警**。默认**不要跑**；只有自己的靶机 + 明确授权才用。
- ★ 词表要自备（本机一个都没有，`/usr/share/wordlists` 不存在），上面演示了现造几行的做法。
- ★ 协议必须写成 `ssh://目标` 这种形式，漏了协议会报 `no service`；服务在非默认端口要 `-s`。
- ★ 认到一对就停要加 `-f`（批量是 `-F`），否则它会试完整张表。
- ★ **为什么慢**：每一次尝试都是一轮完整的网络往返（还可能带 TLS 握手 / 预请求拿 cookie），服务端尤其怕打，`-t` 开大等于对人家做压测 —— 服务容易被拖垮或被 WAF/限速挡掉。默认 `-t 16` 已经不小，**先 `-t 4` 试**。所以在线爆破的吞吐量通常只有几十~几百次/秒，跟 hashcat 动辄每秒几十亿次完全不是一个量级。
- ★ `-V` 能看每一条尝试；`-o 命中.txt -b json` 便于结果被程序读走。
- ★ 来源：`hydra -h` / `hydra -U http-post-form`（本机实测）、官方仓库 <https://github.com/vanhauser-thc/thc-hydra>（hydra 横幅里自己打印的地址）。

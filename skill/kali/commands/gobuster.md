# gobuster · 目录 / DNS 子域 / 虚拟主机枚举

**用途**：**扫一个网站有哪些目录、页面、文件**（目录扫描 / 目录枚举）—— Go 写的枚举器，按模式干活：目录文件（`dir`）、DNS 子域（`dns`）、虚拟主机（`vhost`）、自由位置（`fuzz`），另附 `s3/gcs/tftp` 云存储与 tftp 枚举。速度快、默认就把 404 吞掉，输出干净。★ 找**网站目录**用这个或 `ffuf.md`；扫**端口/服务**才是 `nmap.md` 的活。*只对自有或已授权目标跑。*

**用法**：gobuster <模式> -u 目标 -w 词表 [选项]　（`dns` 模式用 `-d/--domain` 指定域名，不用 `-u`）

**模式**
- `dir`　目录 / 文件枚举（最常用）
- `vhost`　虚拟主机：同 IP 上按 Host 头找别的站点（`-u` 建议直接给 **IP**）
- `dns`　DNS 子域枚举（子命令是 `dns`，`-d` 给域名）
- `fuzz`　把 `FUZZ` 关键字替换进 URL / 请求头 / 请求体（最灵活）
- `s3` / `gcs` / `tftp`　对象存储桶 / TFTP 枚举

**常用选项**（`dir` / `fuzz` 模式，二者选项基本一致）
- `-u URL`　目标；`-w 词表`（**必给**，`-` 表示从 STDIN 读）
- `-x php,html,txt`　追加扩展名；`-X 文件`　从文件读扩展名；`-f`　给每个请求尾部补 `/`
- `-t 20`　线程（**默认 10**）；`--delay 500ms`　每线程请求间延时；`--timeout 10s`　超时
- `-q`　静默，不打印 banner / 进度；`-e`　expanded，打印完整 URL；`-n`　不打印状态码
- `-k`　跳过 TLS 证书校验；`-r`　跟随跳转；`--random-agent`　随机 UA；`-a "UA"`　指定 UA；`--proxy`　代理
- `-s 200,301,302`　正向状态码；`-b 404,403`　反向状态码（**默认屏蔽 404**，可接范围 `200,300-400`）
- `--exclude-length 0`　按响应长度过滤，支持范围 `203-206`；`--hide-length`　隐藏长度列
- `--discover-backup`　命中文件后再找 `.bak/.old/~` 等备份后缀；`-o 文件`　输出

**`dns` 模式专有选项**
- `-d 域名`（也写 `--domain`）　目标域；`--resolver 8.8.8.8`　指定 DNS 服务器（可带端口 `IP:53`）
- `--protocol udp|tcp`　解析协议；`--timeout 1s`　解析超时；`-c`　同时查 CNAME
- `--wildcard`　发现泛解析时仍继续；`--no-fqdn`　不加末尾点、用系统搜索域

**`vhost` 模式专有选项**
- `-u` 建议用 IP；`--append-domain/-ad`　把主域名拼到词表词后（否则词表里要写全限定域名）
- `--domain 域名`　从 IP 的 URL 里拼域名用；`--exclude-length` / `--exclude-status`　去掉噪声
- `--exclude-hostname-length`　按 Host 名长度动态校正排除长度；`--force`　预检失败也硬跑

**示例**（全部打本机靶）
- `gobuster dir -u http://127.0.0.1:8789 -w 词表`　★ 扫这个网站有哪些目录 / 文件（最常用；默认已吞 404）
- `gobuster dir -u http://127.0.0.1:8789 -w 词表 -x php,html,txt -q`　带常见扩展名、静默
- `gobuster dns -d 自有域名 -w 词表 -q`　子域枚举
- `gobuster vhost -u http://127.0.0.1:8789 -w 词表 --append-domain -q`　找同 IP / 同端口上的其它站点
- `gobuster fuzz -u "http://127.0.0.1:8789/FUZZ" -w 词表 -b 404 -q`　自由位置模糊测试

**备注**：★ 本机 gobuster **3.8.2**（`--version` 会打印 go / GOOS / CGO 等 build 信息）。★ **没有 `gobuster version` 这个子命令**（实测报 `No help topic for 'version'`）—— 看版本用 `gobuster --version` 或 `gobuster -v`。★ **默认只显示存在的**（`-b` 默认屏蔽 404），所以"输出很少"不代表没跑起来，跟 ffuf 默认"只认匹配码但也能 `-mc all` 全放出来"不一样，别搞混。★ 同样要吃 `-w`，**本机没现成词表** —— 自制小词表实测可跑：`gobuster dir -u http://127.0.0.1:8789 -w 词表 -q` → 打出 `index.html           (Status: 200) [Size: 24211]`。★ `dir` 线程**默认 10**（比 ffuf 的 40 保守）。★ `dns` 模式默认用系统 DNS —— 本机走内网 DoH，要和公网对比得 `--resolver 8.8.8.8`。

**和 ffuf 怎么分**：gobuster 模式化、开箱即用、默认吞噪声，适合**目录/子域/虚拟主机**这类标准枚举，一条命令就出干净结果；ffuf 的 `FUZZ` 能插到 URL / Header / Body 任意位置、过滤维度更多（大小/词数/行数/正则）且能自动校准，适合**自定义位置、爆参数值、通配符场景**。**先 gobuster 快速摸底，噪声大或要爆特殊位置时再上 ffuf。**

**参考**：gobuster 仓库 https://github.com/OJ/gobuster

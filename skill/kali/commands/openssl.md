# openssl · 抓证书 / 验 TLS

**用途**：看一个端口上的 TLS 证书是谁签的、什么时候过期、握手用什么算法；也做哈希、加解密、证书转换、生成密钥。

**用法**：openssl <子命令> [选项]　（`openssl help` 列标准命令；`openssl list` 列摘要/密码/公钥算法与 provider）

**常用子命令**
- `s_client`　当 TLS 客户端，打印对端证书链
- `x509`　看 / 转换证书
- `s_server`　起个临时 TLS 服务
- `req`　生成 CSR 或自签证书
- `genpkey` / `pkey`　生成密钥 / 处理密钥（3.x 推荐，替代旧的 `genrsa`/`rsa`）
- `dgst`　算哈希（`-sha256`）
- `enc`　对称加解密
- `verify`　验证证书链
- `rand -hex 16`　生成随机数
- `pkcs12`　PEM ↔ .pfx 互转

**常用选项**（都是"子命令 + 其关键选项"）
- `s_client -connect 主机:端口`　连目标；不给默认连 127.0.0.1:4433
- `-servername 主机`　★ 报 SNI，**不能省**；`-showcerts`　打印完整链；`-brief`　一屏摘要
- `-CAfile 文件` / `-CApath 目录`　指定信任库；`-starttls smtp|imap|pop3|ftp|postgres`　对非裸露 TLS 服务先做明文升级
- `-verify_return_error`　校验失败就当错退出；`-tls1_2` / `-tls1_3`　锁协议版本
- `x509 -in 证书 -noout`　只打印、不重复输出整张 PEM；配 `-dates`/`-subject`/`-issuer`/`-serial`/`-enddate`/`-text`
- `x509 -fingerprint -sha256`　看指纹（默认是 SHA1，**显式加 `-sha256`**）；`-pubkey`　导出公钥
- `req -new -x509 -key 私钥 -out 证书 -days 天数 -subj "/CN=名"`　自签证书
- `req ... -addext "subjectAltName=DNS:名,IP:127.0.0.1"`　加 SAN（现代浏览器只认 SAN，不看 CN）
- `genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out k.pem`　生成密钥
- `dgst -sha256 文件`　算文件哈希（`-c` 冒号分隔、`-r` coreutils 格式）
- `enc -aes-256-cbc -pbkdf2 -salt -in 明文 -out 密文`　加密；`-d` 解密、`-a`/`-base64` 出 base64
- `verify -CAfile ca.pem 证书.pem`　验链；`-untrusted 中间证.pem`、`-show_chain` 打链条
- `rand -hex 16`　出 16 字节随机数的 hex
- `pkcs12 -export -inkey k.pem -in c.pem -out c.p12`　打包成 .pfx；`-info` 看结构

**示例**
- `echo | openssl s_client -connect collaplex.me:443 -servername collaplex.me 2>/dev/null | openssl x509 -noout -dates -subject -issuer`　★ 只看主体/签发者/有效期（实测本机出 `subject=CN=collaplex.me`，`issuer=...Let's Encrypt...YE2`，到 2026-12-23）
- `openssl s_client -connect collaplex.me:443 -servername collaplex.me -brief </dev/null`　一屏看协议/套件/验证结果（实测 TLSv1.3、`Verification: OK`）
- `openssl s_client -connect 主机:443 -servername 主机 -showcerts </dev/null`　把完整证书链打出来
- `openssl req -x509 -new -key k.pem -days 30 -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" -out c.pem`　自签一张带 SAN 的证书
- `openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out k.pem`　生成 2048 位 RSA 私钥
- `openssl x509 -in c.pem -noout -fingerprint -sha256`　看证书 SHA256 指纹
- `openssl verify -CAfile c.pem c.pem`　拿证书自己当 CA 验自己（自签证书这样验；输出 `c.pem: OK`）
- `openssl enc -aes-256-cbc -pbkdf2 -salt -in f.txt -out f.enc -pass pass:test`（解密加 `-d`）　文件加解密往返
- `openssl dgst -sha256 文件`　算文件 SHA256

**备注**：
★ 本机 OpenSSL **3.5.5**（`openssl version -a`；OPENSSLDIR `/usr/lib/ssl`）。
★ **`-servername` 不能省** —— 现在都靠 SNI 分流，不带给到的可能是默认站点的证书，看着"证书不对"其实是你没报域名。
★ 打到**非 TLS 端口**会报 `packet length too long` / `record layer failure` —— 实测本机打到 8789（HTTP 面板）就是这个错，**别当成证书有问题**，它说明那个端口根本不是 HTTPS。
★ 交互模式要按 Ctrl-D 退出，脚本里固定写 `</dev/null`。
★ **子命令树**：openssl 是"一个母命令 + 一堆子命令"，`openssl help` 看标准命令、`openssl <子命令> -help` 看该子命令的全部选项。3.x 把大量算法收进 **provider**，`openssl list -providers` 看已载入的、`-digests`/`-ciphers`/`-public-key-algorithms` 看可用的；旧算法（MD4、RC4、部分 3DES 用法）默认被禁，要用得显式 `-provider legacy`。
★ **3.x 变化**：`openssl rsa` / `genrsa` / `dsa` / `gendsa` / `ec` 仍可用但已属"传统命令"，新写法是 `genpkey` + `pkey`。`enc` 默认用较弱的密钥派生，务必显式 `-pbkdf2`（配 `-iter`）；`enc` 的 `-k/-pass` 只是口令，别当强加密。
★ **x509 的"打印类"选项必须配 `-noout`**，否则会把整张证书 PEM 也一起打出来。`-dates`/`-subject`/`-issuer`/`-serial`/`-enddate`/`-fingerprint` 都是这种打印选项。
★ **`-fingerprint` 默认 SHA1**，抓指纹（比对/钉证书）一定加 `-sha256`；`x509 -pubkey` 导出的公钥再 `pkey -pubin` + `dgst` 可算 SPKI 指纹（证书钉扎常用）。
★ 打 **collaplex.me** 是老板自己的域名、可以打（Let's Encrypt 签的）；打别人的生产站要自觉、别反复握手当压力测试。
★ `verify` 默认走系统信任库；验自签证书就把证书自己当 `-CAfile`。看一条链是否完整用 `-show_chain`。
★ `s_client` 连不通别急着怀疑证书，先 `-connect` 到 IP、`openssl s_client -unix /path.sock` 或换 `-starttls` 试，分清是网络问题还是 TLS 问题。

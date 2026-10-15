# dig · DNS 查询

**用途**：查一个域名的 A / AAAA / MX / TXT / NS 记录、看解析走了哪台服务器 —— 域名侦察和"解析对不对"必用。也能发 DNSSEC、DoT/DoH 查询。

**用法**：dig [@DNS服务器] 域名 [记录类型] [选项]

**常用选项**
- `+short`　只出结果值（脚本里用）
- `+noall +answer`　只出 answer 段（带 TTL 和记录类型）
- `+trace`　从根开始逐级追委派（隐含 `+dnssec`，会忽略显示类选项）
- `@8.8.8.8`　指定用哪台 DNS 查（对比污染 / 多解析很有用）
- `-x IP`　反查 PTR
- `+tcp`（同 `+vc`）　强制走 TCP（绕过某些 UDP 拦截 / 大响应）
- `-t 类型`　指定记录类型，等价于直接写类型（`dig -t MX 域名`）
- `+dnssec`　请求 DNSSEC 记录，看 RRSIG 与 AD 位
- `+multiline`　把 SOA / DNSKEY / TXT 展开成多行，好读
- `+nssearch`　列出该域所有权威 NS 的 SOA（看谁在答）
- `+noedns`　关掉 EDNS0；`+bufsize=1232`　改 UDP 包大小（EDNS 太大会被丢时可调）
- `+ignore`　收到 TC（截断）也不自动回退 TCP
- `+subnet=地址`　发 EDNS Client Subnet（看不同地区解析）
- `+tls` / `+https`　DoT / DoH 查询；`+tls-hostname=名` 配 `+tls-ca` 校验证书
- `+ttlunits`　TTL 显示成人可读单位；`+yaml`　结果转 YAML
- `+time=秒` / `+tries=n`　超时 / 重试次数；`+norecurse`　只问不递归
- `+nocmd +nostats`　去掉命令回显和统计尾巴（喂脚本更干净）
- `-4` / `-6`　只用 IPv4 / IPv6 传输

**示例**
- `dig +short 域名`　拿到 IP（实测 `dig +short collaplex.me` → `8.136.202.225`）
- `dig +noall +answer 域名`　★ 带 TTL，能看出缓存还剩多久（实测 `collaplex.me. 85 IN A 8.136.202.225`）
- `dig MX 域名`　`dig TXT 域名`（SPF / DKIM 都在这）
- `dig NS 域名`　谁在管这个域（实测 `dig NS collaplex.me` → `dns15/dns16.hichina.com.`，阿里云在管）
- `dig @127.0.0.53 +short 域名`　问本机真实parser；再 `dig @8.8.8.8 +short 域名` 对比（结果不一致 = 可能被投毒）
- `dig -x 8.8.8.8`　反查这个 IP 属于谁（实测 → `dns.google.`）
- `dig +trace 域名`　从根一路追到权威，看委派链条正不正常
- `dig +dnssec 域名`　看有没有 RRSIG、AD 位是否置位（DNSSEC 有没有验通）

**备注**：
★ 本机 dig（BIND）**9.20.24**。
★ 本机 DNS 走的是**内网 DoH**，`dig` 容易拿到局域网地址或跟公网不一致 —— 判"解析对不对"要和 `@8.8.8.8` / `@223.5.5.5` 对着看。
★ 被墙的域名各条路都会被投毒，**结果不对不等于你查错了**。
★ `+short` 会把 TTL 藏掉，要看 TTL 用 `+noall +answer`。
★ **本机真实parser是 systemd-resolved 的 `127.0.0.53`**（`ss -tlnp` 能看到它听在 `127.0.0.53:53`）。不带 `@` 时 dig 读 `/etc/resolv.conf` 默认就走它；`dig ... | grep SERVER` 可确认走的是谁。**别打 `@127.0.0.1`** —— 本机 53 端口不由 dig 那台服务监听，实测直接 `connection refused`（要问本机解析就写 `@127.0.0.53`）。
★ `@` 后面要写 IP 或能解析出来的名字，且是 **UDP 优先**（除非 `+tcp`）；本机实测 `dig @127.0.0.53 -x 8.8.8.8 +short` 正常返回 `dns.google.`。
★ **`+trace` 与投毒判读**：`+trace` 从根服务器开始、自己逐级迭代，**跳过递归parser**，所以它看到的是"真实委派链"——如果正常递归查询结果和 `+trace` 的权威结果打架，多半是中间那条递归被投毒/劫持。`+trace` 输出很长，且会忽略 `+short` 之类显示选项。
★ **被投毒的典型特征**：TTL 异常小（0~60 秒，真记录一般几百到几万）、A 记录指向黑洞/无关 IP、不同公共 DNS 结果互相打架、`+dnssec` 后 RRSIG 缺失或 AD 位不再置位（DNSSEC 验不过）。
★ **EDNS 小坑**：`+noall +answer` 里的 TTL 是"这条缓存还能活多少秒"，不是记录原始 TTL；连查两次看它递减就能确认命中了缓存。有些网络会丢大包 UDP，响应被 TC 截断时 dig 默认自动改走 TCP 重问（想看原始截断就加 `+ignore`）。

# sqlmap · SQL 注入检测与利用

**用途**：自动化检测 URL / 表单 / 请求头参数有没有 SQL 注入，有的话接着提库名、表名、字段、数据，甚至进一步拿文件系统 / 命令执行。*只对自有或已授权目标跑 —— 它一发就是一串畸形请求，绝不能对着别人的站点用。*

**用法**：sqlmap -u "URL" [选项]　（`-r` 从抓包文件读、`--data` 测 POST、`-m` 跑批量）

**常用选项**
- 目标：`-u "URL"`　带参 URL；`--data "a=1&b=2"`　POST 体；`-r 请求.txt`　从抓好的原始请求文件读（**带 Cookie / 自定义头最省事**）；`-m 列表.txt`　批量目标；`-l burp.log`　从 Burp 日志解析
- 连接：`--cookie "K=V"`、`--random-agent`、`-A "UA"`、`-H "头: 值"`、`--headers`、`--referer`、`--proxy http://127.0.0.1:8080`、`--delay 1`、`--timeout 30`
- 指定注入点：`-p id`　只测某个参数；`--skip`　跳过参数；`--param-filter POST`　按位置筛；`--dbms mysql`　指定后端数据库（省时间）
- 检测深度：`--level 1~5`（默认 1，越高测越多请求头 / 越刁的位置）；`--risk 1~3`（默认 1，越高 payload 越"危险"、可能改数据）
- 注入技术：`--technique BEUSTQ`　★ 每个字母一种：**B**oolean 布尔盲注、**E**rror 报错、**U**nion 联合查询、**S**tacked 堆叠查询、**T**ime 时间盲注、**Q** 内联查询；不指定默认全试 `BEUSTQ`
- 枚举与提取：`--banner`／`--current-db`／`--current-user`／`--dbs`（列库）／`--tables`／`--columns`／`--dump`（提数据）／`--dump-all`；配 `-D 库 -T 表 -C 字段` 精确定位
- 提权 / 进阶（**高危，先在授权靶上练**）：`--sql-shell`、`--os-shell`、`--os-cmd`、`--file-read`／`--file-write`、`--passwords`、`--is-dba`
- 其他：`--batch`　★ **非交互必加**（全部问题用默认答案）；`--tamper=script`　绕 WAF 的篡改脚本；`--threads 4`；`--forms`　自动扒页表单测；`--crawl 2`　爬站；`--output-dir 目录`　自定义输出位置；`--random-agent`；`--fresh-queries`；`--flush-session`　清掉旧会话重来

**示例**（全部打本机靶）
- `sqlmap -u "http://127.0.0.1:端口/page?id=1" --batch`　最基础的一次
- `sqlmap -u "http://127.0.0.1:端口/page?id=1" --batch --dbs`　能注入就列库
- `sqlmap -r 请求.txt --batch --level=3 --risk=2`　拿抓包请求跑，覆盖 headers / Cookie
- `sqlmap -u "http://127.0.0.1:端口/page?id=1" --batch -p id --technique=BEU`　只测一个参数、只用三种技术（快）
- `sqlmap -u "http://127.0.0.1:端口/page?id=1" --batch --dbms=mysql --tables -D 库名`　指定后端库后直接列表
- `sqlmap -u "http://127.0.0.1:端口/page?id=1" --batch --tamper=space2comment --dbs`　带 WAF 时挂篡改脚本（`--list-tampers` 看全部）

**备注**：★ 本机 sqlmap **1.10.4**（Debian 打包版）。★ **每次启动都打一行 `your sqlmap version is outdated` 警告 —— 忽略它**，是打包版比上游 release 慢半步，不是你的问题。★ **非交互必须 `--batch`**，否则它会停下来等人答；实测加了 `--batch` 后那句 `do you want to test this URL? [Y/n/q]` 会自动答 `Y` 继续。★ ★ **目标返回 404 时它会直接 `[CRITICAL] page not found` 结束** —— 实测打本机 8789 面板加个不存在的 `?id=1` 就是这样（exit 仍为 0，别被"没报错"骗了）。**先自己 curl 一下确认 URL 通、参数真的被后端处理，再上 sqlmap**。★ 结果默认落在 `~/.local/share/sqlmap/output/`（里面按目标 IP 建子目录，另有 `results-*.csv` 汇总）。★ **纪律：先手工确认注入点再让工具上** —— 用 `'`／`and 1=1`／`and 1=2` 观察页面差异或报错，锁定大致可注入的参数，再 `-p` 指给它；上来就全量 `--level 5 --risk 3` 既慢又可能把自有库改坏、还可能被 WAF 拦掉留下痕迹。★ `--list-tampers`　打印全部篡改脚本（实测本机可列，如 `space2comment`、`charencode` 等）。★ `--wizard`　给新手用的问答向导。★ 注入测试会发出一大串畸形请求，**只对自有或已授权目标跑**。

**参考**：sqlmap 官网 https://sqlmap.org ；仓库 https://github.com/sqlmapproject/sqlmap ；用法 wiki https://github.com/sqlmapproject/sqlmap/wiki/Usage

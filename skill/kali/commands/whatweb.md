# whatweb · Web 指纹识别

**用途**：给一个 URL，拿回它的服务器软件、开发语言、框架、CMS、中间件、页面标题、HTTP 头线索 —— 判断"这个站是什么搭的"。靠 1800+ 个插件，每个插件认一种技术；激进度越高问得越细。

**用法**：`whatweb [选项] URL...`（可给多个 URL、主机名、IP、CIDR / `x.x.x-x` 段、或文件名）

**常用选项**
激进度（速度 / 隐蔽 vs 可靠性的取舍）：
- `-a 1` / `--aggression=1`　**Stealthy（默认）**：每个目标只发 **1 个** HTTP 请求，跟随重定向。扫公网站用这档
- `-a 3`　**Aggressive**：只在对上某个 level-1 插件后才追加请求（更细的指纹，如 WordPress 精确版本）
- `-a 4`　**Heavy**：对每个目标发**大量**请求，所有插件的激进测试全上 —— 最全也最响，**只对自有站点用**
- （注意档位是 1/3/4，没有 2）

插件：
- `-l` / `--list-plugins`　列出全部插件
- `-I [关键词]` / `--info-plugins`　列插件**详情**，可跟关键词筛（如 `-I nginx`）
- `--search-plugins 关键词`　按关键词搜插件
- `-p 列表` / `--plugins`　**只跑指定插件**，逗号分隔，元素可带 `+` / `-` 和目录 / 文件名，例：`-p title,md5`、`-p ./plugins-disabled,-md5`、`-p +`（= `-p +plugins-disabled`）
- `-g 串或/正则/` / `--grep`　只显示匹配的结果，例 `-g "hello"`、`-g "/he[l]*o/"`
- `--custom-plugin "定义"`　命令行临时定义插件（`:text=>'powered by abc'` 之类）
- `--dorks=插件`　列出该插件的 Google dork

HTTP / 身份：
- `-U "UA"` / `--user-agent`　改 User-Agent（默认 `WhatWeb/0.6.3`）
- `-H "头:值"` / `--header`　加 / 换 HTTP 头（空值可删掉某默认头）
- `--follow-redirect=WHEN`　never / http-only / meta-only / same-site / always（默认 always）
- `--max-redirects=N`　最多跟几个重定向（默认 10）
- `-u 用户:密码` / `--user`　HTTP Basic 认证
- `-c 键=值; ...` / `--cookie`　带 cookie；`--cookie-jar=FILE` 存取 cookie；`--no-cookies` 关自动 cookie
- `--proxy 主机[:端口]`　走代理

输出 / 日志：
- `-v` / `--verbose`　详细（列出每条匹配 + 插件说明；**两次更 debug**）
- `-q` / `--quiet`　不打 STDOUT 的一行简要
- `--color=never|always|auto` / `--colour`　颜色控制（**进日志 / 管道必加 never**）
- `--no-errors`　不打印错误
- `--log-brief=FILE`　一行简报；`--log-verbose=FILE`　详细
- `--log-json=FILE`　**JSON 结构化输出** ★ 接脚本首选
- 其它格式：`--log-xml` / `--log-magictree` / `--log-object` / `--log-mongo-*` / `--log-elastic-*`
- `-i 文件` / `--input-file`　从文件批量读目标（可 `-i /dev/stdin`）
- `--url-prefix` / `--url-suffix` / `--url-pattern`　给目标 URL 加前后缀 / 套模板

性能：
- `-t N` / `--max-threads`　并发线程（默认 25）
- `--open-timeout`（默认 15s）/ `--read-timeout`（默认 30s）
- `--wait=秒`　两次连接之间等待（单线程时有用）

**示例**
- `whatweb-fixed --color=never http://目标`　★ 最快的一条（默认 -a 1）
- `whatweb-fixed -a 3 -v http://目标`　更细的指纹 + 每条匹配说明
- `whatweb-fixed -i urls.txt --log-json=结果.json`　批量存 JSON
- `whatweb-fixed -p title,ip http://目标`　★ 只跑两个插件，输出极简
- `whatweb-fixed -U "Mozilla/5.0" http://目标`　伪装浏览器 UA
- `whatweb-fixed --no-errors --url-prefix https:// 192.168.0.0/24`　扫内网 https（**只在自有网段**）
- `whatweb-fixed -I nginx`　查 nginx 相关插件详情

**备注**
- ★ ★★ **本机 `/usr/bin/whatweb` 是坏的**：跑任何命令都报
  `cannot load such file -- /usr/bin/lib/messages (LoadError)`（实测 `/usr/bin/whatweb:257:in 'require_relative'` 直接崩，连 `--help` / `--version` 都进不去）。
  **根因**：apt 装的这份脚本还是上游原版 —— 第 **257** 行 `require_relative 'lib/messages'`、第 **628** 行 `require_relative 'lib/simple_cookie_jar'`；而 Debian 把 whatweb 的 ruby 库放在 `/usr/lib/ruby/vendor_ruby/`（`messages.rb`、`simple_cookie_jar.rb` 都在那），脚本却按自己所在目录 `/usr/bin/lib/...` 去找，于是 LoadError。正确写法应是 `require 'messages'` / `require 'simple_cookie_jar'`（走 ruby 的库搜索路径）。
- ★ **已修好的可用副本：`~/.local/bin/whatweb-fixed`**（同一份脚本，只把那两行 `require_relative 'lib/xxx'` 换成 `require 'xxx'`，其余原样）。实测 `~/.local/bin/whatweb-fixed --version` → `WhatWeb version 0.6.3`。**所有示例命令都用 `whatweb-fixed`**。
- ★ **要修 `/usr/bin` 那份得改系统文件（要 root，本机铁律不许 sudo，得人手动来）**。临时免 root 的造法（已生效，留档）：
  ```bash
  cp /usr/bin/whatweb ~/.local/bin/whatweb-fixed
  sed -i "s|require_relative 'lib/|require '|g" ~/.local/bin/whatweb-fixed
  chmod +x ~/.local/bin/whatweb-fixed
  ```
  （这条只改**你自己**的副本，不碰系统文件，符合无 sudo 约束。）
- ★ 本机环境：whatweb 包版本 **0.6.3-1**（dpkg），ruby **3.3.8**（脚本靠系统 ruby 跑）。上游最新已到 **0.6.4**（2026-04，性能大改）。
- ★ **本机可用靶标（实测）**：
  - `~/.local/bin/whatweb-fixed --color=never http://127.0.0.1:8789`
    → `http://127.0.0.1:8789 [200 OK] Country[RESERVED][ZZ], HTML5, HTTPServer[BaseHTTP/0.6 Python/3.14.4], IP[127.0.0.1], Python[3.14.4], Script, Title[Collaplex 音效]`
  - `~/.local/bin/whatweb-fixed --color=never http://127.0.0.1:8790`
    → `http://127.0.0.1:8790 [404 Not Found] Country[RESERVED][ZZ], HTTPServer[llama.cpp], IP[127.0.0.1], UncommonHeaders[access-control-allow-origin]`
  - 结论一眼看出：8789 是 Python(BaseHTTP) 搭的音效面板，8790 是 llama.cpp 的模型服务。
- ★ **怎么读聚合结果**：一行式 `http://主机 [HTTP状态] 插件1[值], 插件2[值], ...`。键名就是证据类型 —— `HTTPServer[...]` 服务端、`Python[3.14.4]` 语言版本、`Script` 有脚本、`Title[...]` 页面标题、`IP[...]` 解析 IP、`UncommonHeaders[...]` 异常响应头（常泄露后端）、`Country[...]` 归属。`-v` 会把每个插件的**命中证据逐条列出 + 插件说明**；要结构化接脚本就用 `--log-json`（实测输出形如 `[{"target":"http://...","http_status":200,"plugins":{"HTTPServer":{"string":["..."]}, ...}}]`）。
- ★ 本机 `-l` 列出的插件很多（1800+ 量级）；`-p` 挑插件能把输出压到极简（实测 `-p title,ip` 只剩 `IP[127.0.0.1], Title[Collaplex 音效]`）。
- ★ `-a 3` / `-a 4` 会发更多请求，**可能触发 WAF 告警** —— 只对自有站点用（本机靶标 127.0.0.1 随便扫；对外目标不动手）。
- 参考：WhatWeb 官方仓库与 README <https://github.com/urbanadventurer/WhatWeb>；wiki <https://github.com/urbanadventurer/WhatWeb/wiki/>。

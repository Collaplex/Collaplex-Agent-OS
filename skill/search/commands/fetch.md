# 取 · 真浏览器取一页（html + 截图 + 状态码 + 错误分类）

**用途**：把一个网址**真取回来**。用系统 Chrome 走 CDP —— 目的就是**防爬虫识别**：
有一批站按 UA / JS 挑战 / TLS 指纹挡直抓，直抓拿回的是空壳或挑战页。

**实测差距**（同一批站，HTTP 直抓 vs 真浏览器）：

| 站点 | HTTP 直抓 | 真浏览器 |
|---|---|---|
| 今日头条首页 | 200，**4KB** | 200，**584KB**，正文 1437 字 |
| 微博首页 | 200，8KB | 200，229KB，正文 1300 字 |
| 知乎首页 | 200，44KB | 200，172KB |
| 豆瓣首页 | 200，85KB | 200，91KB（服务端渲染，两边差不多） |
| 知乎某问题页 | **403 失败** | 403（这个真被挡，浏览器也不行） |

**用法**：`.venv/bin/python skill/search/main.py 取 "<url>" [--shot 路径] [--seconds N]`

**选项**
- `--shot 路径` 截图存哪（默认 `skill/search/cache/shots/<url摘要>.jpg`）
- `--seconds N` 导航完再等几秒（默认 2.5，JS 渲染慢的站可以加大）

**输出**（JSON）

| 字段 | 意思 |
|---|---|
| `ok` | 取到了且没毛病 |
| `status` | HTTP 状态码（拿不到就是 `null`） |
| `title` / `text_chars` | 页面标题 / 正文长度（字） |
| `html_path` / `html_bytes` | 落盘的 html 路径与字节（超 5MB 会截断，`html_truncated` 标记） |
| `shot_path` | 整页截图（1440 宽，按内容高度，最多 8000px） |
| `err_kind` / `err_msg` | 出错口径与原文（见下） |
| `ms` | 花了多久（毫秒，实测一页 3~4 秒） |

**错误四类**（`err_kind`）

| 情况 | `err_kind` | `err_msg` 长什么样 |
|---|---|---|
| 域名解析不了 | `站点不存在` | `net::ERR_NAME_NOT_RESOLVED` |
| 连上了不回话 | `响应超时` | `net::ERR_CONNECTION_TIMED_OUT` / 导航完没收到响应 |
| 证书有问题 | `HTTPS 错误` | `net::ERR_CERT_*` |
| 404 / 403 / 站点拒绝 | `具体报错` | `HTTP 404`、`net::ERR_CONNECTION_REFUSED` |
| 取到了但没正文 | `空页面` | `正文只有 98 字(没内容的页面只回截图)` |

**示例**
- `取 "https://www.toutiao.com/"`　200 / 584KB / 正文 1437 字
- `取 "https://www.python.org/this-does-not-exist-xyz"`　`具体报错` / `HTTP 404`
- `取 "https://this-domain-definitely-not-exist-12345.com/"`　`站点不存在`
- `取 "https://example.com/" --shot /tmp/a.jpg`

**备注**：①**取不到也要回话**：四种错各有各的 `err_kind`，照实报，不许猜内容。
②html 与截图都落在 `skill/search/cache/`（不进 git）；截图与热库 TTL 一起清（见架构 §2）。
③要干净正文就接着跑 `正文 <html_path>`。
④浏览器是**常驻**的，第一次用会冷启（2~4 秒），之后每页 3~4 秒。

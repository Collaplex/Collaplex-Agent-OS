# curl · 发 HTTP 请求 / 下载

**用途**：发 HTTP(S) 请求 —— 看状态码、抓页面/接口、下载文件、发 JSON。

**用法**：curl [选项]... URL

**常用选项**
- `-I`　只取响应头（看状态码，最快）
- `-s`　安静（不显示进度）
- `-f`　HTTP 4xx/5xx 就静默失败、退出码非 0
- `-o 文件`　存到文件（`-O` 用原文件名）
- `-L`　跟随 302
- `-X POST -d '...' -H 'Content-Type: application/json'`　发 JSON
- `--max-time 5`　超时上限
- `--noproxy '*'`　★ 绕过 http_proxy 环境变量

**示例**
- `curl -sI --max-time 5 https://collaplex.me`　活没活（看首行 HTTP/2 200）
- `curl -s --noproxy '*' http://127.0.0.1:8790/v1/models`　★ 本机端口
- `curl -sL -o 文件.tar.gz URL`　下载
- `curl -s -X POST -H 'Content-Type: application/json' -d '{"a":1}' http://127.0.0.1:8899/api`

**备注**：★ **本机设了 http_proxy=127.0.0.1:7897（Clash，常没在跑）** —— 访问 `127.0.0.1` 的本地服务必须 `--noproxy '*'`，否则拿到 502 空 body（反复踩过的坑）。★ 判活要看**状态码**：端口能连上不代表应用层活着。★ 下载大文件加 `-C -` 支持断点续传。

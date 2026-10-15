# env · 看环境变量 / 换环境跑命令

**用途**：打印当前环境变量；或者临时改掉环境变量后运行一条命令。

**用法**：env [选项]... [-] [名字=值]... [命令 [参数]...]

**常用选项**
- 不带参数　打印所有环境变量
- `-i`　清空环境再跑命令
- `-u 名字`　去掉某个变量
- `-C 目录`　先切到目录再跑
- `-0`　用 NUL 分隔输出

**示例**
- `env | sort | grep -i proxy`　看代理相关变量
- `env | grep -E 'LMSTUDIO|DEEPSEEK|XIAOMI'`　看模型服务的密钥变量在不在
- `env -i PATH=/usr/bin:/bin bash`　起一个干净环境的 shell
- `env FOO=1 python script.py`　只给这一条命令加变量

**备注**：★本机 `http_proxy=127.0.0.1:7897`（Clash，经常没在跑）：curl 打本地地址必须加 `--noproxy "*"`，否则会被代理拦成 502 空 body。看单个变量直接 `echo $名字` 更快。要持久化就写 `~/.bashrc`，图形会话相关的写 `~/.xsessionrc`（lightdm 只读这个）。

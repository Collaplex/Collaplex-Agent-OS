# 命令行跑一轮对话 · 不进网页

**用途**：在命令行里跑一轮对话（不开浏览器、不起网页）—— 问"怎么不开浏览器跑一轮 / 在命令行里跑一轮对话怎么弄"就是这条；也用来在没人盯着的时候自证"跑得通"。

**用法**
- `collaplex-agent chat`（= `./.venv/bin/python main.py`），一行一条消息，末行 `/exit` 退出
- 非交互验收（管道喂一句，EOF 干净退出，尾行 `>已退出`）：
  `printf '一个笼子里鸡和兔共 35 个头、94 只脚，鸡兔各几只？只给数字。\n我上一个问题问的是什么？\n/exit\n' | ./.venv/bin/python main.py > run.log 2>&1`
- 读日志前先清 ANSI：`sed -e 's/\x1b\[[0-9;]*m//g' run.log > run.clean.txt`
- 第二轮问"我上一个问题问的是什么"就是上下文判据：答"没有保留之前的交互记录"= 单轮

**备注**
- ★ 退出用 `timeout <秒> ./.venv/bin/python main.py` 时，掐不完的进程要**按 pid 收尾**再 `pgrep -af collaplex_agent/main.py` 复查，别留孤儿。
- ★ 长跑一律**重定向到文件**，别接 `| tail -N`：python 的 stdout 到管道是块缓冲，中途啥也看不到、超时被掐只剩尾巴。
- 一轮大概花在哪看产物时间戳：`state/activity.json` 的 `时间` = 提问时刻、`logs/exec/` 里那几个文件 mtime = 命令跑完时刻、`state/*.json` mtime = 收尾时刻。
- 界面文字改动、exec 真跑过没有，判据都是**真跑一遍看那一行**（exec 真跑过会打 `[exec agent] 跑：`），不是读代码。

# 起服务 · 总入口 collaplex-agent

**用途**：把这套系统（Collaplex Agent OS）跑起来 —— 问"这套系统怎么起 / 起服务 / 怎么启动"就是这条。只有一个入口 `collaplex-agent`（就是 `cli.py`；本机靠 `~/.local/bin/` 里的转发脚本，没装就写 `./.venv/bin/python cli.py …`，两个写法等价）。

**用法**
- `collaplex-agent web`　起网页版（默认 `http://127.0.0.1:8791`）。浏览器先落在**启动页**，上面两个按钮：
  「以本地模型启动」= 起 PG → 拉模型(8790+8199) → 检查单二次核对 → 自检 → 挂看门狗 + 起清洗 → 放开页面；
  「正常启动」= 不拉本地主模型、不挂看门狗（向量模型仍会拉起来，检索要用）。
- `collaplex-agent web --本地`　起 web 并自动走「以本地模型启动」（进度就显示在页面上，不是黑盒等）
- `collaplex-agent web --端口 9000 --不打开`　换端口 / 不自动开浏览器
- `collaplex-agent chat`　命令行对话
- `collaplex-agent 自检`　只跑自检（30 项，不拉起主程序）
- `collaplex-agent 模型 start|stop|status`　单独管本地模型服务

**备注**：PG / 模型 / web **都不是开机自启**，得手动起（这是老板定的：服务手动控制）。启动页那个「日志」框读的是 `logs/启动.log`。点过设置页「关闭」之后会落一个停机闸门 `state/停机`（清洗/灌语料下一轮收手）；走「以本地模型启动」会自动撤掉它，手动撤 = `rm state/停机`。

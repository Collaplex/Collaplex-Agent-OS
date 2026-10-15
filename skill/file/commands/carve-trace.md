# carve trace · 把报错定位到代码里的那个节点

**用途**：手里有一段 traceback（或"报错在哪一行"），想立刻知道**是哪一块代码**出的问题 —— 把报错里的文件/行号对到语法节点上，给出该节点的 ID 和源码。

**用法**：`carve -p <文件> trace '<traceback 文本>'`　或　`… | carve -p <文件> trace -`

**常用选项**
- 文本传 `-` 表示从管道读（推荐：报错带引号换行，直接管道最省事）

**示例**
- `carve -p app.py trace 'File "app.py", line 12, in add
    return a + b
TypeError'`
- `python app.py 2>&1 | carve -p app.py trace -`　真跑一遍把报错喂进去

**备注**：①它只做"行号 → 节点"的定位，**不负责解释报错原因**（那是你自己看代码的事）。②拿到节点 ID 后接着 `carve show <ID>` 看上下文。③报错来自别的文件（不在 `-p` 指的这个目标里）就对不上了 —— 换那个文件再定位。

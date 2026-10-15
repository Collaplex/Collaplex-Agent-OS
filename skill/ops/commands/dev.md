# 改代码的规矩 · 动之前先留还原点

**用途**：这套系统的骨架不大，但牵一发动全身的件（切片器 / 检索件 / 解析层 / 协议）改坏了没得 `git checkout`（有些件还没进 git）。按下面来。

**怎么做**
1. ★ 改之前先 `git commit`（提交信息写清"还原点"），验收报告里给出还原法 `git reset --hard <SHA>`
2. 没进 git 的件先 `cp` 一份到 `data/`（已在索引排除表里），报出还原命令
3. 改完跑：`uvx pyright`（strict，要求 **0 errors / 0 warnings / 0 informations**；口径在 `pyrightconfig.json`，新文件按目录自动纳入、新 skill 的 `scripts/` 要加进 `extraPaths`）+ 相关回归（`tests/`、各 skill 的 `tests/`）+ `./selfcheck.py --只查`
4. **改完要能一条命令退回**才算交付闭环：改文件/改数据那类，跑前 `md5sum`，回退后再 `md5sum` 与原件**逐字节一致**

**两条约定**
- **配置外置**：开关/阈值/价目/提示词一律放 `config/*.json`、`skill/<名>/resources/*.json`、`config/skills/*.md`，代码里不硬编码；提示词不写死在 `.py` 里
- **文件名英文、给人看的界面文字中文**（日志/报错/表格/TUI 全中文）；运行产物不许带汉字

**备注**
- ★ **老板亲手调的配置绝对不许擅改**：`.env`、`config/*.json` 里的开关与模型列表要动**先问**。
- 提交前扫一遍：`git diff --cached --name-only | grep -E 'logs/|\.env$'` 应为空、`git diff --cached | grep -cE 'sk-[A-Za-z0-9]{20,}'` 必须是 0。
- 改 `.env` 走不回显写法（别用会把 diff 回显进会话的工具），只打印键名与值长度。

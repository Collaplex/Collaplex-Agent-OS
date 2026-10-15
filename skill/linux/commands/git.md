# git · 版本控制

**用途**：看仓库状态、改动、历史，提交与回滚。

**用法**：git <子命令> [选项]

**常用子命令**
- `status`　★ 改了哪些文件、哪些已暂存
- `log --oneline -10`　最近十条提交
- `diff`（`--cached` 看已暂存）　改了哪几行
- `add -A` / `commit -m "说明"`　暂存 + 提交
- `show --stat HEAD`　这次提交动了哪些文件
- `checkout -- 文件`　撤销工作区改动（★ 会丢改动）
- `ls-files 路径`　这个文件被跟踪了吗

**示例**
- `git status --short`　紧凑状态（`M ` 已暂存 / ` M` 未暂存 / `??` 未跟踪）
- `git log --oneline -5`
- `git ls-files .env`　★ 查密钥文件有没有进仓库
- `git -c user.name=x -c user.email=a@b commit -m "…"`　仓库没配身份时临时给

**备注**：★ 动配置/密钥前先 `git ls-files 文件` 确认**有没有被跟踪**（本机踩过：`.env` 一度进过仓库）。★ `git reset --hard` 按索引删 tracked 文件、**`.gitignore` 不保护**它们 —— 动手前先备份工作区。★ 提交信息里别写密钥，提交后 `grep` 扫一遍。

# pip · 装 Python 包

**用途**：装/卸/看 Python 包。★ 本机要分清"系统 pip"和"项目 venv 里的 pip"。

**用法**：pip <子命令> [选项]

**常用子命令**
- `list`　装了哪些（`--outdated` 看可升级）
- `show 包名`　这个包的版本/位置/依赖
- `install 包名`　装（`-U` 升级）
- `uninstall 包名`　卸
- `download -d 目录 包名`　只下载不装（离线迁移用）

**示例**
- `./.venv/bin/pip list | grep -i requests`　★ 项目 venv 里的包
- `./.venv/bin/pip show openai`　版本与安装位置
- `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple 包名`　★ 走清华源（本机默认源慢）
- `python3 -m pip --version`　这个解释器配的 pip 是谁

**备注**：★ **`pip` 和 `.venv/bin/pip` 是两个环境**（本机裸 `pip` = 系统的 python3.14，项目里必须显式写 `.venv/bin/pip`）—— "import 报缺包"最常见的原因就是装到了另一个环境。★ 拿不准就按 `./.venv/bin/python -m pip install …` 走。★ 系统 Python 有 PEP 668 保护，直接装会被拒（要 venv 或 `--break-system-packages`，后者别用）。

# apt · 装包 / 查包

**用途**：Ubuntu 上的命令行包管理器 —— 装、删、升级、查询软件包。

**用法**：apt [选项] 命令

**常用命令**
- `update`　刷新软件源索引
- `install` / `remove 包名`　装 / 卸
- `search 关键字`　搜包
- `show 包名`　看包详情和依赖
- `list --installed`　已安装的包
- `policy 包名`　看它会从哪个源装、什么版本

**示例**
- `apt policy nginx`　这个包从哪个源来
- `apt list --installed 2>/dev/null | grep -i mesa`　装没装
- `sudo apt install -y 包名`　安装（脚本里加 `-y`）
- `apt-file search 某个.h`　找哪个包提供这个文件（要先装 apt-file）

**备注**：★本机 apt 3.2.0，走内网镜像。★踩过的坑：NVIDIA CUDA 源的上游索引里有 5 个缺 `Package:` 头的小节，会让 apt **拒绝读全部列表**（install / remove 全废），本机已装 `fix-nvidia-cuda-index` 钩子自动剔（`/etc/apt/apt.conf.d/99-nvidia-cuda-index-fix`）。装不动先看 `apt update` 的报错，别急着换源。

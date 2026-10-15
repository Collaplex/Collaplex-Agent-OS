# file · 认文件类型

**用途**：不看扩展名、按内容判断这是什么文件（文本/图片/可执行/归档/数据）。

**用法**：file [选项]... 文件...

**常用选项**
- `-b`　只输出类型，不打文件名
- `-i`　输出 MIME 类型（`text/plain` 这种）
- `--mime-encoding`　顺带报编码（认 GBK / UTF-8）
- `-z`　试着看压缩包**里面**
- `-L`　跟软链接

**示例**
- `file 未知文件`　这是什么
- `file -i *`　一目录的 MIME 类型
- `file --mime-encoding 乱码.txt`　是不是 GBK
- `head -c 400 xxx | file -b -`　认管道里前几百字节

**备注**：★ 扩展名骗人的场景全靠它（`.txt` 其实是 zip、`.mp4` 其实是 html 页）。★ 判"是不是文本"用 `file -i 文件 | grep text`；判可执行文件看输出里有没有 "ELF"。★ 本机踩过的坑：GBK 编码的文件名/内容会让 GNOME 卡顿（GLib UTF-8 校验自旋）—— 用 `--mime-encoding` 能快速定位。

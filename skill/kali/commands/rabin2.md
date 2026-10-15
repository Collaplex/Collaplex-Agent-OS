# rabin2 · 二进制信息速读（radare2 套件）

**用途**：不开图形界面、不看汇编，先把一个可执行文件 / 库的"身份证"读出来 —— 架构、位数、类型、有没有栈保护、依赖哪些库、导入了谁、导出了什么、里面有什么字符串。它是 radare2 套件里的**只读信息提取器**：只列信息，不改文件、不反汇编、不跑代码。

**用法**：`rabin2 [选项] 文件`（文件可为 ELF / PE / Mach-O / dex / Java class / zip 容器等，支持几十种格式。加 `-j` 任何输出转 JSON）

**常用选项**

信息类（先跑这几条看"好不好搞"）：
- `-I`　文件头信息（架构 / 位数 / 类型 / 保护：canary、nx、pic、relro、stripped）★ 入口第一条
- `-H`　**原始**头部字段（按偏移逐字段列出：Magic、Type、Machine、EntryPoint、PhOff…）
- `-e`　程序入口点（entrypoint）；`-ee`　构造函数 / 析构函数入口点
- `-M`　main 符号地址（符号被 strip 过就报 `Missing bin header main`）
- `-g`　= `-SMZIHVResizcld -SS -SSS -ee` 一把全列（信息最多，输出也最长）
- `-V`　二进制自带的版本信息块

符号 / 依赖：
- `-i`　导入表（它调用了谁的哪些函数 —— 一眼看出有没有用 openssl、pthread、libsystemd）
- `-E`　导出表（它对外提供了什么；`-E` 在 `/bin/ls` 上为空，因为它是可执行文件不是库）
- `-s`　符号表；`-l`　链接的库（DT_NEEDED）；`-R`　重定位表
- `-q`　精简输出、`-qq`　更少（连地址 / 大小都不打）

结构 / 字符串：
- `-S`　段表（section）；`-SS`　segment；`-SSS`　section→segment 映射
- `-z`　字符串（从 data 段提取，比 `strings` 更懂格式，带地址和所属段）
- `-zz`　从原始 bin 提字符串（换个来源，抓 `-z` 漏掉的）
- `-zzz`　把原始字符串**直接 dump 到 stdout**（大文件只求内容时用）
- `-N min:max`　限定字符串长度区间（配合 `-z` / `-zz` 去掉噪音）
- `-x`　抽取文件里内嵌的其它二进制（`-O` 是写 / 抽取操作，`-O help` 看用法）

格式 / 编码：
- `-j`　**所有**输出转 JSON（接脚本首选）
- `-a arch` / `-b bits`　强制指定架构 / 位数（自动判错时覆盖）
- `-F format`　强制用某个 bin 插件解析（跳过头部校验）
- `-D lang name`　符号名 demangle（cxx / swift / java…；`-D all` 全开）
- `-K algo`　算校验和（md5 / sha1…；`-t` 打印文件哈希，无则尝试 `-j -t`）
- `-c` / `-cc`　列出文件里定义的**类**（Java/相关格式，头格式 `-cc`）
- `-d`　显示 **debug / DWARF** 信息；`-A`　列出**子二进制**（fatbin / 复合格式里的每一段）

**示例**
- `rabin2 -I 文件`　★ 先用这条判类型和保护（canary/nx/pic/stripped）
- `rabin2 -H 文件`　看原始头字段（比 `-I` 更底层）
- `rabin2 -i 文件 | head`　它依赖哪些函数（能看出用了 openssl、pthread 之类）
- `rabin2 -l 文件`　依赖哪些 .so
- `rabin2 -S 文件`　段表；`rabin2 -SS 文件`　内存 segment 布局
- `rabin2 -z 文件 | grep -i 关键字`　里面有没有可读线索（URL、报错文案）
- `rabin2 -zzz 文件 | grep -i flag`　大文件直接 dump 原始串再筛
- `rabin2 -j -I 文件 | jq`　结构化取字段接脚本
- `rabin2 -g 文件`　懒得挑就一把全列
- `r2 -q -c 'aaa; afl~main' 文件`　一行命令版：直接找 main 函数
- `r2 文件`　进交互后敲 `aaa` 再 `afl`　列出全部函数

**备注**
- ★ 本机 **radare2 / rabin2 6.0.7**（`git.6.0.7 2025-11-27`），rabin2 随套件一起装，`/usr/bin/rabin2`；man 页在 `/usr/share/man/man1/rabin2.1.gz`。
- ★ `-I` 输出里 **`canary` 那一行就是有没有栈保护**（true = 有），`nx` / `pic` / `stripped` / `relro` 同理 —— 判"好不好搞"先看这几个。实测 `/bin/ls`：`canary true / nx true / pic true / relro full / stripped false`。
- ★ **rabin2 不做反汇编、不产伪代码**——这是它和 r2 的分工。别把 `-d`（=debug/DWARF）、`-c`（=列类）、`-A`（=列子二进制）当成"导出反汇编"。要看汇编 / 伪代码得进 r2 交互：
  - 反汇编：r2 里 `pd`（当前块）/ `pdf @ sym.main`（单函数）；或 `r2 -q -c 'aaa; s main; pdf' 文件`
  - 伪 C：r2 内置 `pdc`（简单反编译器）；更贴近人话的是 Ghidra（`/opt/ghidra_12.1.3_PUBLIC`），r2 可用 `pdg` 插件调 Ghidra 反编译
- ★ **本机 rabin2 没有 entropy（熵）选项**——查过 `-h` 和 man 都没有。要看熵 / 加壳特征得用 r2 交互的 `p=` 命令，实测 `/bin/ls`：`r2 -q -e scr.color=0 -c 's 0; b 256; p=' /bin/ls` 打出按块熵值柱状图（高熵块 ≈ 压缩 / 加密 / 加壳）。
- ★ `aaa`（全量分析）在几 MB 的文件上要跑几十秒，**大文件先用 `aa` 或只看 `afl`**。
- ★ 实测样本：`/bin/ls`（ELF64）、本机 blender 的 `lib*.so`（ELF 动态库）。这些是**本机自己的文件**。
- ★ 和 `jadx`（Java / APK）、Ghidra（`/opt/ghidra_12.1.3_PUBLIC`，伪 C 更像人话）配着用：rabin2 负责"读完信息"，反编译交给 jadx / Ghidra / r2 的 `pd*`。
- 参考：radare2 官方书 rabin2 章 <https://book.rada.re/tools/rabin2/intro.html>；rabin2 手册 man rabin2。

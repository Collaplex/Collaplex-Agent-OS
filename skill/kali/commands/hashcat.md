# hashcat · 离线哈希破解

**用途**：拿到哈希（文件里、数据库里、抓包里的）之后**离线**还原明文 —— 字典、掩码、规则组合。**不产生任何网络流量**，是最"干净"的一类，也是最吃 GPU 的一类。

**用法**：`hashcat [选项] 哈希文件 [词表 | 掩码]`

**哈希类型 `-m`（先定对模式号，选错必失败）**
- `-m 0` MD5 ／ `-m 1000` NTLM ／ `-m 1800` sha512crypt（Linux `/etc/shadow` 里 `$6$`）
- `-m 22000` WPA-PBKDF2（aircrack-ng 导出的 `.hccapx`）／ 老格式 `-m 2500`（`.hccap`）
- 还有 `-m 500`(md5crypt `$1$`)、`-m 3200`(bcrypt) 等上千种 —— 完整列表见 `hashcat --help` 里的"Hash Modes"段或 <https://hashcat.net/wiki/doku.php?id=example_hashes>。
- 不确定模式号？用 `--identify 哈希文件` 让它按格式猜（不用 GPU，见下）。
- ★ 模式选错会直接报 `No hashes loaded` / 提示 token length exception，**别以为是文件坏了**。

**攻击方式 `-a`（本机 `hashcat --help` 实测的合法值）**
- `-a 0` Straight 　字典（最常用）
- `-a 1` Combination 　两张词表两两拼接
- `-a 3` Brute-force 　掩码暴力枚举
- `-a 6` Hybrid Wordlist + Mask 　`词表 + 掩码`（如 `apples?d?d`）
- `-a 7` Hybrid Mask + Wordlist 　`掩码 + 词表`（如 `?d?dapples`）
- `-a 9` Association 　关联攻击

**掩码字符集（`-a 3/6/7` 用，本机 help 实测）**
- `?l`=小写a-z　`?u`=大写A-Z　`?d`=数字0-9　`?h`=小写十六进制　`?H`=大写十六进制　`?s`=符号　`?a`=`?l?u?d?s`(全部)　`?b`=0x00–0xff
- 自定义集合：`-1`~`-8` 定义 `?1`…（如 `-1 ?l?d` 然后掩码里写 `?1`）
- 增量：`-i` 自动从短到长逐位加（`--increment-min`/`--increment-max` 限范围），省得手动写好几条

**常用选项**
- `-r 规则文件`　套规则做变形，规则在 `/usr/share/hashcat/rules/`（如 `best64.rule`、`rockyou-30000.rule`）；单条规则用 `-j`(左词表) / `-k`(右词表)
- `-O`　启用**优化内核**，更快，但**限制最大密码长度**（具体上限运行时它会打印）；不加 `-O` 是纯内核，能跑更长的口令但慢很多
- `-w 1..4`　负载档位：`1`低(桌面影响最小) / `2`默认 / `3`高 / `4`最高(机器会卡到不能动)。**笔记本用 1~2**
- `-o 文件`　结果写文件（`--outfile`）；`--outfile-format` 定制字段
- `--show`　把哈希文件和 potfile 比对，**打印已破出的明文**（不用 GPU）
- `--potfile-path 文件`　指定 potfile 位置（默认在 `~/.hashcat/`）；`--potfile-disable` 不记录
- `--remove`　破出的哈希行从输入文件里删掉
- `--stdout`　不破解，只把候选口令打印出来（**验证掩码/词表/规则生成啥样，不用 GPU**）
- `-I` / `-II`　列可用的计算设备/后端信息（见备注）
- `-i` / `--increment`、`--increment-min/max`　掩码增量
- `--identify 哈希文件`　按格式识别可能的哈希类型（不用 GPU）
- `--force`　无视警告强行跑（比如驱动/显存告警）
- `--hwmon-temp-abort 90`　温度到 90℃ 自动停（本机 help 实测 90 是默认触发点）；`--hwmon-disable` 关掉温度/风扇读取
- `--session 名字` / `--restore`　会话存档 / 断点续跑（长跑必备）
- `-s 跳过数` / `-l 限长`　从第 N 个候选开始 / 只跑 N 个（分片并行用）

**示例**
```
# 1) 先看设备（★ 每次开跑前都值得看一眼）
hashcat -I

# 2) MD5 跑字典（词表自备；本机没有现成的，见备注）
hashcat -m 0 -a 0 哈希.txt 词表.txt

# 3) NTLM 加规则、并存结果
hashcat -m 1000 -a 0 ntlm.txt 词表.txt -r /usr/share/hashcat/rules/best64.rule -o 命中.txt

# 4) 掩码：6 位小写+数字
hashcat -m 0 -a 3 哈希.txt ?l?d?l?d?l?d
# 增量版：从 1 位试到 8 位
hashcat -m 0 -a 3 -i --increment-min 1 --increment-max 8 哈希.txt ?a

# 5) 只看已破出的（不用 GPU）
hashcat -m 0 --show 哈希.txt

# 6) 不用 GPU 就能验证：识别类型 / 看候选长啥样
hashcat --identify 哈希.txt
hashcat -a 3 --stdout ?d?d | head
```

**备注**
- ★ 本机 hashcat **v7.1.2**，`hashcat -I` 实测能看到 **CUDA 13.4（NVIDIA GeForce RTX 5060 Laptop GPU，26 个 SM，8GB 显存）**。
- ★ 会打一行 `nvmlDeviceGetFanSpeed(): Not Supported` —— 笔记本没这个 nvml 接口，**不是故障**。
- ★ ★ **踩过的真坑（本机实测）**：这台机器上 `llama-server`（本地大模型）常驻占着 **约 7.2GB** 显存，`hashcat -I` 里会显示显存几乎被占满；此时**任何真实破解都起不来**，直接报
  `* Device #1: Not enough allocatable device memory or free host memory for mapping.`
  这不是哈希文件的问题 —— **开跑前先 `nvidia-smi` 看有没有别人占着显存**（老板会打游戏 / 挂着 llama-server），先把占显存的进程停了再跑。
- ★ **词表要自备**（本机 `/usr/share/wordlists` 不存在），规则文件包里有。
- ★ 哈希类型选错（`-m`）会直接报 `No hashes loaded`，别以为是文件坏了。
- ★ 跑起来是 GPU 满载，`-w 3/4` 会让桌面卡死；笔记本从 `-w 1`/`-w 2` 起。
- ★ 来源：`hashcat --help` / `hashcat -I`（本机实测）、官方 wiki <https://hashcat.net/wiki/doku.php?id=hashcat>、示例哈希 <https://hashcat.net/wiki/doku.php?id=example_hashes>、FAQ <https://hashcat.net/faq/>、仓库 <https://github.com/hashcat/hashcat>。

# aircrack-ng · 无线口令恢复

**用途**：从**自己抓到的** WPA/WPA2 握手包或 PMKID 里**离线**还原 Wi-Fi 口令。四点注意：这是一整套工具的四条命（见下"四件套"），`aircrack-ng` 只负责最后那步离线跑词表，前面的监听/抓包/踢客户端得靠另外三条。

**用法**：`aircrack-ng [选项] 抓包.cap`（抓包文件可给多个）

**四件套分工（这才是完整流程）**
- `airmon-ng`　把网卡切进/退出**监听模式**（monitor mode）。`airmon-ng start wlan0` 起、`airmon-ng stop wlan0mon` 停。**要 root**（本机实测直接跑会回 `Run it as root`）。
- `airodump-ng`　**抓包**，把空口上的报文写成 `.cap`。关键要**抓到 WPA 四次握手** —— 屏幕上对应那张 AP 的"WPA handshake"列出现 `AA:BB:CC:DD:EE:FF` 字样才算拿到了。
- `aireplay-ng`　**去认证 / 注入**，最常用 `-0`（deauth）把已连客户端踢下线，逼它重连从而抓握手。
- `aircrack-ng`　**离线**拿抓包丢词表跑口令。

**常用选项**（本机 `aircrack-ng --help` 实测）
- `-w 词表`　用口令表试
- `-b AA:BB:CC:DD:EE:FF`　指定 AP 的 BSSID（抓包里有多个网络时必给）
- `-e SSID`　按网络名选目标
- `-a 2`　强制 WPA-PSK 模式（`-a 1` 是 WEP）
- `-l 文件`　找到的口令写到文件（会覆盖原文件）
- `-j 文件`　导出 **HCCAPX**（hashcat v3.6+ 格式 → 丢给 `hashcat -m 22000`，GPU 更快）
- `-J 文件`　导出旧 **HCCAP**（→ `hashcat -m 2500`，老格式，一般用 `-j` 就行）
- `-I 字符串`　直接吃一个 PMKID 字符串（对应 hashcat 的 `-m 16800`）
- `-E 文件`　导出 EWSA 工程文件；`-S`/`-Z`　WPA 跑速测试
- `-p nbcpu`　用几个 CPU；`-q` 安静模式

**airodump-ng 关键选项**（抓包时）
- `--write 前缀`　把抓到的报文写盘（生成 `前缀-01.cap` / `.csv` 等）
- `-c 频道`　锁定某个信道（如 `-c 6`）；`--bssid`/`--essid`　过滤只盯某个 AP
- `-w`/`--output-format`　输出格式（pcap/csv/kismet/netxml…）
- 默认在 2.4GHz 信道间跳；5GHz/6GHz 要手动指定信道。

**aireplay-ng 关键选项**（踢客户端逼重连）
- `-0 次数 -a BSSID 接口`　deauth 攻击（如 `-0 5 -a AA:BB:.. wlan0mon`，发 5 次）
- `-e SSID`　指定目标 SSID；`-c 客户端MAC`　只踢某个客户端（更温柔）
- 还有 fakeauth（`-1`）、arp-replay（`-3`）等，多为 WEP 场景。

**示例**（全程针对**自己的** AP）
```
# 1) 切监听模式（要 root）
sudo airmon-ng start wlan0          # 之后网卡一般变成 wlan0mon

# 2) 抓包：锁定自己 AP 的信道，写盘，盯着 handshake 字样
sudo airodump-ng -c 6 --bssid AA:BB:CC:DD:EE:FF -w 抓包 wlan0mon

# 3) 另开一个终端，踢一下自己的客户端逼它重连，好抓握手
sudo aireplay-ng -0 5 -a AA:BB:CC:DD:EE:FF wlan0mon   # 看到 "WPA handshake: ..." 就成了

# 4) 离线跑词表（词表自备；本机没有，见备注）
aircrack-ng -w 词表.txt -b AA:BB:CC:DD:EE:FF 抓包-01.cap

# 5a) 导给 hashcat 跑（GPU 更快）：-j 出 hccapx
aircrack-ng -j 导出名 抓包-01.cap
hashcat -m 22000 导出名.hccapx 词表.txt

# 5b) 抓包完退出监听模式
sudo airmon-ng stop wlan0mon
```

**备注**
- ★ 本机 **Aircrack-ng 1.7**；`airmon-ng` 实测直接跑会回 `Run it as root`（切监听模式需要 root 权限）。
- ★ **抓包前要把网卡切成监听模式**（`airmon-ng start`），而本机无线是 **MT7922 + NetworkManager 在管** —— 切监听要先把 NM 停下来，**而且会短暂断网**，别在正常上网时做（本机还有个别名 `wifi-health` 在盯链路）。
- ★ **目标是自己的 AP**：对不属于你的 SSID 做去认证 / 抓握手是**实打实的攻击行为**（会把别人的客户端踢下线）。
- ★ **抓到的不一定是握手包**：只有 `airodump-ng` 出现 "WPA handshake: XX:XX:.." 字样才算拿到了可用握手，否则空中打了一堆包也是废的（这也是很多人"抓到 cap 却跑不出"的原因）。
- ★ **字典攻击的现实前提**：WPA 的口令空间很大，离线跑**只能命中词表/规则能覆盖到的弱口令**；除非口令本身很弱或恰好在词表里，否则跑不动。本机没有词表。
- ★ **PMKID**：某些 AP 支持直接抓 PMKID（不用等握手、也不用踢客户端），更快更隐蔽。
- ★ **本机验不了的部分**：切监听模式、抓握手、去认证都需要 root 权限 + 网卡支持监听/注入（MT7922 驱动支持情况、以及会不会断网，都**得人手动来**试）。上面命令是照本机 `--help` 与官方文档整理的，未在本机实跑。
- ★ 来源：`aircrack-ng --help` / `airmon-ng --help` / `airodump-ng --help` / `aireplay-ng --help`（本机实测）、官方站 <https://www.aircrack-ng.org/>、wiki <https://www.aircrack-ng.org/doku.php>、仓库 <https://github.com/aircrack-ng/aircrack-ng>。

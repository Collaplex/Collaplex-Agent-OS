# systemd-analyze · 看开机耗时

**用途**：开机花了多久、慢在哪一步、哪个服务拖后腿。

**用法**：systemd-analyze [子命令]

**常用子命令**
- 无参数　总耗时（固件/引导/内核/用户空间分开列）
- `blame`　★ 每个服务耗时排行（谁最慢）
- `critical-chain`　关键路径（谁挡着谁）
- `verify 单元名`　检查单元文件有没有写错
- `security`　安全体检（要 root）

**示例**
- `systemd-analyze`　开机总时间
- `systemd-analyze blame | head -15`　★ 最慢的十五个服务
- `systemd-analyze critical-chain | head -20`　关键链
- `systemd-analyze verify /etc/systemd/system/xxx.service`　改完服务文件先验

**备注**：★ 本机实测（2026-10-06）：开机 **26.1s** = 固件 9.8s + 引导 5.6s + 内核 0.6s + initrd 2.3s + 用户空间 7.7s。★ `blame` 里时间长**不等于**拖慢开机（很多服务是并行跑的）—— 要看"到底卡在哪"用 `critical-chain`。★ 改完 unit 文件用 `verify` 先过一遍，比 `systemctl start` 失败再翻日志省事。

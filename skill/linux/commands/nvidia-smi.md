# nvidia-smi · 看显卡状态

**用途**：NVIDIA 显卡状态 —— 显存用量、温度、占用率、哪些进程占着显存。

**用法**：nvidia-smi [选项]

**常用选项**
- `--query-gpu=字段 --format=csv,noheader`　只取指定字段（name,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu）
- `--query-compute-apps=pid,used_memory --format=csv,noheader`　谁在占显存（给 pid 就知道是哪个进程）
- `-l 秒`　每 N 秒刷一次

**示例**
- `nvidia-smi --query-gpu=name,memory.used,memory.total,temperature.gpu,utilization.gpu --format=csv,noheader`　一行看全
- `nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader`　谁占着显存
- `nvidia-smi`　原样打整张表（进程表在最下面）

**备注**：本机是 **RTX 5060 Laptop 8GB**（实测 8151 MiB）。★ 显存是共享的：本地模型常驻占 4GB+，老板可能同时在玩游戏（占 4~5GB）—— 跑 GPU 活之前**先查这两条**，不够就排队等，别抢。★ 卡被电源管理关掉时 nvidia-smi 会报错，那属硬件层问题（另有恢复流程）。

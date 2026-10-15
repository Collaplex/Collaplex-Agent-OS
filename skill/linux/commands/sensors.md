# sensors · 看温度 / 风扇

**用途**：读温度传感器 —— CPU、显卡、硬盘、内存、风扇。

**用法**：sensors [选项]

**常用选项**
- `-A`　不显示芯片的适配器名（输出干净）
- `-f`　华氏度
- `-j`　JSON 输出
- `-u`　原始值

**示例**
- `sensors | grep -A2 k10temp`　CPU 温度（Tctl / Tccd1）
- `sensors | grep -E "edge|Composite|temp1"`　显卡/硬盘/内存各一行
- `watch -n2 sensors`　盯着看变化

**备注**：本机实测（2026-10-06）：CPU 在 `k10temp` 段 **Tctl 75°C**（就是常看的那条），核显 `amdgpu edge 71°C / PPT 57W`，硬盘 `nvme Composite 51°C`，内存 SPD `56°C`（high=55 会报 ALARM，正常），风扇在 `asus_custom_fan_curve` 段。★ **CPU 连轴 95°C 是要点名的** —— 90°C 上下就该停任务让机器歇。★ 独显温度看 `nvidia-smi` 更准。

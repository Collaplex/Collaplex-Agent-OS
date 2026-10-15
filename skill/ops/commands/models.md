# 本地模型服务 · 主模型 8790 与向量 8199

**用途**：本地那套 llama.cpp 的两头 —— 主模型 `:8790`（qwen3-vl-8b，带视觉塔 mmproj，能看图）+ 向量 `:8199`（qwen3-embedding-0.6b，检索/嵌入用）。判活要**真答话**，端口在听不算活。

**用法**
- `./start_models.sh start | stop | status | log`（就是项目根那个脚本；`collaplex-agent 模型 <动作>` 转发给它）
- 判活：`curl --noproxy '*' -s http://127.0.0.1:8790/v1/models`，向量同样打 8199
- 看显存与占用：`nvidia-smi`；日志在 `logs/` 下

**备注**
- 权重住 `~/models/<发布者>/<模型>/`（换机器用 `.env` 的 `COLLAPLEX_MODELS` 指别处）；llama.cpp 本体在项目里 `vendor/llama.cpp/build/bin/`（RUNPATH 已改成 `$ORIGIN`，搬目录/换机器照跑）。
- ★ `stop` **不一定停干净**：停完必查 `pgrep -af llama-server` + `ss -ltnp | grep -E ':(8790|8199)'`；有落单的**先读 `/proc/<pid>/cmdline` 确认是本项目那份**（别误杀老板自己的东西）再按 pid 杀，然后 `start` 复核。
- ★ 两份权重会抢同一块 8G 卡（新的加载失败，看着像模型坏了/权重不对）—— 这不是模型故障，别往那边查。主模型 `-c 32768` 与嵌入服务也抢显存：抬窗口时给嵌入服务 `CUDA_VISIBLE_DEVICES=`，主模型约吃 7320/8151 MiB。

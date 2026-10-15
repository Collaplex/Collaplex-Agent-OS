# systemctl · 管服务

**用途**：查看和控制 systemd 服务（单元）的状态、启停、开机自启。

**用法**：systemctl [选项] 命令 [单元...]

**常用命令**
- `status 单元`　看状态和最近日志
- `start` / `stop` / `restart 单元`　启 / 停 / 重启
- `is-active` / `is-enabled 单元`　在跑吗 / 会开机自启吗
- `list-units --failed`　哪些单元挂了
- `daemon-reload`　改完 unit 文件后必须重载
- `--user`　管用户级服务（图形会话里那些）

**示例**
- `systemctl --user status collaplex-audio-panel.service`　音效面板状态
- `systemctl is-active collaplex-audio-panel.service`　一句话问在不在跑
- `systemctl --failed`　全系统挂了哪些
- `systemctl --user list-units 'hermes*'`　Hermes 相关单元

**备注**：★本机的偏好是**不要自启、不要自动重启**（`enable` 和 `Restart=always` 都别乱开 ——"一搞就炸"，跑稳的配置不要动）。改完 unit 文件必须 `daemon-reload` 才生效。日志接着用 `journalctl` 看。

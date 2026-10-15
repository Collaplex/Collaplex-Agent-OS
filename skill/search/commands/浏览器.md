# 浏览器 · 管常驻浏览器（start / stop / status）

**用途**：看门狗与常驻进程的开关。**平时不用手动叫** —— `取` / `搜` 会自己把浏览器拉起来。

**用法**：`.venv/bin/python skill/search/main.py 浏览器 <start|stop|status>`

**三个动作**
- `start` 起来（已经在跑就续命）；顺带把看门狗也拉起来
- `stop` 杀看门狗 + 杀 chrome + 清状态（**顺手把浏览数据 profile 也清了**）
- `status` 看状态：`alive` / `pid` / `watchdog_pid` / `idle_for`（闲了多久）/ `shots`（截图张数）

**示例**
- `浏览器 status` → `alive: true, pid: 65314, watchdog_pid: 65480, idle_limit: 300, idle_for: 12.4`
- `浏览器 stop` → `{ok: true, note: "已停", watchdog_pid: 65480}`

**备注**
①**常驻**是为了省启动：冷启 2~4 秒、几百 MB 内存，每次取页都重启太亏。
②**延时看门狗**：闲置超过 `idle_seconds`（默认 300 秒，配置 `resources/browser.json`）就杀掉，
下次要用再拉起 —— 常驻但不养老。到点会写日志 `闲置 Ns >= 300s, 杀掉`。
③**为什么 stop 要清 profile**：连打一阵之后浏览数据养脏，bing 会给**泛结果**
（实测同一查询连打 20 多次后，对题率从 7/10 掉到 0/10；换新 profile 立刻回到 7/10）。
④看门狗与 chrome 一起收：只删 pid 文件不杀进程会留孤儿看门狗，下次 start 又起一个。
⑤端口默认 9334（`resources/browser.json`），**不是** Hermes 自己那个 9333 —— 两边互不打扰。
⑥日志在 `skill/search/logs/`：`browser.log`（事件）/ `watchdog.out` / `chrome.out`（chrome 自己的输出）。

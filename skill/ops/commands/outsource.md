# 外援与交叉验证 · 摇人花钱的活儿

**用途**：本地这支小模型拿不准（写不出成段代码 / 推不动多步推理 / 卡住绕圈）时，把一件明确的活交给云端强模型；还不放心就多家并排交叉验证。**默认都关着，会花钱。**

**用法**
- 外援（一级）：`./.venv/bin/python skill/outsource/main.py status`　看开关 / 今天花了几毛 / 凭据在不在
  `… skill/outsource/main.py ask "写个把 GBK 转 UTF-8 的脚本"`　干一件活（产出落盘 + 记账）
- 交叉验证（二级，只在外援不行之后）：`… skill/mtp/main.py status` / `… ask "这段代码为什么死锁？<贴代码>"`
- 外援自动触发（程序判摇不摇，默认关）：`./.venv/bin/python outsource_hook.py "写个判断回文数的函数" --秒 0`（只看判据，不花钱）

**备注**
- 开关/价目/预算/记账全在 `skill/outsource/resources/outsource.json`（mtp 直接 import 它的钱袋子，流水行用"来自"区分：outsource / hook / mtp）；触发判据与否决词表在 `config/outsource_trigger.json`。
- ★ **两道闸都要开**才会真摇：触发开关 + 钱袋子开关，只开一个 = 白跑一趟（hook 说摇、钱袋子拦下）。这个组合本身也要验（它证明"接不上就退"）。
- ★ 判"摇不摇"**由程序做**（要成段代码 / 左链检索不到 / 卡了明显时间 + 否决词表），不许模型自陈"我拿不准"。
- 加一家只动两处：`outsource.json` 的 `家` 加一条 + `.env` 写 `<前缀>_API_KEY/_BASE_URL/_MODEL`；★ 端点不认 `thinking` 字段的，`思考` 要设 `true`。验收用 `ask --家 <名> --强制`（`--强制` 只跳开关、不跳预算）。
- 记账别虚高：Hermes 那类端点每次吞自己 6.7 万 token 系统提示且不报缓存命中，单价要按实测有效价校准。批量活一律**直连 API**，别用这类端点（每件都有基础开销）。

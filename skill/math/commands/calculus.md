# calculus · 导数 / 积分 / 极限 / 求和 / 连乘

**用途**：微积分的数值件：导数（一阶、二阶）、定积分、极限（两侧逼近）、求和、连乘。表达式里自变量写 `x`；求和/连乘里写 `k`（`n` `i` 也认）。

**用法**
- `.venv/bin/python skill/math/main.py calculus 导数 "<f(x)>" <x0>`　/ `calculus 二阶导 "<f(x)>" <x0>`
- `.venv/bin/python skill/math/main.py calculus 积分 "<f(x)>" <a> <b>`
- `.venv/bin/python skill/math/main.py calculus 极限 "<f(x)>" <x0>`
- `.venv/bin/python skill/math/main.py calculus 求和 "<通项>" <起> <止>`　/ `calculus 连乘 "<通项>" <起> <止>`

**示例**
- `calculus 导数 "x^2" 3`　→ 6（稳定性 4e-11）
- `calculus 二阶导 "x^3" 2`　→ 12
- `calculus 积分 "x^2" 0 3`　→ 9（附误差估计）
- `calculus 极限 "sin(x)/x" 0`　→ 两侧都逼近 1
- `calculus 求和 "k^2" 1 100`　→ 338350（精确）

**备注**：①导数是中心差分（不是符号解）：输出里的"稳定性"是换步长再算的差，越小越可信。②积分是自适应 Simpson，误差估计不是严格上界；函数有尖点/间断时别当准。③求和/连乘逐项精确算（最多 200 万项）。

# units · 单位换算

**用途**：长度、质量、面积、体积、速度、数据量、时间、压力、能量、功率、角度、温度之间的换算。换算表里全是精确有理数（1 英里 = 1609.344 米 这种定值），所以结果是精确分数。

**用法**
- `.venv/bin/python skill/math/main.py units 换算 <数值> <源单位> <目标单位>`
- `.venv/bin/python skill/math/main.py units 温度 <数值> <源> <目标>`　C / F / K
- `.venv/bin/python skill/math/main.py units 表 [类别]`　看有哪些单位

**单位举例**：`m km cm mm 里 尺 寸 英里 ft in` / `kg g 斤 两 磅` / `平方米 公顷 亩` / `L mL 加仑` / `m/s km/h mph 节` / `B KB MB GB TB KiB MiB GiB TiB` / `秒 分钟 小时 天 周 年` / `Pa bar atm mmHg psi` / `J kcal kWh 度` / `W kW 马力` / `度 弧度`

**示例**
- `units 换算 10 km mi`　→ 6.213711922373… mi
- `units 换算 1 GiB MB`　→ 1073.741824 MB
- `units 换算 1 斤 g`　→ 500 g
- `units 温度 100 C F`　→ 212 F

**备注**：①跨类换不了（米→克 会直接报错）。②`GB`(1000³) 和 `GiB`(1024³) 别混。③温度走 `温度` 不走 `换算`（加减关系）。④**汇率不在表里**（实时行情得查资料），这里只做定值单位。

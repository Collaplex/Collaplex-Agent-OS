#!/usr/bin/env python3
"""外援自动触发的判据回归: 摇不摇 / 为什么 / 否决权 / 材料包装. 纯逻辑不联网.

跑法: .venv/bin/python tests/test_outsource_hook.py

★ 这组用例守的是项目铁律:**"拿不准"必须程序判**, 不许模型自己说"我不确定"。
 所以判据全是词表 + 秒数 + 标志位这类**看得见的事实**, 没有"交给模型感觉一下"的分支。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import outsource_hook  # noqa: E402

passed = 0
failed = 0


def check(label: str, got: object, want: object) -> None:
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label}: 得到 {got!r}, 想要 {want!r}")


def trigger(**overrides: Any) -> dict[str, Any]:
    """拿真配置当底子, 按用例改开关 —— 用例要现成配置, 不另抄一份词表(抄了就会漂)."""
    config = outsource_hook.load_trigger()
    config.update(overrides)
    return config


def main() -> int:
    print("外援自动触发 · 判据")

    print("[1] 要成段代码 (两道: 强命中词 或 动作词×代码名词)")
    on = trigger(开关=True)
    check("写个脚本 → 摇", outsource_hook.decide("写个把 GBK 转 UTF-8 的脚本", {}, 0.0, on)["摇"], True)
    check("帮我写个函数 → 摇", outsource_hook.decide("帮我写个读 csv 的函数", {}, 0.0, on)["摇"], True)
    check("为什么这个函数会报错 → 摇", outsource_hook.decide("这个函数为什么会报错", {}, 0.0, on)["摇"], True)
    check("重构这段代码 → 摇", outsource_hook.decide("重构这段代码", {}, 0.0, on)["摇"], True)
    check("改这段脚本 → 摇", outsource_hook.decide("改一下这段脚本的路径处理", {}, 0.0, on)["摇"], True)
    check("命中时级别=outsource", outsource_hook.decide("写个脚本", {}, 0.0, on)["级别"], "outsource")

    print("[1b] ★ 边界组: 本地答得上的知识题/写作题不许摇 (2026-10-07 真数据误触发)")
    check("解释函数和方法 (只有名词) → 不摇", outsource_hook.decide("解释一下 Python 里函数和方法有什么区别", {}, 0.0, on)["摇"], False)
    check("写个请假条 (只有动作) → 不摇", outsource_hook.decide("帮我写个请假条，说明我明天下午要去医院", {}, 0.0, on)["摇"], False)
    check("代码注释用中文还是英文 → 不摇", outsource_hook.decide("代码里的注释应该用中文还是英文", {}, 0.0, on)["摇"], False)
    check("这段代码是什么意思 (名词没动作) → 不摇", outsource_hook.decide("这段代码是什么意思", {}, 0.0, on)["摇"], False)
    check("不摇的理由写清是三条判据都没中", "判据都没命中" in outsource_hook.decide("这段代码是什么意思", {}, 0.0, on)["因为"], True)

    print("[2] ★ 不摇词表有否决权 (机器状态/闲聊 —— 外援帮不上)")
    check("看日志里的报错 → 不摇", outsource_hook.decide("看下日志里的报错", {}, 0.0, on)["摇"], False)
    check("查一下端口占用 → 不摇", outsource_hook.decide("查一下这个端口被谁占了", {}, 0.0, on)["摇"], False)
    check("重启服务 → 不摇", outsource_hook.decide("重启一下 nginx 服务", {}, 0.0, on)["摇"], False)
    check("现在几点 → 不摇", outsource_hook.decide("现在几点", {}, 0.0, on)["摇"], False)
    check("否决权优先于代码词", outsource_hook.decide("看下日志里的报错，写个脚本处理", {}, 0.0, on)["摇"], False)
    check("不摇的理由写清了命中词", "不摇" in outsource_hook.decide("看下日志里的报错", {}, 0.0, on)["因为"], True)

    print("[3] 左链检索不到 / 卡了明显时间")
    check("左链没找到 → 摇", outsource_hook.decide("帮我处理一下这个", {"左链检索不到": True}, 0.0, on)["摇"], True)
    check("花了 50 秒(阈值 45) → 摇", outsource_hook.decide("随便问点啥", {}, 50.0, on)["摇"], True)
    check("花了 10 秒 → 不摇", outsource_hook.decide("随便问点啥", {}, 10.0, on)["摇"], False)
    check("刚好到阈值就摇", outsource_hook.decide("随便问点啥", {}, 45.0, on)["摇"], True)
    check("理由里带上实际秒数", "50" in outsource_hook.decide("随便问点啥", {}, 50.0, on)["因为"], True)

    print("[4] 开关与判据开关")
    check("总开关关着 → 不摇", outsource_hook.decide("写个脚本", {}, 999.0, trigger(开关=False))["摇"], False)
    check("总开关关着也给理由", "关" in outsource_hook.decide("写个脚本", {}, 0.0, trigger(开关=False))["因为"], True)
    only = trigger(开关=True, 要成段代码={"开": False}, 卡了明显时间={"开": False}, 左链检索不到={"开": False})
    check("三条判据全关 → 不摇", outsource_hook.decide("写个脚本", {}, 999.0, only)["摇"], False)
    no_slow = trigger(开关=True, 卡了明显时间={"开": False})
    check("只关切『卡时间』→ 写入 999 秒也不摇", outsource_hook.decide("随便问问", {}, 999.0, no_slow)["摇"], False)

    print("[5] 参考材料的包装 (交给主 agent, 不替它下结论)")
    material = outsource_hook.build_material("outsource", "deepseek", "deepseek-flash", 1.2, 0.0012, "答案: 42")
    check("写明是参考", "参考" in material, True)
    check("写明出处与花费", ("deepseek" in material) and ("0.00120 元" in material), True)
    check("正文带上了", "答案: 42" in material, True)
    check("不许当结论: 明确可以否掉", "否掉" in material, True)
    panel_material = outsource_hook.build_material("mtp", "多家", "—", 0.0, 0.002, "# 交叉验证参考材料\n答案: 7")
    check("二级材料带上了原文", "答案: 7" in panel_material, True)

    print("[6] 判据是程序可见的事实 (没有『交给模型感觉一下』的分支)")
    source = (HERE.parent / "outsource_hook.py").read_text(encoding="utf-8")
    decide_head = source.split("def decide(")[1].split(")")[0]
    check("decide 不接模型客户端", "client" in decide_head, False)
    check("判据里没有任何模型调用", ".chat.completions" in source, False)
    check("判据只吃 事实(问题/声明/秒数/标志位)", "elapsed" in decide_head, True)

    print()
    print("-" * 40)
    print(f"通过 {passed} / 失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

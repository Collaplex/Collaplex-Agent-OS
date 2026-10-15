# -*- coding: utf-8 -*-
"""全量 59 条 A/B —— 用**两个**指标统计，别只报一个数。

老板的判据纪律：不能拿总准确率当判据，要同时看
  ① 该动没动（该去查/该动手，却直接给答案 —— A 的病）
  ② 不该动却动（本来就该直接答，却被反问/绕圈 —— 这是 B 的病！）

★ 为什么必须两个一起看（本日实测教训）：
  只报"该动没动 100%→7%"会得出"B 结构赢了"的错结论 —— 全量一跑才发现
  B 把翻译/化学式/概念题也逼成了"需要知道：…"，即**药到病也到**。
  所以：单一指标 = 骗自己；两个指标对照才叫判据。
"""
from __future__ import annotations

import json
from pathlib import Path

产出 = Path(__file__).parent

# 该动没动的那 14 条（标注里定的）
该动没动题号 = {2, 3, 4, 8, 9, 14, 17, 18, 20, 23, 26, 37, 38, 56}

# ★ 本来就该**直接答**的题（纯知识 / 纯任务 —— 反问一句都是病）
该直接答题号 = {5, 13, 15, 16, 19, 21, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36,
               39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 57, 58, 59}


def 读(条件: str) -> dict[int, str]:
    文件 = 产出 / f"AB-条件{条件}.jsonl"
    if not 文件.exists():
        return {}
    return {int(json.loads(l)["号"]): str(json.loads(l)["答"])
            for l in 文件.read_text().splitlines() if l.strip()}


def 是反问(答: str) -> bool:
    """B 条件失败时会把整段回答写成"需要知道：…" —— 这不算答了。"""
    return 答.strip().startswith("需要知道")


def 抓了数据(答: str) -> bool:
    """答案里出现了本机真值/真读出的内容 —— 粗略但有效的"真去查了"信号。"""
    真值标记 = ["8940HX", "Ryzen", "nvme", "build-info.h", "llama.h",
              "417G", "417 G", "已用 237", "686G", "Ubuntu 26.04", "7.0.0-38",
              "16 核", "16核", "ubuntu", "93:93", "187G"]
    return any(m in 答 for m in 真值标记)


if __name__ == "__main__":
    A, B = 读("A"), 读("B")
    if not A or not B:
        print(f"缺结果：A={len(A)} 条，B={len(B)} 条（全量跑要 59 条）")
        raise SystemExit(0)

    print(f"═══ 全量对照（A {len(A)} 条 / B {len(B)} 条）═══\n")

    组 = [("该动没动(14条)", 该动没动题号), ("该直接答(34条)", 该直接答题号)]
    print(f"{'指标':<16}{'A 直接问':<12}{'B 先取数':<12}{'含义'}")
    print("─" * 68)
    for 名, 号集 in 组:
        号集 = 号集 & set(A) & set(B)
        if 名.startswith("该动没动"):
            a = sum(1 for i in 号集 if not 抓了数据(A[i]))
            b = sum(1 for i in 号集 if not 抓了数据(B[i]))
            含义 = "↓ 越低越好"
        else:
            a = sum(1 for i in 号集 if 是反问(A[i]))
            b = sum(1 for i in 号集 if 是反问(B[i]))
            含义 = "↑ A 本来就好, B 反而加病"
        print(f"{名:<16}{f'{a}/{len(号集)}':<12}{f'{b}/{len(号集)}':<12}{含义}")

    print()
    print("【B 里被逼成『需要知道』的题】")
    坏 = sorted(i for i in 该直接答题号 & set(B) if 是反问(B[i]))
    print(f"  共 {len(坏)} 条：{坏}")
    print()
    print("【B 真去查了的题（该动没动那批）】")
    好 = sorted(i for i in 该动没动题号 & set(B) if 抓了数据(B[i]))
    print(f"  共 {len(好)} 条：{好}")

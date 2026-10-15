"""judge.md 触发判据对照探针 —— 正例(该触发 math) / 反例(不该触发) / 控制组(本就该触发 linux)。

跑法: cd /home/lou/桌面/collaplex_agent && .venv/bin/python <本脚本>
输出: 每题一行 need/wanted + 三组汇总数。
"""

import sys

sys.path.insert(0, "/home/lou/桌面/collaplex_agent")

from dotenv import load_dotenv

load_dotenv("/home/lou/桌面/collaplex_agent/.env")

import main as M
import sub_agent

正例: list[str] = [
    "算一下 0.1+0.2 的精确值, 别用浮点",
    "123456789 乘 987654321 等于多少",
    "帮我算 15% 折扣后的价格是多少",
    "求 2x+3=7 的解",
]
反例: list[str] = [
    "你好",
    "解释一下什么是递归",
    "写一段自我介绍",
    "为什么天空是蓝色的",
    "rm -rf 和 rm -r 有什么区别",
    "怎么删文件",
    "磁盘满了会有什么后果",
    "帮我写个 Python 函数算两数之和",
    "总结一下我们刚才聊的",
    "Python 和 C 哪个快",
]
控制组: list[str] = [
    "磁盘还剩多少空间",
    "8899 端口起一个临时服务",
]


def 逐题(组名: str, 题: list[str]) -> int:
    """跑一组题, 返回"触发了 skill"的条数。"""
    触发数 = 0
    for 问 in 题:
        判决 = sub_agent.prepare_skill(问)
        词 = M.retrieval_term(判决, 问)
        标 = "触发" if 词 else "不触发"
        if 词:
            触发数 += 1
        print(f"  [{标}] {问[:26]:28} wanted={词!r}")
    print(f"  ── {组名}: {触发数}/{len(题)} 触发")
    return 触发数


def main() -> int:
    print("=== 正例(算数, 改后应 4/4 触发) ===")
    正例触发 = 逐题("正例", 正例)
    print("=== 反例(答案在脑子里, 应 0/10 触发) ===")
    反例触发 = 逐题("反例", 反例)
    print("=== 控制组(本机实况, 应 2/2 触发) ===")
    控制触发 = 逐题("控制组", 控制组)
    print(f"\n汇总: 正例 {正例触发}/4 · 反例误触发 {反例触发}/10 · 控制组 {控制触发}/2")
    return 0


if __name__ == "__main__":
    sys.exit(main())

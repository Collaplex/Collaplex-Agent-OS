"""DeepSeek 那套原生工具调用(DSML)的识别与清洗回归.

背景(2026-10-09): 主线一换成 DeepSeek, exec agent 就"炸" —— 它吐命令时用的不是我们约定的
`<调用>命令</调用>`, 也不是小米 MiMo 那套 XML, 而是自己家的 DSML 标记. 程序一条命令都抠不出来,
判成"演", 催几轮还是听不懂, 最后把那串没人认领的标记原样留在了回答里.

这里不联网、不调模型, 只测"抠命令 / 清正文"两个纯函数:
  跑法: .venv/bin/python tests/test_dsml_calls.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import exec_agent

# 标记本体从转义拼出来 —— 以免源码里躺着不可见字符(全角竖线).
M = "\uff5c\uff5cDSML\uff5c\uff5c"

# 实测的完整形状(DeepSeek 吐出来的原样, 来自历史会话存档).
FULL_BLOCK = (
    "<" + M + "tool_calls>\n"
    "<" + M + 'invoke name="execute_command">\n'
    "<" + M + 'parameter name="command" string="true">ss -ltnp | grep 8899</' + M + "parameter>\n"
    "</" + M + "invoke>\n"
    "</" + M + "tool_calls>"
)

# 实测的"半截"形状: 只有闭合标签, 没有开标签 —— 语料里 `# 产出` 段就是这个样子.
HALF_TAGS = "</" + M + "parameter>\n</" + M + "invoke>\n</" + M + "calls>"


def test_full_block_extracted() -> bool:
    """成对的 DSML 块 ---> 抠出命令, 正文里不留标记."""
    answer = "我来查一下端口占用。\n\n" + FULL_BLOCK
    calls = exec_agent.extract_calls(answer)
    print("  抠到的命令:", calls)
    if calls != ["ss -ltnp | grep 8899"]:
        print("  ✗ 命令没抠对")
        return False
    cleaned = exec_agent.strip_calls(answer)
    print("  清完的正文:", repr(cleaned))
    if M in cleaned or "tool_calls" in cleaned:
        print("  ✗ DSML 标记漏进正文了")
        return False
    if "我来查一下端口占用。" not in cleaned:
        print("  ✗ 把正文的话一起清了")
        return False
    return True


def test_half_tags_cleaned() -> bool:
    """只有半截闭合标签(实测最常见的形状) ---> 标签清干净, 正文保留."""
    answer = "内存是 16G 单条。\n" + HALF_TAGS
    calls = exec_agent.extract_calls(answer)
    print("  抠到的命令:", calls)
    if calls:
        print("  ✗ 半截标签不该抠出命令")
        return False
    cleaned = exec_agent.strip_calls(answer)
    print("  清完的正文:", repr(cleaned))
    if M in cleaned:
        print("  ✗ 半截标签没清掉")
        return False
    if cleaned != "内存是 16G 单条。":
        print("  ✗ 正文被连累")
        return False
    return True


def test_own_call_plus_half_tags() -> bool:
    """语料里那两条污染的真实形状: 我们的 <调用> + DeepSeek 的半截标签."""
    answer = (
        "<调用>.venv/bin/python -c \"print(1)\"</调用>\n"
        "</" + M + "parameter>\n</" + M + "invoke>\n</" + M + "calls>"
    )
    calls = exec_agent.extract_calls(answer)
    print("  抠到的命令:", calls)
    if calls != ['.venv/bin/python -c "print(1)"']:
        print("  ✗ 我们的写法该照旧抠出来")
        return False
    cleaned = exec_agent.strip_calls(answer)
    print("  清完的正文:", repr(cleaned))
    if M in cleaned or "<调用>" in cleaned:
        print("  ✗ 还有标记残留")
        return False
    return True


def test_json_wrapped_parameter() -> bool:
    """参数值被套了一层 JSON 也要还原成命令本身."""
    answer = (
        "<" + M + "tool_calls>\n"
        "<" + M + 'invoke name="execute">\n'
        "<" + M + 'parameter name="arguments">{"command": "df -h", "explanation": "看盘"}</'
        + M + "parameter>\n"
        "</" + M + "invoke>\n"
        "</" + M + "tool_calls>"
    )
    calls = exec_agent.extract_calls(answer)
    print("  抠到的命令:", calls)
    if calls != ["df -h"]:
        print("  ✗ JSON 壳没剥掉")
        return False
    return True


def test_corpus_shape_unclosed_own_call() -> bool:
    """语料里实测的完整形状: <调用> 没收尾, 后面直接跟 DSML 闭合标记.

    这是出事那次的真身 —— 老的代码在这里一条命令都抠不出来(它只认收尾完整的 <调用>),
    于是判成"演"、催几轮、最后把这串没人认领的标记原样打进回答.
    """
    answer = (
        "# 产出\n<调用>.venv/bin/python -c \"print(1)\" ; echo 完"
        "</" + M + "parameter>\n</" + M + "invoke>\n</" + M + "calls>"
    )
    calls = exec_agent.extract_calls(answer)
    print("  抠到的命令:", calls)
    if calls != ['.venv/bin/python -c "print(1)" ; echo 完']:
        print("  ✗ 半截 <调用> 里的命令没抠出来")
        return False
    cleaned = exec_agent.strip_calls(answer)
    print("  清完的正文:", repr(cleaned))
    if M in cleaned or "<调用>" in cleaned:
        print("  ✗ 还有残留")
        return False
    return True


def test_old_two_ways_still_work() -> bool:
    """回归: 我们的约定 + MiMo 那套 XML 都还不能坏."""
    own = exec_agent.extract_calls("<调用>echo 甲</调用>")
    mimo = exec_agent.extract_calls(
        "<tool_call><function=execute_commands>"
        "<parameter=command>echo 乙</parameter>"
        "<parameter=explanation>随便</parameter></function></tool_call>"
    )
    print("  我们的:", own, "| MiMo 的:", mimo)
    if own != ["echo 甲"] or mimo != ["echo 乙"]:
        print("  ✗ 老的两套被改坏了")
        return False
    return True


def test_no_calls_still_says_no() -> bool:
    """判据不变: 一个命令都抠不出来时必须是空 —— 不能为了"接上 DeepSeek"就胡乱认定."""
    answer = "我来看看这台机器的配置。\n(只有预告语, 没有任何工具调用标记)"
    calls = exec_agent.extract_calls(answer)
    print("  抠到的命令:", calls)
    if calls:
        print("  ✗ 演的话被当成命令了")
        return False
    return True


def main() -> None:
    results: list[tuple[str, bool]] = []
    cases = [
        test_full_block_extracted,
        test_half_tags_cleaned,
        test_own_call_plus_half_tags,
        test_corpus_shape_unclosed_own_call,
        test_json_wrapped_parameter,
        test_old_two_ways_still_work,
        test_no_calls_still_says_no,
    ]
    for case in cases:
        print(f"-- {case.__name__}")
        results.append((case.__name__, bool(case())))
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'OK' if passed == len(results) else 'X'} DSML 识别 {passed}/{len(results)}")
    for name, ok in results:
        if not ok:
            print(f"   失败: {name}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()

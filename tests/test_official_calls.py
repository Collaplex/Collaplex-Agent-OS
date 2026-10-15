"""DeepSeek **官方 chat_template** 那套工具调用标记的识别与清洗回归.

背景(2026-10-09): 老板丢来 deepseek_v4_tokenizer.zip, 里头 tokenizer_config.json 的 chat_template
写明了官方渲染工具调用用的是哪串标记:

    <｜Assistant｜><｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function<｜tool▁sep｜>run_command
    ```json
    {"command": "ls -la"}
    ```<｜tool▁call▁end｜><｜tool▁calls▁end｜>

照模板原文造样本喂给我们自己的解析器: 一条命令都抠不出、一个标记都清不掉 —— 跟 DSML 那次同形的坑.
顺带补了同族的另一种外壳 `<dsml:`(tokenizer 里躺着 <dsml: 与 </dsml: 两个 token).

这里不联网、不调模型, 只测"抠命令 / 清正文 / 扫污染"这几板斧:
  跑法: .venv/bin/python tests/test_official_calls.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import exec_agent
import native_marks

# 标记原子从转义拼出来 —— 以免源码里躺着不可见字符(全角竖线 / ▁).
B = "\uff5c"
S = "\u2581"


def 官方块(cmd: str) -> str:
    """照 chat_template 的渲染结果拼一个工具调用块."""
    return (
        f"<{B}Assistant{B}>"
        f"<{B}tool{S}calls{S}begin{B}>"
        f"<{B}tool{S}call{S}begin{B}>function<{B}tool{S}sep{B}>run_command\n"
        "```json\n"
        '{"command": "' + cmd + '"}\n'
        "```"
        f"<{B}tool{S}call{S}end{B}>"
        f"<{B}tool{S}calls{S}end{B}>"
        f"<{B}end{S}of{S}sentence{B}>"
    )


def test_official_template_block() -> bool:
    """官方模板渲染的整块 ---> 抠出命令; 清完连参数壳都不留."""
    answer = "我来看看目录。\n" + 官方块("ls -la /home/lou")
    calls = exec_agent.extract_calls(answer)
    print("  抠到的命令:", calls)
    if calls != ["ls -la /home/lou"]:
        print("  ✗ 官方那套标记里的命令没抠出来")
        return False
    cleaned = exec_agent.strip_calls(answer)
    print("  清完的正文:", repr(cleaned))
    if cleaned != "我来看看目录。":
        print("  ✗ 标记或参数壳漏进正文了")
        return False
    return True


def test_official_bare_json() -> bool:
    """参数没装 ```json 围栏, 直接一个 JSON 壳 ---> 照样抠得出来."""
    answer = (
        f"<{B}tool{S}call{S}begin{B}>function<{B}tool{S}sep{B}>run_command\n"
        '{"command": "wc -l main.py", "timeout": 30}'
        f"<{B}tool{S}call{S}end{B}>"
    )
    calls = exec_agent.extract_calls(answer)
    print("  抠到的命令:", calls)
    if calls != ["wc -l main.py"]:
        print("  ✗ 裸 JSON 里的命令没抠出来")
        return False
    if exec_agent.strip_calls(answer) != "":
        print("  ✗ 没清干净")
        return False
    return True


def test_official_nested_arguments() -> bool:
    """命令套在 {"arguments": {"command": ...}} 里(OpenAI 那个 function.arguments 的样子)."""
    answer = (
        f"<{B}tool{S}calls{S}begin{B}>"
        f"<{B}tool{S}call{S}begin{B}>function<{B}tool{S}sep{B}>run_command\n"
        '```json\n{"arguments": {"command": "df -h"}}\n```'
        f"<{B}tool{S}call{S}end{B}>"
        f"<{B}tool{S}calls{S}end{B}>"
    )
    calls = exec_agent.extract_calls(answer)
    print("  抠到的命令:", calls)
    if calls != ["df -h"]:
        print("  ✗ 套一层的 JSON 壳没剥掉")
        return False
    return True


def test_dsml_alternate_shell() -> bool:
    """DSML 方言的另一种外壳 <dsml: (tokenizer 里那对 <dsml:/</dsml: token)."""
    answer = (
        '<dsml:tool_calls><dsml:invoke name="run_command">'
        '<dsml:parameter name="command">hostname</dsml:parameter>'
        "</dsml:invoke></dsml:tool_calls>"
    )
    calls = exec_agent.extract_calls(answer)
    print("  抠到的命令:", calls)
    if calls != ["hostname"]:
        print("  ✗ <dsml: 那套没认")
        return False
    if exec_agent.strip_calls(answer) != "":
        print("  ✗ <dsml: 那套没清干净")
        return False
    return True


def test_corpus_gate_ignores_doc_mention() -> bool:
    """扫语料的闸门只认"会外泄被模仿"的工具/role 标记 —— 文档里提一句 bos/eos 不算污染.

    ★ 这一条是 2026-10-09 特意校准的: 语料里本来就有一份讲 tokenizer 的文档,
      它正文里必须能写 "<｜begin▁of▁sentence｜> 是 bos", 别被当脏东西清掉。
    """
    文档 = "特殊 token 家族(如 <｜...｜> 系列)里有 <｜begin▁of▁sentence｜> 和 <｜end▁of▁sentence｜>。"
    if native_marks.has_native_marker(文档):
        print("  ✗ 把文档正文当成污染了")
        return False
    if not native_marks.has_native_marker(文档 + 官方块("ls")):
        print("  ✗ 真的混进工具标记却看不见")
        return False
    return True


def test_old_marks_still_work() -> bool:
    """回归: 自家 <调用> / MiMo / DSML 三套都不能被本轮改动破坏."""
    own = exec_agent.extract_calls("<调用>echo 甲</调用>")
    mimo = exec_agent.extract_calls(
        "<tool_call><parameter=command>echo 乙</parameter></tool_call>"
    )
    dsml = exec_agent.extract_calls(
        "<" + native_marks.DSML + 'tool_calls><' + native_marks.DSML + 'invoke name="run_command">'
        "<" + native_marks.DSML + 'parameter name="command">echo 丙</'
        + native_marks.DSML + "parameter></" + native_marks.DSML + "invoke></"
        + native_marks.DSML + "tool_calls>"
    )
    print("  我们的:", own, "| MiMo 的:", mimo, "| DSML 的:", dsml)
    if own != ["echo 甲"] or mimo != ["echo 乙"] or dsml != ["echo 丙"]:
        print("  ✗ 老的三套被改坏了")
        return False
    return True


def test_no_calls_still_says_no() -> bool:
    """判据不变: 抠不出命令就是空 —— 别为了"多认一家"把演的话也认成命令."""
    calls = exec_agent.extract_calls("我来看看这台机器的配置。\n(只有预告语)")
    print("  抠到的命令:", calls)
    if calls:
        print("  ✗ 演的话被当成命令了")
        return False
    return True


def main() -> None:
    results: list[tuple[str, bool]] = []
    cases = [
        test_official_template_block,
        test_official_bare_json,
        test_official_nested_arguments,
        test_dsml_alternate_shell,
        test_corpus_gate_ignores_doc_mention,
        test_old_marks_still_work,
        test_no_calls_still_says_no,
    ]
    for case in cases:
        print(f"-- {case.__name__}")
        results.append((case.__name__, bool(case())))
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'OK' if passed == len(results) else 'X'} 官方模板标记 {passed}/{len(results)}")
    for name, ok in results:
        if not ok:
            print(f"   失败: {name}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()

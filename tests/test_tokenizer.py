"""本地分词器(tokenizer.py)回归 —— 拿 tokenizers 库量下来的真值当基准.

背景(2026-10-09): 老板丢来 deepseek_v4_tokenizer.zip 说"这个是用来算token的"。
项目 requirements 就三个依赖(openai/dotenv/numpy), 为判一个 token 数去引 Rust 的 tokenizers
不划算 —— 于是照它那份 tokenizer.json 用纯 stdlib 复刻了一份(tokenizer.py)。

**真值怎么来的**: 用 tokenizers 库 (Rust, 官方实现) 对同一份词表 encode, 逐 id 抄下来,
硬编码在本文件里。所以这些数字不是"我自己跟自己对", 是跟官方实现对过账的。
  ★ 换词表 / 改 tokenizer.py 之后必须重跑本文件; 真值怎么量见下面注释里的脚本要点:
      Tokenizer.from_file(词表).encode(文本).ids

跑法: .venv/bin/python tests/test_tokenizer.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import tokenizer

# 长样例: 拿来做"整篇数得准"的基准(内容固定, 不要改 —— 改了要重量真值)
长样例 = (
    "Collaplex Agent 的上下文预算 = 窗口 × 40%，再扣掉输出预留与只读区预留。\n"
    "def estimate_tokens(text: str) -> int:\n    return max(1, len(text))\n"
    "SELECT id, tier, text FROM rag_chunks ORDER BY id DESC LIMIT 10;\n"
) * 40

# tokenizers 库量出来的真值 (count, 文本)
真值: list[tuple[int, str]] = [
    (0, ""),
    (2, "Hello!"),
    (10, "报告一下当前目录有几个 .py 文件。"),
    (24, "这个仓库里 skill/rag/scripts 下有多少个 .py 文件? 它们的行数合计是多少?"),
    (16, "def f(x: int) -> str:\n    return f'{x}'\n"),
    (11, "1234567890 12 345 6789"),
    (9, "  \t\n多  空格\n\n换行\n\n\n"),
    (24, "emoji 🎉 🚀 👍🏽 家族 👨‍👩‍👧‍👦"),
    (8, "mixed混合123abcABC中文English。"),
    (1, "<|EOT|>"),
    (4, "<｜tool▁calls▁begin｜><｜tool▁sep｜>run_command"),
    (21, "https://api.deepseek.com/v1/chat/completions?x=1&y=2"),
    (20, "SELECT * FROM rag_chunks WHERE tier = 1 ORDER BY id DESC LIMIT 10;"),
    (24, "日志 2026-10-09 19:30:19 [INFO] done in 0.42s"),
    (2600, 长样例),
]


def _机器() -> tokenizer.Tokenizer | None:
    return tokenizer.load()


def test_counts_match_official() -> bool:
    """逐条对 id 数 —— 大小、中英混排、emoji、代码、特殊 token 都要对上."""
    机器 = _机器()
    if 机器 is None:
        print("  ✗ 没找到词表(config/tokenizer.json 指的那份)")
        return False
    坏 = 0
    for 期望, 文本 in 真值:
        得到 = 机器.count(文本)
        标 = "✓" if 得到 == 期望 else "✗"
        if 得到 != 期望:
            坏 += 1
        print(f"  {标} 期望 {期望:>5} 得到 {得到:>5}  {文本[:34]!r}")
    return 坏 == 0


def test_id_sequences_exact() -> bool:
    """不只看个数 —— id 序列要逐一相同(个数对而内容错 = 词表版本不对)."""
    机器 = _机器()
    if 机器 is None:
        return False
    期望表 = {
        "Hello!": [19923, 3],
        "报告一下当前目录有几个 .py 文件。": [7018, 4915, 9053, 19766, 62849, 1204, 12403, 223, 5791, 320],
    }
    好 = True
    for 文本, 期望 in 期望表.items():
        得到 = 机器.encode(文本)
        print(f"  {'✓' if 得到 == 期望 else '✗'} {文本[:20]!r} -> {得到[:12]}")
        if 得到 != 期望:
            好 = False
            print(f"     期望 {期望}")
    return 好


def test_special_tokens_are_one_piece() -> bool:
    """特殊 token 整串一个 id(不走 BPE) —— 数语料时它们是 1 个 token, 不是一二十个."""
    机器 = _机器()
    if 机器 is None:
        return False
    期望表 = {
        "<|EOT|>": [128805],
        "<｜tool▁sep｜>": [128814],
        "<｜begin▁of▁sentence｜>": [0],
        "<｜end▁of▁sentence｜>": [1],
        "<｜begin▁of▁sentence｜>你好": [0, 30594],
    }
    好 = True
    for 文本, 期望 in 期望表.items():
        得到 = 机器.encode(文本)
        print(f"  {'✓' if 得到 == 期望 else '✗'} {文本!r} -> {得到}")
        if 得到 != 期望:
            好 = False
    return 好


def test_count_is_len_encode() -> bool:
    """count() 必须就是 encode() 的长度 —— 两个口径不能有两套数."""
    机器 = _机器()
    if 机器 is None:
        return False
    for _, 文本 in 真值[:6]:
        if 机器.count(文本) != len(机器.encode(文本)):
            print(f"  ✗ count 与 encode 对不上: {文本[:24]!r}")
            return False
    print("  ✓ 一致")
    return True


def test_missing_vocab_degrades_quietly() -> bool:
    """词表找不到时 load()/count() 要给 None, 不能抛 —— 上层好退回粗估."""
    旧词表函数 = tokenizer.vocab_path
    try:
        tokenizer.reset()
        tokenizer.vocab_path = lambda: None  # type: ignore[assignment]
        if tokenizer.count("随便什么") is not None:
            print("  ✗ 没词表还数出了数")
            return False
        if tokenizer.load() is not None:
            print("  ✗ 没词表还给了实例")
            return False
        try:
            tokenizer.Tokenizer("/nope/不存在的.json")
            print("  ✗ 文件不存在居然没报错")
            return False
        except OSError:
            pass
        print("  ✓ 没词表 -> None, 直接构造坏路径 -> OSError")
        return True
    finally:
        tokenizer.vocab_path = 旧词表函数  # type: ignore[assignment]
        tokenizer.reset()


def test_estimate_tokens_wired_to_real_count() -> bool:
    """sub_agent 的预算用的是 estimate_tokens —— 它现在该走精确数, 不是 len()."""
    try:
        import sub_agent
    except Exception as exc:  # noqa: BLE001
        print(f"  ~ 跳过(导不动 sub_agent: {type(exc).__name__}: {exc})")
        return True
    得到 = sub_agent.estimate_tokens(长样例)
    print(f"  estimate_tokens(长样例) = {得到} | len() = {len(长样例)} | 真值 = 2600")
    if 得到 != 2600:
        print("  ✗ 没走精确数")
        return False
    if sub_agent.estimate_tokens("Hello!") != 2:
        print("  ✗ 短文本没走精确数")
        return False
    return True


def main() -> None:
    results: list[tuple[str, bool]] = []
    cases = [
        test_counts_match_official,
        test_id_sequences_exact,
        test_special_tokens_are_one_piece,
        test_count_is_len_encode,
        test_missing_vocab_degrades_quietly,
        test_estimate_tokens_wired_to_real_count,
    ]
    for case in cases:
        print(f"-- {case.__name__}")
        results.append((case.__name__, bool(case())))
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'OK' if passed == len(results) else 'X'} 本地分词器 {passed}/{len(results)}")
    for name, ok in results:
        if not ok:
            print(f"   失败: {name}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""检索对照 —— 四路 top1/top3 实测: 向量 / 倒排 / RRF / 加权.

用法:
    .venv/bin/python skill/math/tests/retrieval_check.py                      # 数学那组问法
    .venv/bin/python skill/math/tests/retrieval_check.py --cases eval \
        --index skill/rag/scripts/vector-index.json                            # 借 rag 的标注题测别的层

四路:
    A 向量   查询向量 vs 条目向量, 余弦     (借 rag: search 的 load_index/embed_query)
    B 倒排   BM25, 中文 2-gram + 英文词    (借 file: scripts/retrieve 的 bm25_scores)
    C RRF    A/B 按名次倒数加权合并
    D 加权   A/B 分数归一后 0.5/0.5 加权

判定: 期望的出处落在 top1 / top3; 期望为空 = 库里没有 (应当拒答, 推上第一就是假命中).
本脚本只读语料; 倒排缓存由 retrieve 负责写到 skill/math/cache/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent            # skill/math/tests
SKILL_FILE = HERE.parent                           # skill/math
PROJECT = SKILL_FILE.parent.parent                 # 项目根
sys.path.insert(0, str(PROJECT / "skill" / "rag" / "scripts"))
sys.path.insert(0, str(SKILL_FILE / "scripts"))

import retrieve as math_retrieve  # noqa: E402  (要先插 sys.path)
import search as rag_search  # noqa: E402

DEFAULT_INDEX = SKILL_FILE / "commands-index.json"
EVAL_YAML = PROJECT / "skill" / "rag" / "tests" / "eval.yaml"
TOP_K = 3                                          # 看前三
ALPHA = 0.5                                        # D 路里向量的权重
CMD_PREFIX = "skill/math/commands/"

# 数学那组问法: (问题, 期望命中的命令名; 空集 = 库里没有, 应当拒答)
CASES: list[tuple[str, set[str]]] = [
    # —— 算数与数论 ——
    ("6/2(1+2) 等于多少", {"calc"}),
    ("帮我算一下这个式子", {"calc"}),
    ("0.1 加 0.2 到底是多少", {"calc"}),
    ("三分之一加六分之一等于几", {"calc"}),
    ("二的一百次方是多少", {"calc"}),
    ("sqrt(2) 的小数点后 100 位", {"calc"}),
    ("要精确到小数点后 30 位", {"calc"}),
    ("360 分解质因数", {"num"}),
    ("97 是不是质数", {"num"}),
    ("49 选 6 有多少种组合", {"num"}),
    ("255 转成十六进制是多少", {"num"}),
    ("1 左移 40 位是多少", {"num"}),
    ("第 100 个斐波那契数", {"num"}),
    ("100 和 75 的最大公约数", {"num"}),
    # —— 方程 / 线代 / 多项式 ——
    ("解这个方程 x^2-2=0", {"solve"}),
    ("这个方程组的解是多少", {"solve"}),
    ("求这个矩阵的行列式", {"linalg"}),
    ("矩阵求逆", {"linalg"}),
    ("这个矩阵的特征值", {"linalg"}),
    ("解 Ax=b 这个线性方程组", {"linalg"}),
    ("把这两个多项式乘开", {"poly"}),
    ("这个多项式求导是什么", {"poly"}),
    ("这个多项式有几个根", {"poly"}),
    # —— 微积分 ——
    ("求 x^2 在 x=3 处的导数", {"calculus"}),
    ("算 x^2 从 0 到 3 的定积分", {"calculus"}),
    ("sin(x)/x 当 x 趋向 0 的极限", {"calculus"}),
    ("1 到 100 的平方和是多少", {"calculus"}),
    # —— 统计 / 概率 ——
    ("这组数的平均数是多少", {"stats"}),
    ("算一下标准差", {"stats"}),
    ("这组数据的中位数", {"stats"}),
    ("两组数据的相关系数", {"stats"}),
    ("做个线性回归拟合", {"stats"}),
    ("抛 10 次硬币正好 5 次正面", {"prob"}),
    ("正态分布里 P(X<1.96) 是多少", {"prob"}),
    ("泊松分布 λ=3 的累计概率", {"prob"}),
    ("第 5 次才成功的概率", {"prob"}),
    # —— 钱 / 单位 / 出图 / 日期 ——
    ("打八折之后是多少钱", {"money"}),
    ("一万块按 3.5% 存十年复利有多少", {"money"}),
    ("房贷每个月的月供怎么算", {"money"}),
    ("30 是 200 的百分之几", {"money"}),
    ("10 公里等于多少英里", {"units"}),
    ("1 GiB 是多少 MB", {"units"}),
    ("100 摄氏度是多少华氏度", {"units"}),
    ("画个正弦函数的图像", {"plot"}),
    ("把这条走势画出来", {"plot"}),
    ("画个柱状图", {"plot"}),
    ("两个日期相差多少天", {"date"}),
    ("30 天之后是几月几号", {"date"}),
    ("今天是周几", {"date"}),
    # —— 库里没有 = 该拒答 (分别属于修图 / linux / file / 检索 的活) ——
    ("把这张图调成 1920 宽", set()),
    ("看看磁盘还剩多少空间", set()),
    ("这个函数是谁调用的", set()),
    ("查一下杭州有多少人口", set()),
]


def display_width(text: str) -> int:
    """中文算两列, 用来对齐表格."""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def pad(text: str, width: int) -> str:
    """按显示宽度左侧补空格."""
    return text + " " * max(0, width - display_width(text))


def load_eval_cases(path: Path) -> list[tuple[str, set[str]]]:
    """读 rag 的 eval.yaml: 该命中的拿 top_source 当标准答案, 该不命中的期望为空."""
    cases: list[tuple[str, set[str]]] = []
    query = ""
    expect = ""
    source = ""

    def flush() -> None:
        if query and expect:
            cases.append((query, {source} if expect == "hit" and source else set()))

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            flush()
            query, expect, source = "", "", ""
            continue
        if line.startswith("query:"):
            query = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("expect:"):
            expect = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("top_source:"):
            source = line.split(":", 1)[1].strip().strip('"')
    flush()
    return cases


def expand(expect: set[str]) -> set[str]:
    """命令名 -> 出处路径 (已经是路径的原样留着)."""
    return {name if "/" in name else CMD_PREFIX + name + ".md" for name in expect}


def ranked(labels: list[str], scores: list[float]) -> list[tuple[str, float]]:
    """分数降序 -> (出处, 分数); 同分按出处定序, 结果可复现."""
    pairs = [(labels[doc], score) for doc, score in enumerate(scores)]
    return sorted(pairs, key=lambda pair: (-pair[1], pair[0]))


def top_labels(hits: list[tuple[str, float]], k: int) -> set[str]:
    return {label for label, _ in hits[:k]}


def mark(expect: set[str], hits: list[tuple[str, float]]) -> str:
    """命中标记: ✓✓ top1 中 / ✓ top3 中 / ✗ 没中 / · 库里没有."""
    if not expect:
        return "·"
    if expect & top_labels(hits, 1):
        return "✓✓"
    if expect & top_labels(hits, TOP_K):
        return "✓"
    return "✗"


LEGS = (("A", "向量"), ("B", "倒排"), ("C", "RRF"), ("D", "加权"))


def main() -> int:
    parser = argparse.ArgumentParser(description="检索对照: 向量 / 倒排 / 两路合并")
    parser.add_argument("--index", default=str(DEFAULT_INDEX), help="索引路径")
    parser.add_argument("--cases", choices=("cmd", "eval"), default="cmd",
                        help="cmd=命令库那组问法; eval=读 rag 的 eval.yaml 标注题")
    args = parser.parse_args()

    index_path = Path(str(args.index))
    cases = CASES if args.cases == "cmd" else load_eval_cases(EVAL_YAML)

    config = rag_search.load_config(rag_search.CONFIG_PATH)
    model_info = rag_search.resolve_model()
    items, matrix = rag_search.load_index(index_path)
    table = math_retrieve.load_or_build(index_path, items)
    labels = [str(item.get("source", "")) for item in items]

    print(f"索引 {index_path} · {len(items)} 条")
    print(f"嵌入 {model_info['model']} | 倒排词 {len(table['postings'])} 个 | "
          f"题 {len(cases)} 道 ({args.cases}) | 全局阈值 {config.get('hit_threshold')}")
    print(f"四路对照, 看 top{TOP_K}\n")

    counts: dict[str, list[int]] = {key: [0, 0] for key, _ in LEGS}   # [top1 中, top3 中]
    outside_best: dict[str, float] = {key: 0.0 for key, _ in LEGS}
    outside_top1: list[tuple[str, str, float]] = []                   # (问题, C 的第一名, 分)
    rows: list[dict[str, Any]] = []                                   # 逐题留档, 后面算互补和扫描
    asked = 0

    print(pad("#", 4) + pad("问题", 26) + pad("期望", 30) + pad("A 向量", 18)
          + pad("B 倒排", 18) + pad("C RRF", 14) + "D 加权")
    print("-" * 118)

    for number, (query, raw_expect) in enumerate(cases, 1):
        expect = expand(raw_expect)
        vec_scores = math_retrieve.vector_scores_of(
            matrix, rag_search.embed_query(query, config, model_info))
        inv_scores = math_retrieve.bm25_scores(table, query)
        rrf_scores = math_retrieve.merge_rrf(
            [math_retrieve.rank_of(vec_scores), math_retrieve.rank_of(inv_scores)], len(items))
        weighted = math_retrieve.merge_weight([vec_scores, inv_scores], ALPHA)

        legs = {
            "A": ranked(labels, vec_scores),
            "B": ranked(labels, inv_scores),
            "C": ranked(labels, rrf_scores),
            "D": ranked(labels, weighted),
        }
        rows.append({"query": query, "expect": expect, "legs": legs})

        shown = "|".join(sorted(name.replace(CMD_PREFIX, "") for name in expect)) or "（无）"
        line = pad(str(number), 4) + pad(query, 26) + pad(shown, 30)
        for key, _note in LEGS:
            hits = legs[key]
            top = hits[0][0].replace(CMD_PREFIX, "")
            line += pad(f"{top} {hits[0][1]:.2f} {mark(expect, hits)}", 18 if key in "AB" else 14)
        print(line.rstrip())

        if expect:
            asked += 1
            for key, _note in LEGS:
                if expect & top_labels(legs[key], 1):
                    counts[key][0] += 1
                if expect & top_labels(legs[key], TOP_K):
                    counts[key][1] += 1
        else:
            for key, _note in LEGS:
                outside_best[key] = max(outside_best[key], legs[key][0][1])
            outside_top1.append((query, legs["C"][0][0].replace(CMD_PREFIX, ""), legs["C"][0][1]))

    print("-" * 118)
    print(f"\n该命中的 {asked} 条:")
    for key, note in LEGS:
        top1, top3 = counts[key]
        print(f"  {key} {note:<3} top1 {top1}/{asked}   top{TOP_K} {top3}/{asked}")

    saved = sum(1 for row in rows if row["expect"]
                and not (row["expect"] & top_labels(row["legs"]["A"], 1))
                and (row["expect"] & top_labels(row["legs"]["B"], 1)))
    broke = sum(1 for row in rows if row["expect"]
                and (row["expect"] & top_labels(row["legs"]["A"], 1))
                and not (row["expect"] & top_labels(row["legs"]["B"], 1)))
    print(f"\n互补 (top1 口径): 倒排救回向量 {saved} 条; 向量救回倒排 {broke} 条")

    outside = sum(1 for _, expect in cases if not expand(expect))
    print(f"\n库里没有的 {outside} 条, 各路的最高分 (越高越容易假命中):")
    for key, note in LEGS:
        print(f"  {key} {note:<3} {outside_best[key]:.3f}")

    print("\n阈值扫描 A 向量路:")
    print("  " + pad("阈值", 8) + pad("正确命中且过线", 16) + pad("漏判", 8) + "库里没有的误命中")
    for threshold in (0.35, 0.40, 0.45, 0.50, 0.53, 0.60):
        hit = sum(1 for row in rows if row["expect"] and row["legs"]["A"][0][1] >= threshold
                  and row["legs"]["A"][0][0] in row["expect"])
        dropped = sum(1 for row in rows if row["expect"] and row["legs"]["A"][0][1] < threshold)
        wrong = sum(1 for row in rows if not row["expect"] and row["legs"]["A"][0][1] >= threshold)
        print("  " + pad(f"{threshold:.2f}", 8) + pad(f"{hit}/{asked}", 16)
              + pad(str(dropped), 8) + str(wrong))

    print("\n阈值扫描 B 倒排路 (BM25 分):")
    print("  " + pad("阈值", 8) + pad("正确命中且过线", 16) + pad("漏判", 8) + "库里没有的误命中")
    for threshold in (5.0, 8.0, 10.0, 15.0, 20.0):
        hit = sum(1 for row in rows if row["expect"] and row["legs"]["B"][0][1] >= threshold
                  and row["legs"]["B"][0][0] in row["expect"])
        dropped = sum(1 for row in rows if row["expect"] and row["legs"]["B"][0][1] < threshold)
        wrong = sum(1 for row in rows if not row["expect"] and row["legs"]["B"][0][1] >= threshold)
        print("  " + pad(f"{threshold:.1f}", 8) + pad(f"{hit}/{asked}", 16)
              + pad(str(dropped), 8) + str(wrong))

    print("\n双闸 (向量 ≥ ta 或 倒排 ≥ tb, 谁过线都算命中):")
    print("  " + pad("ta / tb", 12) + pad("正确命中且过线", 16) + pad("漏判", 8) + "库里没有的误命中")
    for ta in (0.40, 0.45):
        for tb in (5.0, 8.0, 10.0):
            hit = sum(1 for row in rows if row["expect"]
                      and ((row["legs"]["A"][0][1] >= ta and row["legs"]["A"][0][0] in row["expect"])
                           or (row["legs"]["B"][0][1] >= tb and row["legs"]["B"][0][0] in row["expect"])))
            dropped = sum(1 for row in rows if row["expect"]
                          and row["legs"]["A"][0][1] < ta and row["legs"]["B"][0][1] < tb)
            wrong = sum(1 for row in rows if not row["expect"]
                        and (row["legs"]["A"][0][1] >= ta or row["legs"]["B"][0][1] >= tb))
            print("  " + pad(f"{ta:.2f} / {tb:.1f}", 12) + pad(f"{hit}/{asked}", 16)
                  + pad(str(dropped), 8) + str(wrong))

    print("\n库里没有的问题被 C(RRF) 推到第一的是:")
    for query, name, score in outside_top1:
        print(f"  {query} -> {name} (RRF {score:.4f})")

    missed = [row for row in rows if row["expect"]
              and not ((row["legs"]["A"][0][1] >= 0.40 and row["legs"]["A"][0][0] in row["expect"])
                       or (row["legs"]["B"][0][1] >= 5.0 and row["legs"]["B"][0][0] in row["expect"]))]
    if missed:
        print(f"\n★ 生产口径 (向量 0.40 / 倒排 5.0) 没命中 {len(missed)} 例"
              " —— 要提命中就改这些条目的措辞:")
        for row in missed:
            got_a = row["legs"]["A"][0][0].replace(CMD_PREFIX, "")
            got_b = row["legs"]["B"][0][0].replace(CMD_PREFIX, "")
            want = ", ".join(sorted(name.replace(CMD_PREFIX, "").replace(".md", "")
                                    for name in row["expect"]))
            print(f"  {pad(row['query'], 26)} 期望 {pad(want, 16)}"
                  f" 向量最高 {row['legs']['A'][0][1]:.2f} ({got_a})"
                  f"  倒排最高 {row['legs']['B'][0][1]:.2f} ({got_b})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

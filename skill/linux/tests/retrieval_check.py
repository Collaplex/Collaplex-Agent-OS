#!/usr/bin/env python3
"""检索对照 —— 四路 top1/top3 实测: 向量 / 倒排 / RRF / 加权.

用法:
    .venv/bin/python skill/linux/tests/retrieval_check.py                      # 命令库那组问法
    .venv/bin/python skill/linux/tests/retrieval_check.py --cases eval \
        --index skill/rag/scripts/vector-index.json                            # 借 rag 的标注题测别的层

四路:
    A 向量   查询向量 vs 条目向量, 余弦     (借 rag: search 的 load_index/embed_query)
    B 倒排   BM25, 中文 2-gram + 英文词    (借 linux: scripts/retrieve 的 bm25_scores)
    C RRF    A/B 按名次倒数加权合并
    D 加权   A/B 分数归一后 0.5/0.5 加权

判定: 期望的出处落在 top1 / top3; 期望为空 = 库里没有 (应当拒答, 推上第一就是假命中).
本脚本只读语料; 倒排缓存由 retrieve 负责写到 skill/linux/cache/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent            # skill/linux/tests
SKILL_LINUX = HERE.parent                          # skill/linux
PROJECT = SKILL_LINUX.parent.parent                # 项目根
sys.path.insert(0, str(PROJECT / "skill" / "rag" / "scripts"))
sys.path.insert(0, str(SKILL_LINUX / "scripts"))

import retrieve as linux_retrieve  # noqa: E402  (要先插 sys.path)
import search as rag_search  # noqa: E402

DEFAULT_INDEX = SKILL_LINUX / "commands-index.json"
EVAL_YAML = PROJECT / "skill" / "rag" / "tests" / "eval.yaml"
TOP_K = 3                                          # 看前三
ALPHA = 0.5                                        # D 路里向量的权重
CMD_PREFIX = "skill/linux/commands/"

# 命令库那组问法: (问题, 期望命中的命令名; 空集 = 库里没有, 应当拒答)
CASES: list[tuple[str, set[str]]] = [
    ("磁盘还剩多少空间", {"df"}),
    ("这盘是不是快满了", {"df"}),
    ("根分区还剩多少", {"df"}),
    ("哪个文件夹最占地方", {"du"}),
    ("各个目录分别占多大", {"du"}),
    ("我那块硬盘挂上了没有", {"lsblk", "mount"}),
    ("插的 U 盘认到没", {"lsblk", "mount"}),
    ("怎么把挂着的盘卸下来", {"mount"}),
    ("内存还剩多少", {"free"}),
    ("是不是快没内存了", {"free"}),
    ("现在跑着哪些进程", {"ps", "top"}),
    ("我这程序还在跑吗", {"pgrep", "ps"}),
    ("谁占着 8789 端口", {"ss", "lsof"}),
    ("我的服务是不是挂了", {"systemctl", "journalctl"}),
    ("看一下最近的日志", {"journalctl", "tail"}),
    ("按名字找个文件", {"find"}),
    ("这堆代码里哪儿用到这个函数", {"grep"}),
    ("这个目录里都有啥", {"ls"}),
    ("装个新软件包", {"apt"}),
    ("现在几点了", {"date"}),
    ("我的定时任务都有啥", {"crontab"}),
    ("帮我把这张图调成 1920 宽", set()),
    ("把这段视频剪掉前五秒", set()),
    # —— 2026-10-06 补的 24 条（系统/硬件/文本/文件/网络/packaging/进程/外设）——
    ("这台机器开机多久了", {"uptime", "top"}),
    ("CPU 温度多少", {"sensors"}),
    ("显卡温度多高", {"sensors", "nvidia-smi"}),
    ("显存还剩多少", {"nvidia-smi"}),
    ("谁在占着显卡", {"nvidia-smi"}),
    ("内核日志里报了什么错", {"dmesg", "journalctl"}),
    ("谁最吃内存", {"top", "free", "ps"}),
    ("实时看进程排行", {"top"}),
    ("看看这个文件开头几行", {"head"}),
    ("这个文件有多少行", {"wc"}),
    ("按大小把这些文件排一下", {"sort"}),
    ("统计出现最多的十项", {"uniq", "sort"}),
    ("比一下这两个文件哪里不一样", {"diff"}),
    ("改一下文件权限", {"chmod"}),
    ("这个文件什么时候改的", {"stat", "ls"}),
    ("这个文件是什么类型", {"file"}),
    ("这个命令装在哪儿", {"which"}),
    ("建个软链接", {"ln"}),
    ("网卡的 IP 是多少", {"ip"}),
    ("路由表长什么样", {"ip"}),
    ("网络通不通", {"ping"}),
    ("这个网站还活着吗", {"curl", "ping"}),
    ("下载个文件", {"curl"}),
    ("把这堆文件打个包", {"tar"}),
    ("解开这个压缩包", {"tar"}),
    ("看看代码的提交历史", {"git"}),
    ("装个 Python 包", {"pip"}),
    ("把那个进程杀掉", {"pkill", "kill"}),
    ("USB 设备认到没有", {"lsusb"}),
    ("显卡用的什么驱动", {"lspci"}),
    # —— 2026-10-06 第二批（文本处理/传输/校验/硬件/开机）——
    ("把文件里的旧字样替换掉", {"sed"}),
    ("按列取出第二列", {"awk", "cut"}),
    ("把第三列大于 100 的行筛出来", {"awk"}),
    ("一批文件逐个处理", {"xargs"}),
    ("一边跑一边存到文件", {"tee"}),
    ("看看这个 JSON 里的字段", {"jq"}),
    ("每隔两秒刷一次", {"watch"}),
    ("把文件传到那台机器上", {"scp", "rsync"}),
    ("两个目录同步一下", {"rsync"}),
    ("算一下这个文件的指纹", {"md5sum", "sha256sum"}),
    ("校验下载的文件有没有坏", {"md5sum", "sha256sum"}),
    ("列出这台机器的硬件清单", {"lshw"}),
    ("开机花了多久", {"systemd-analyze", "uptime"}),
    ("这个端口开着吗", {"nc", "ss"}),
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
    table = linux_retrieve.load_or_build(index_path, items)
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
        vec_scores = linux_retrieve.vector_scores_of(
            matrix, rag_search.embed_query(query, config, model_info))
        inv_scores = linux_retrieve.bm25_scores(table, query)
        rrf_scores = linux_retrieve.merge_rrf(
            [linux_retrieve.rank_of(vec_scores), linux_retrieve.rank_of(inv_scores)], len(items))
        weighted = linux_retrieve.merge_weight([vec_scores, inv_scores], ALPHA)

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

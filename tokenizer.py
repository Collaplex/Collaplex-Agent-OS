#!/usr/bin/env python3
"""DeepSeek V4 那份 tokenizer.json 的纯 stdlib 复刻 —— 离线精确计算 token 数, 不引入新依赖.

为什么自己写一份
    requirements.txt 只有三个依赖(openai / dotenv / numpy)。为了计算 token 去引入 tokenizers
    (Rust 轮子) 或 transformers 不划算 —— 这份只用 json / re / unicodedata / functools。
    实测与 tokenizers 库**逐 id 完全一致**(对拍真值记在 tests/test_tokenizer.py 里)。

它认的是哪种 tokenizer.json
    normalizer 空 -> Split(数字 1~3) -> Split(中日韩连片) -> Split(主体正则, Llama3 那套)
    -> ByteLevel(按字节映射成可打印字符) -> BPE(127,741 条合并)。
    ★ 换别家 tokenizer 不能直接使用, 要先重跑对拍 —— 别家的 pre_tokenizer 流水线不一样。

装载代价
    约 1~2 秒(读 6.4MB json + 扫一遍 Unicode 分类拼字符类)。所以**首次真正用到才装**:
    sub_agent 只是 import 本模块, 不数 token 就不付这个钱。

词表来源(配置外置, 不硬编码)
    ① 环境变量 COLLAPLEX_TOKENIZER_JSON
    ② config/tokenizer.json 的 tokenizer_path
    ③ 兜底候选 ~/models/deepseek-v4-tokenizer/tokenizer.json
    一个都找不到 -> count() 返回 None, 调用方自己退回粗估(见 sub_agent.estimate_tokens)。
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

# 项目根与配置(本文件就在项目根)
_PROJECT_ROOT = Path(__file__).resolve().parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "tokenizer.json"
_FALLBACK_VOCAB = Path.home() / "models" / "deepseek-v4-tokenizer" / "tokenizer.json"


def _bytes_to_unicode() -> dict[int, str]:
    """GPT-2 那套"字节 -> 可打印字符"映射(ByteLevel 预处理要用).

    256 个字节里, 可打印的照原样, 其余的往后顺延到 256+ 的私有区间 —— 这样每个字节
    都能用一个可见字符表示, BPE 才好在字节序列上做合并。
    """
    base = list(range(0x21, 0x7F)) + list(range(0xA1, 0xAD)) + list(range(0xAE, 0x100))
    chars = base[:]
    n = 0
    for byte in range(256):
        if byte not in base:
            base.append(byte)
            chars.append(256 + n)
            n += 1
    return {byte: chr(char) for byte, char in zip(base, chars)}


@lru_cache(maxsize=1)
def _unicode_classes() -> dict[str, str]:
    """把 \\p{L} / \\p{M} / \\p{P} / \\p{S} / \\p{N} 算成 re 吃得下的字符类(区间串).

    Python 的 re 不认 \\p{...}; 为了不再引入 regex 包, 改为按 unicodedata 扫一遍码点,
    把同类码点拼成区间。一次约 0.6 秒, 进程内只算一次。
    """
    wanted = ("L", "M", "P", "S", "N")
    spans: dict[str, list[tuple[int, int]]] = {key: [] for key in wanted}
    prev = ""
    start = 0
    for cp in range(0x110000):
        head = unicodedata.category(chr(cp))[:1]
        if head != prev:
            if prev in spans:
                spans[prev].append((start, cp - 1))
            start = cp
            prev = head
    if prev in spans:
        spans[prev].append((start, 0x10FFFF))
    out: dict[str, str] = {}
    for key, items in spans.items():
        parts: list[str] = []
        for lo, hi in items:
            parts.append(re.escape(chr(lo)) + ("" if lo == hi else "-" + re.escape(chr(hi))))
        out[key] = "".join(parts)
    return out


class Tokenizer:
    """读一份 tokenizer.json, 复刻 tokenizers 库的 encode 结果."""

    def __init__(self, path: str | Path) -> None:
        raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        model: dict[str, Any] = raw["model"]
        vocab = cast(dict[str, int], model["vocab"])
        merges = cast(list[str], model["merges"])
        added = cast(list[dict[str, Any]], raw.get("added_tokens", []))

        self.vocab: dict[str, int] = vocab
        self.ranks: dict[tuple[str, str], int] = {}
        for rank, pair in enumerate(merges):
            left, _, right = pair.partition(" ")
            self.ranks[(left, right)] = rank
        self.byte_map: dict[int, str] = _bytes_to_unicode()

        # 特殊 token(added_tokens) 不参与 BPE —— 整串切出来就是一个 id。按长度倒序 = 最长优先
        self.special_ids: dict[str, int] = {item["content"]: item["id"] for item in added}
        specials = sorted(self.special_ids, key=len, reverse=True)
        self._special_re: re.Pattern[str] | None = (
            re.compile("|".join(re.escape(item) for item in specials)) if specials else None
        )

        # 三级 Split(都是 Isolated: 命中段与空隙各自成块) + 最后的 ByteLevel
        classes = _unicode_classes()
        self._re_digits = re.compile(f"[{classes['N']}]{{1,3}}")
        self._re_cjk = re.compile(r"[一-龥぀-ゟ゠-ヿ]+")
        self._re_main = re.compile(
            r"""[!"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~][A-Za-z]+"""
            r"""|[^\r\n""" + classes["L"] + classes["P"] + classes["S"] + r"""]?["""
            + classes["L"] + classes["M"] + r"""]+"""
            r"""| ?[""" + classes["P"] + classes["S"] + r"""]+[\r\n]*"""
            r"""|\s*[\r\n]+|\s+(?!\S)|\s+"""
        )

    # ---------- 预处理 ----------

    @staticmethod
    def _split_isolated(pieces: list[str], pattern: re.Pattern[str]) -> list[str]:
        """Isolated 切法: 命中段各自成块, 命中与命中之间的空隙也各自成块."""
        out: list[str] = []
        for piece in pieces:
            cursor = 0
            for hit in pattern.finditer(piece):
                if hit.start() > cursor:
                    out.append(piece[cursor : hit.start()])
                out.append(hit.group(0))
                cursor = hit.end()
            if cursor < len(piece):
                out.append(piece[cursor:])
        return out

    def _to_bytes(self, pieces: list[str]) -> list[str]:
        return ["".join(self.byte_map[b] for b in piece.encode("utf-8")) for piece in pieces]

    def pretokenize(self, text: str) -> list[str]:
        """走完三级 Split + ByteLevel, 得到喂给 BPE 的块."""
        pieces = [text]
        pieces = self._split_isolated(pieces, self._re_digits)
        pieces = self._split_isolated(pieces, self._re_cjk)
        pieces = self._split_isolated(pieces, self._re_main)
        return self._to_bytes(pieces)

    # ---------- BPE ----------

    @lru_cache(maxsize=200_000)
    def _bpe(self, piece: str) -> tuple[int, ...]:
        """对一个块做 BPE: 每轮合并"排名最靠前的那一对", 直到没有可合并的."""
        symbols = list(piece)
        if len(symbols) < 2:
            one = self.vocab.get(symbols[0]) if symbols else None
            return () if one is None else (one,)
        while True:
            best_pair: tuple[str, str] | None = None
            best_at = -1
            best_rank = len(self.ranks) + 1
            for i in range(len(symbols) - 1):
                pair = (symbols[i], symbols[i + 1])
                rank = self.ranks.get(pair, -1)
                if rank != -1 and rank < best_rank:
                    best_rank = rank
                    best_pair = pair
                    best_at = i
            if best_pair is None:
                break
            symbols[best_at : best_at + 2] = [best_pair[0] + best_pair[1]]
        return tuple(self.vocab[item] for item in symbols if item in self.vocab)

    # ---------- 对外 ----------

    def encode(self, text: str) -> list[int]:
        """文本 -> id 序列(与 tokenizers 库逐 id 一致)."""
        ids: list[int] = []
        cursor = 0
        if self._special_re is not None:
            for hit in self._special_re.finditer(text):
                if hit.start() > cursor:
                    ids.extend(self._encode_plain(text[cursor : hit.start()]))
                ids.append(self.special_ids[hit.group(0)])
                cursor = hit.end()
        if cursor < len(text):
            ids.extend(self._encode_plain(text[cursor:]))
        return ids

    def _encode_plain(self, text: str) -> list[int]:
        out: list[int] = []
        for piece in self.pretokenize(text):
            out.extend(self._bpe(piece))
        return out

    def count(self, text: str) -> int:
        """数 token —— 这就是本地能给的精确值."""
        return len(self.encode(text))


def vocab_path() -> Path | None:
    """按 环境变量 -> 配置 -> 兜底候选 的顺序找词表文件; 都没有返回 None."""
    env = os.environ.get("COLLAPLEX_TOKENIZER_JSON")
    if env:
        candidate = Path(env).expanduser()
        if candidate.is_file():
            return candidate
    if _CONFIG_PATH.is_file():
        try:
            conf: dict[str, Any] = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            conf = {}
        configured = conf.get("tokenizer_path")
        if isinstance(configured, str) and configured:
            candidate = Path(configured).expanduser()
            if candidate.is_file():
                return candidate
    return _FALLBACK_VOCAB if _FALLBACK_VOCAB.is_file() else None


# 进程内单例 —— 名字用小写: 它们要被重新赋值, 大写会被 pyright 当常量(reportConstantRedefinition)
_cached_instance: Tokenizer | None = None
_load_attempted = False


def load(path: str | Path | None = None) -> Tokenizer | None:
    """拿词表实例(进程内单例). 找不到词表 / 读崩 都返回 None, 不抛."""
    global _cached_instance, _load_attempted
    if _cached_instance is not None:
        return _cached_instance
    if _load_attempted:
        return None
    _load_attempted = True
    target = Path(path).expanduser() if path else vocab_path()
    if target is None or not target.is_file():
        return None
    try:
        _cached_instance = Tokenizer(target)
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        _cached_instance = None
    return _cached_instance


def reset() -> None:
    """清掉进程内单例(测试与"换了词表想重装"用)."""
    global _cached_instance, _load_attempted
    _cached_instance = None
    _load_attempted = False


def count(text: str) -> int | None:
    """数 token; 没词表就返回 None(调用方自己兜底)."""
    machine = load()
    if machine is None:
        return None
    return machine.count(text)


def encode(text: str) -> list[int] | None:
    """文本 -> id 序列; 没词表返回 None."""
    machine = load()
    if machine is None:
        return None
    return machine.encode(text)


if __name__ == "__main__":
    import sys
    import time

    started = time.perf_counter()
    counter = load()
    if counter is None:
        print("没找到词表 —— 配 config/tokenizer.json 的 tokenizer_path, 或设 COLLAPLEX_TOKENIZER_JSON")
        raise SystemExit(1)
    print(f"装载 {time.perf_counter() - started:.2f}s | 词表 {len(counter.vocab)} | 合并 {len(counter.ranks)}")
    for sample in sys.argv[1:] or ["报告一下当前目录有几个 .py 文件。"]:
        print(f"  {counter.count(sample):>6} token  {sample[:48]!r}")

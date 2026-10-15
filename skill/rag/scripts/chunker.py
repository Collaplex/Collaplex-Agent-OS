import ast
import math
import os
import re
import statistics
import sys
from typing import Callable


# ============================================================
# 通用工具
# ============================================================
# ★ 切片出的每一块都必须是**原文的连续子串**(text[起:止]), 不许用 "".join(片段) 重新拼。
#   拼 = 把原文重打一遍: 切句时句末标点后的 \s* 连同片段两端的 strip, 一起把换行/空行吞掉了,
#   拼回来段落会黏成一团(实测 15 个 md 丢 11 个空行 —— 逐字内容没丢, 段落全平了)。
#   各条路一律: 记住用到的片段在原文里的 (起, 止), 块 = text[首片起 : 末片止] —— 片段**之间**
#   的空白因此原样留在块里, 块与块首尾相接(带重叠)正好铺满原文。

_SENTENCE_END = "。！？.!?"


def _emit(text: str, spans: list[tuple[int, int, int]]) -> str:
    """把攒下的一串片段收成一个块: 逐字节是 text 的子串, 片段之间的空白原样保留。

    span = (起, 正文止, 尾巴止) —— 尾巴止 = 下一片的起点。于是块与块首尾严丝合缝,
    段间/句间/轮间那些空行不会掉在块边界的缝里。
    """
    return text[spans[0][0]:spans[-1][2]]


def _trim_right(text: str, start: int, end: int) -> int:
    """把区间右端的空白收掉 —— 等价于旧写法里的 .strip() 右半边。"""
    while end > start and text[end - 1].isspace():
        end -= 1
    return end


def _line_offsets(text: str) -> list[int]:
    """每一行的起始偏移, 末尾多一个 = len(text)。"""
    offsets: list[int] = []
    at = 0
    for line in text.splitlines(keepends=True):
        offsets.append(at)
        at += len(line)
    offsets.append(at)
    return offsets


def _补尾巴(text: str, 正文: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """给每一片补上"尾巴止"(= 下一片的起点): 片与片之间的空白因此有主, 块与块严丝合缝。"""
    return [
        (begin, finish, 正文[序 + 1][0] if 序 + 1 < len(正文) else len(text))
        for 序, (begin, finish) in enumerate(正文)
    ]


def _sentence_spans(text: str) -> list[tuple[int, int, int]]:
    """句子的 (起, 正文止, 尾巴止): 正文止在句末标点之后, 尾巴吃到下一句开头。"""
    cores: list[tuple[int, int]] = []
    start: int | None = None
    for at, char in enumerate(text):
        if char.isspace():
            continue
        if start is None:
            start = at
        if char in _SENTENCE_END:
            cores.append((start, at + 1))
            start = None
    if start is not None:
        cores.append((start, _trim_right(text, start, len(text))))
    return _补尾巴(text, cores)


def _paragraph_spans(text: str) -> list[tuple[int, int, int]]:
    """段落的 (起, 正文止, 尾巴止): 段落 = 非空行连成的一段; 尾巴吃到下一段开头。"""
    cores: list[tuple[int, int]] = []
    start: int | None = None
    previous_end = 0
    at = 0
    for line in text.splitlines(keepends=True):
        at += len(line)
        if line.strip():
            if start is None:
                start = at - len(line)
        elif start is not None:
            cores.append((start, previous_end))
            start = None
        previous_end = at
    if start is not None:
        cores.append((start, at))
    return _补尾巴(text, cores)


def _split_long_text(
    text: str,
    chunk_size: int = 800,
    overlap_sentences: int = 1,
) -> list[str]:
    """兜底: 按句子切, 再合并成块, 块之间保留 1 句重叠。出的块是原文的连续子串。"""
    if isinstance(chunk_size, bool) or chunk_size <= 0:
        raise ValueError("chunk_size 必须为一个正整数")
    if isinstance(overlap_sentences, bool) or overlap_sentences < 0:
        raise ValueError("overlap_sentences 必须为非负整数")

    spans = _sentence_spans(text)
    if not spans:
        return [text] if text.strip() else []

    blocks: list[list[tuple[int, int, int]]] = []
    current: list[tuple[int, int, int]] = []
    current_len = 0

    for span in spans:
        size = span[1] - span[0]
        if current_len + size > chunk_size and current:
            blocks.append(current)
            current = current[-overlap_sentences:] if overlap_sentences > 0 else []
            current_len = sum(part[1] - part[0] for part in current)
        current.append(span)
        current_len += size

    if current:
        blocks.append(current)
    # ★ 首块从 0 起 —— 句子区间是从第一个非空白字符开始的, 不补的话块首那点空白会掉在缝里
    return [
        text[0 if 序 == 0 else block[0][0]:block[-1][2]]
        for 序, block in enumerate(blocks)
    ]


# ============================================================
# Markdown 切片：按标题 + 代码块状态机
# ============================================================

def _split_markdown(text: str, chunk_size: int = 800) -> list[str]:
    """按标题 + 代码块状态机切。出的每块都是原文的一段(不再 strip 掉段首段尾的空白)。"""
    lines = text.splitlines(keepends=True)
    offsets = _line_offsets(text)
    chunks: list[str] = []

    start: int | None = None      # 手上攒的块在原文里的起点; None = 手上没东西
    end = 0                       # 块终点(不含)
    in_code_block = False
    code_fence: str | None = None
    code_start = 0

    def flush() -> None:
        """把手上攒的收成一个块, 太长就再切。"""
        nonlocal start, end
        if start is None:
            return
        block = text[start:end]
        if not block.strip():
            # ★ 纯空白不单独成块, 也不许丢掉 —— 留着跟下一块走, 否则块边界上会漏一个空行
            return
        start = None
        end = 0
        if len(block.strip()) > chunk_size:
            chunks.extend(_split_long_text(block, chunk_size))
        else:
            chunks.append(block)

    def 收行(at: int) -> None:
        """把第 at 行收进手上这一块(标题 / 围栏 / 普通行都走这句)。"""
        nonlocal start, end
        if start is None:
            start = offsets[at]
        end = offsets[at + 1]

    for at, line in enumerate(lines):
        stripped = line.lstrip()

        # ---------- 代码块状态 ----------
        if not in_code_block:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                flush()
                in_code_block = True
                code_fence = stripped[:3]
                code_start = offsets[at]
                收行(at)
                continue
        else:
            收行(at)
            if code_fence is not None and stripped.startswith(code_fence):
                begin = start if start is not None else code_start
                block = text[begin:offsets[at + 1]]
                body = block.strip()
                start = None
                end = 0
                in_code_block = False
                code_fence = None
                if body:
                    if len(body) > chunk_size * 2:
                        # 超长代码块(一整段命令输出/日志)必须切: 否则整块超嵌入窗口被静默截断
                        chunks.extend(_split_code_lines(body, chunk_size))
                    else:
                        chunks.append(block)
            continue

        # ---------- 标题状态 ----------
        if stripped.startswith("#"):
            flush()
            收行(at)
            continue

        # ---------- 普通行 ----------
        收行(at)

    flush()
    return chunks


# ============================================================
# Python 切片：按 def / class
# ============================================================

def _split_python(text: str, chunk_size: int = 800) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _split_text(text, chunk_size)

    lines = text.splitlines()
    chunks: list[str] = []

    spans: list[tuple[int, int]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        spans.append((_banner_start(lines, node.lineno - 1), end))

    for start, end in spans:
        code = "\n".join(lines[start:end]).strip()
        if not code:
            continue
        if len(code) > chunk_size:
            chunks.extend(_split_code_lines(code, chunk_size))
        else:
            chunks.append(code)

    top_lines: list[str] = []
    for i, line in enumerate(lines):
        if any(start <= i < end for start, end in spans):
            continue
        top_lines.append(line)
    top_text = "\n".join(top_lines).strip()
    if top_text:
        chunks.insert(0, top_text)

    return chunks


def _banner_start(lines: list[str], def_line: int) -> int:
    """向上吸收紧邻的注释横幅/装饰器, 中间夹一个空行也算. 避免注释被归入顶层块."""
    start = def_line
    probe = def_line
    while probe > 0:
        previous = lines[probe - 1].strip()
        if previous.startswith(("#", "@")):
            probe -= 1
            start = probe
        elif previous == "" and probe >= 2 and lines[probe - 2].strip().startswith(("#", "@")):
            probe -= 1
        else:
            break
    return start


def _split_code_lines(code: str, chunk_size: int) -> list[str]:
    """超长代码按行切, 保住换行. 不能用句子切分, 那会把代码行黏成一片."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in code.splitlines():
        if current and size + len(line) + 1 > chunk_size:
            chunks.append("\n".join(current))
            current = []
            size = 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


# ============================================================
# 纯文本切片：段落 + 句子
# ============================================================

def _split_text(text: str, chunk_size: int = 800) -> list[str]:
    """纯文本按段落攒块(段落 = 非空行连成的一段)。出的块是原文的连续子串。"""
    spans = _paragraph_spans(text)
    chunks: list[str] = []
    current: list[tuple[int, int, int]] = []
    current_len = 0

    for span in spans:
        size = span[1] - span[0]
        # 段间原先会拼上 "\n\n" 两个字符 —— 算长照旧加上, 攒块的决定才跟以前逐字一致
        joined = current_len + 2 + size if current else size
        if joined <= chunk_size:
            current.append(span)
            current_len = joined
            continue
        if current:
            chunks.append(_emit(text, current))
            current = []
            current_len = 0
        if size > chunk_size:
            chunks.extend(_split_long_text(text[span[0]:span[2]], chunk_size))
        else:
            current = [span]
            current_len = size

    if current:
        chunks.append(_emit(text, current))
    return chunks


# ============================================================
# 对话切片：按 说话人 轮次切 (import_hermes_hist.py 导出的语料用这套)
# ============================================================

_DIALOGUE_MARKS: tuple[str, ...] = ("**用户**", "**助手**", "**工具**")


def _looks_like_dialogue(text: str) -> bool:
    """判断是不是导出的对话语料: 整行恰为角色标记的行出现 >= 2 次(有问也有答)。

    ★ 不要只看前 N 行。实测一条 343KB 的附件(整段放进一条消息)就占满前 80 行,
      判据漏判 —— 30 个语料文件漏掉 2 个。漏判的代价很大: 对话会走 markdown 分支,
      切出来的中位长度从 780 字掉到 28 字, 几乎每片都是噪声。
      所以改成全文数标记行。count 是 C 实现, 343KB 全文数一遍也是微秒级, 不用采样。
      前后补 \n 是为了让首行/末行也能被"行边界"匹配上(否则首行永远数不到)。
    """
    样本 = "\n" + text + "\n"
    return sum(
        样本.count(f"\n{标记}\n") + 样本.count(f"\n{标记}\r\n")
        for 标记 in _DIALOGUE_MARKS
    ) >= 2


def _dialogue_turn_spans(text: str) -> list[tuple[int, int, int]]:
    """轮次的 (起, 正文止, 尾巴止): 按角色标记行切, 轮尾空白算进这一轮的尾巴。"""
    offsets = _line_offsets(text)
    cores: list[tuple[int, int]] = []
    start = 0
    for at, line in enumerate(text.splitlines(keepends=True)):
        if line.strip() in _DIALOGUE_MARKS:
            cores.append((start, _trim_right(text, start, offsets[at])))
            start = offsets[at]
    cores.append((start, _trim_right(text, start, len(text))))
    cores = [
        (begin, finish)
        for begin, finish in cores
        if begin < finish and text[begin:finish].strip()
    ]
    return _补尾巴(text, cores)


def _dialogue_turns(text: str) -> list[str]:
    """按角色标记切出轮次 —— 对话语料的原子单元(切片的输入)。"""
    return [text[begin:finish] for begin, finish, _ in _dialogue_turn_spans(text)]


def _split_dialogue(
    text: str,
    chunk_size: int = 800,
    hard_max: int | None = None,
    min_chunk: int = 0,
) -> list[str]:
    """对话切片: **一问一答为一个单元**, 太长的按句拆、太短的并到相邻单元。

    为什么是一问一答(老板定的): 检索单元就是"一组问答" —— 搜到问题就该带出答案。
    所以断点只认"新问题"(`**用户**`), 中间跟着的 `**助手**`/`**工具**` 都算这一对的答案,
    多轮工具调用不会被拆开。

    两个兜底:
      - 太长的对(> hard_max): 按句拆, 每块补上"谁说的"保住上下文;
      - 太短的对(< min_chunk): 往相邻的并 —— 否则"现在几点了"这种 5 字的会单独成片,
        检索时是纯噪声(实测 1,789 条里有 83% 是这种)。
    """
    limit = hard_max if hard_max is not None else chunk_size * 2
    spans = _dialogue_turn_spans(text)

    chunks: list[str] = []
    buffer: list[tuple[int, int, int]] = []
    buffer_len = 0
    for span in spans:
        size = span[1] - span[0]
        speaker = next((mark for mark in _DIALOGUE_MARKS if text.startswith(mark, span[0])), "")
        是新问题 = speaker == _DIALOGUE_MARKS[0]  # "**用户**"
        if size > limit:
            # 超长的一轮: 先收掉手上的, 再按句拆开
            if buffer:
                chunks.append(_emit(text, buffer))
                buffer = []
                buffer_len = 0
            拆开 = _split_turn(text[span[0]:span[2]], chunk_size, speaker)
            if 拆开 and text[span[1]:span[2]]:
                # ★ 轮尾的空行接回最后一块 —— 否则下一轮的开头会在缝上丢一截空白
                拆开[-1] = 拆开[-1] + text[span[1]:span[2]]
            chunks.extend(拆开)
        elif 是新问题 and buffer and buffer_len >= min_chunk:
            # 攒够了 + 来了新问题: 断在这里, 一问一答自成一单元
            chunks.append(_emit(text, buffer))
            buffer = [span]
            buffer_len = size
        else:
            # 其余一律攒进当前这一对(含"**助手**"/"**工具**")
            # ★ 断点只认"新问题": 若在"助手"处断, 下一片就从答案开头, 丢了它答的是哪个问题
            buffer_len = (buffer_len + 2 + size) if buffer else size
            buffer.append(span)
    if buffer:
        chunks.append(_emit(text, buffer))
    return chunks


def _split_turn(turn: str, chunk_size: int, speaker: str) -> list[str]:
    """一个超长轮次按句切; 单句仍超长(无标点)按字符硬切。每块补上说话人。"""
    chunks: list[str] = []
    for piece in _split_long_text(turn, chunk_size):
        body = piece.strip()
        if not body:
            continue
        while len(body) > chunk_size * 2:
            chunks.append(f"{speaker}\n\n{body[:chunk_size]}" if speaker else body[:chunk_size])
            body = body[chunk_size:]
        if body:
            chunks.append(f"{speaker}\n\n{body}" if speaker else body)
    return chunks


# ============================================================
# 语义切片: 用嵌入模型找话题边界 (长文本用)
# ============================================================

def _cosine(left: list[float], right: list[float]) -> float:
    """两个向量的余弦相似度; 有零向量就返回 0。"""
    dot = 0.0
    norm_left = 0.0
    norm_right = 0.0
    for a, b in zip(left, right):
        dot += a * b
        norm_left += a * a
        norm_right += b * b
    if norm_left <= 0.0 or norm_right <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_left) * math.sqrt(norm_right))


def _hard_split(text: str, size: int) -> list[str]:
    """无标点长串按字符硬切。"""
    return [text[at:at + size] for at in range(0, len(text), size)]


def semantic_units(text: str, max_unit: int) -> list[str]:
    """拆成"语义单元": 句子为粒度(中英句读/空行都能断), 超长单元硬切。"""
    pieces = re.split(r'(?<=[。！？!?；;])\s*|\n{2,}', text)
    units: list[str] = []
    for piece in pieces:
        body = piece.strip()
        if not body:
            continue
        if len(body) > max_unit:
            units.extend(_hard_split(body, max_unit))
        else:
            units.append(body)
    return units


def _similarity_threshold(sims: list[float], fixed: float, zscore: float) -> float:
    """语义切点阈值。

    zscore > 0 时按**这个文件自己的**相似度分布自适应 (均值 - z*标准差):
    实测各语料均值在 0.47~0.61 之间浮动, 用拍死的绝对值要么处处断、要么处处不断。
    zscore <= 0 时退回固定阈值 fixed。
    """
    if zscore <= 0.0 or len(sims) < 3:
        return fixed
    mean = statistics.fmean(sims)
    spread = statistics.pstdev(sims)
    return min(1.0, max(0.0, mean - zscore * spread))


def _group_by_similarity(
    units: list[str],
    embed_fn: Callable[[list[str]], list[list[float]]],
    cut_threshold: float,
    cut_zscore: float,
    min_chunk: int,
    max_chunk: int,
) -> list[tuple[str, list[float] | None]]:
    """把单元按"相邻余弦骤降处断开"攒成块 —— 对话和长文本共用同一套攒块逻辑。"""
    if len(units) < 2:
        body = units[0].strip() if units else ""
        return [(body, None)] if body else []

    vectors = embed_fn(units)
    if len(vectors) != len(units):
        print(f"[语义] 返回向量数 {len(vectors)} != 单元数 {len(units)}, 退回规则切片", file=sys.stderr)
        return []

    sims = [_cosine(vectors[at], vectors[at + 1]) for at in range(len(vectors) - 1)]
    threshold = _similarity_threshold(sims, cut_threshold, cut_zscore)
    cuts = sum(1 for value in sims if value < threshold)
    print(f"[语义] {len(units)} 个单元, 相邻相似度 {statistics.fmean(sims):.3f}"
          f"±{statistics.pstdev(sims):.3f}, 切点阈值 {threshold:.3f} (低相似接缝 {cuts} 处)")

    groups: list[list[int]] = []
    current: list[int] = [0]
    size = len(units[0])
    for position in range(1, len(units)):
        addition = len(units[position]) + 1
        similarity = sims[position - 1]
        # ★ 切点只认语义(相似度骤降) + 硬上限;
        #   早先把"到了目标字数"也当切点, 结果单元平均 536 字、目标 800 字 → 几乎每两轮
        #   就撞字数上限, 断点全由字数决定(实测断开处相似度反而更高 = 信号被淹没)。
        over_ceiling = size + addition > max_chunk
        if (size >= min_chunk and similarity < threshold) or over_ceiling:
            groups.append(current)
            current = [position]
            size = len(units[position])
        else:
            current.append(position)
            size += addition
    groups.append(current)

    chunks: list[tuple[str, list[float] | None]] = []
    for group in groups:
        body = "\n".join(units[position] for position in group).strip()
        if not body:
            continue
        chunks.append((body, vectors[group[0]] if len(group) == 1 else None))
    return chunks


def split_semantic(
    text: str,
    chunk_size: int = 800,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    *,
    cut_threshold: float = 0.62,
    cut_zscore: float = 0.8,
    min_chunk: int = 0,
    max_chunk: int = 1600,
) -> list[tuple[str, list[float] | None]]:
    """长文本语义切片: 句子单元嵌入 -> 相邻余弦 -> 骤降处断成一块。

    和按句号/字数切的分水岭: 断点落在"话题换了"的地方, 不是"字数够了"的地方。
    切点阈值默认按本文档的相似度分布自适应 (cut_zscore), cut_threshold 只在
    cut_zscore<=0 时当固定阈值用。
    代价是先算一遍单元向量 —— 只含一个单元的块把它那条向量带出去, 上层不必重算。

    返回 [(块文本, 单元向量 or None)]。
    """
    if embed_fn is None or not text.strip():
        return [(chunk, None) for chunk in _split_text(text, chunk_size)]
    if isinstance(cut_threshold, bool) or not 0.0 <= cut_threshold <= 1.0:
        raise ValueError("cut_threshold 必须落在 0~1 之间")

    units = semantic_units(text, max(chunk_size, max_chunk))
    chunks = _group_by_similarity(
        units, embed_fn, cut_threshold, cut_zscore, min_chunk, max_chunk,
    )
    if not chunks:
        return [(chunk, None) for chunk in _split_text(text, chunk_size)]
    return chunks


def dialogue_units(text: str, chunk_size: int = 800, max_chunk: int = 1600) -> list[str]:
    """对话切片的原子单元: 正常轮次原样; 超长轮次(> max_chunk)按句拆开并补上说话人。"""
    units: list[str] = []
    for turn in _dialogue_turns(text):
        if len(turn) > max_chunk:
            speaker = next((mark for mark in _DIALOGUE_MARKS if turn.startswith(mark)), "")
            units.extend(_split_turn(turn, chunk_size, speaker))
        else:
            units.append(turn)
    return units


def split_dialogue_semantic(
    text: str,
    chunk_size: int = 800,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    *,
    cut_threshold: float = 0.62,
    cut_zscore: float = 0.8,
    min_chunk: int = 0,
    max_chunk: int = 1600,
) -> list[tuple[str, list[float] | None]]:
    """对话切片: **一问一答为一个单元**(老板定的), 不按语义断。

    原先这里按"话题变才断"用嵌入找边界。改成按问答对了, 因为对话的天然检索单元
    就是"一组问答" —— 搜到问题就该带出答案, 而这个边界不需要模型猜, 标记里明摆着。

    函数名保留(调用方是 split_file_semantic), embed_fn 参数也留着不删, 以免改签名
    牵动调用处; 现在不再用它。

    两个兜底在 _split_dialogue 里: 太长的对按句拆、太短的对并到相邻单元
    (min_chunk 就是"短于多少要并", 由配置的 min_chunk_ratio 算出来)。
    """
    del embed_fn, cut_threshold, cut_zscore  # 一问一答不需要猜话题边界了
    return [(chunk, None) for chunk in _split_dialogue(text, chunk_size, max_chunk, min_chunk)]


# ============================================================
# 入口：根据后缀路由
# ============================================================

def split_rules(text: str, extension: str, chunk_size: int = 800) -> list[str]:
    """规则路由: 对话按轮次, 代码按 def/class, md 按标题, 其余按段+句。"""
    if extension in (".md", ".markdown"):
        if _looks_like_dialogue(text):
            return _split_dialogue(text, chunk_size)
        return _split_markdown(text, chunk_size)
    if extension == ".py":
        return _split_python(text, chunk_size)
    if extension in (".txt", ".log", ".rst", ".csv"):
        if _looks_like_dialogue(text):
            return _split_dialogue(text, chunk_size)
        return _split_text(text, chunk_size)
    if _looks_like_dialogue(text):
        return _split_dialogue(text, chunk_size)
    return _split_text(text, chunk_size)


def split_text(text: str, chunk_size: int = 800) -> list[str]:
    """纯文本 -> 切片（网页正文、临时串这类没有文件后缀的走这条）.

    split_file 是按后缀选算法的, 网页正文拿不到后缀 —— 但它就是普通散文, 走 _split_text。
    """
    if isinstance(chunk_size, bool) or chunk_size <= 0:
        raise ValueError("chunk_size 必须为一个正整数")
    return _split_text(text, chunk_size)


def split_file(filepath: str, chunk_size: int = 800) -> list[str]:
    """
    读取文件, 根据后缀选择规则切片算法, 返回字符串列表。

    参数:
        filepath:   文件路径
        chunk_size: 目标块大小 (字符数, 默认 800)

    返回:
        list[str], 每个元素是一个切片
    """
    if isinstance(chunk_size, bool) or chunk_size <= 0:
        raise ValueError("chunk_size 必须为一个正整数")
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"文件不存在: {filepath}")

    extension = os.path.splitext(filepath)[1].lower()
    with open(filepath, "r", encoding="utf-8") as file:
        text = file.read()
    return split_rules(text, extension, chunk_size)


def split_file_semantic(
    filepath: str,
    chunk_size: int = 800,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    *,
    cut_threshold: float = 0.62,
    cut_zscore: float = 0.8,
    min_ratio: float = 0.35,
    max_ratio: float = 2.0,
    min_text_chars: int = 1600,
    force: bool = False,
) -> list[tuple[str, list[float] | None]]:
    """按后缀路由: 对话/代码/短文本照旧走规则, 长文本走语义切片。

    返回 [(块文本, 单元向量 or None)] —— 向量那一项是给上层省一次嵌入的。
    """
    if isinstance(chunk_size, bool) or chunk_size <= 0:
        raise ValueError("chunk_size 必须为一个正整数")
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"文件不存在: {filepath}")

    extension = os.path.splitext(filepath)[1].lower()
    with open(filepath, "r", encoding="utf-8") as file:
        text = file.read()

    structured = _looks_like_dialogue(text) or extension == ".py" or len(text) < min_text_chars
    if not force and structured:
        if _looks_like_dialogue(text) and len(text) >= min_text_chars:
            # 对话语料单独一套: 一问一答为一个单元(不需要嵌入器)
            return split_dialogue_semantic(
                text,
                chunk_size,
                embed_fn,
                min_chunk=int(chunk_size * min_ratio),
                max_chunk=int(chunk_size * max_ratio),
            )
        return [(chunk, None) for chunk in split_rules(text, extension, chunk_size)]

    return split_semantic(
        text,
        chunk_size,
        embed_fn,
        cut_threshold=cut_threshold,
        cut_zscore=cut_zscore,
        min_chunk=int(chunk_size * min_ratio),
        max_chunk=int(chunk_size * max_ratio),
    )


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "skill/seek/SKILL.md"
    chunks = split_file(target)

    print(f"一共 {len(chunks)} 块")
    for i, c in enumerate(chunks):
        print(f"--- 第 {i} 块 ---")
        print(c[:100])   # 只打印前 100 字看看
        print()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""算 token —— 离线精确数(拿本地那份 tokenizer.json, 不花钱不联网).

用法
    算token.py 文件 [文件 ...]                    每份文件多少 token
    算token.py --文本 "一段文字"                   数一段文本(可给多次)
    算token.py --目录 skill/rag [--后缀 .md,.py]   目录里按后缀扫一遍(默认不递归)
    算token.py --在线 --文本 "..."                 打一次 API 对一下 prompt_tokens(花钱, 一两分钱)
选项
    --明细            连字符数 / 每 token 几个字符 一起给
    --上限 N          超过 N 的标 ⚠(用于监控"这块塞不进预算")
    --递归            跟 --目录 搭配: 钻进子目录
    --排序 大小|名字   跟 --目录 搭配
    --json            机器可读
    --词表 路径        临时换一份词表(默认读 config/tokenizer.json)

为什么要它: 项目里拼上下文的预算(sub_agent)原来只能"一字符一 token"粗估, 现在能数准。
本地数出来的值 + 4 = 线上 API 报的 prompt_tokens(单条 user 消息实测, 见 config/tokenizer.json)。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tokenizer  # noqa: E402


def 读配置开销() -> int:
    """config/tokenizer.json 里的"单条 user 消息模板开销"."""
    conf = Path(__file__).resolve().parent / "config" / "tokenizer.json"
    if not conf.is_file():
        return 0
    try:
        data: dict[str, object] = json.loads(conf.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    value = data.get("single_user_message_overhead")
    return value if isinstance(value, int) else 0


def 挑文件(目录: Path, 后缀们: list[str], 递归: bool) -> list[Path]:
    出: list[Path] = []
    候选 = 目录.rglob("*") if 递归 else 目录.glob("*")
    for p in 候选:
        if p.is_file() and (not 后缀们 or p.suffix in 后缀们):
            出.append(p)
    return sorted(出)


def 在线对一下(文本: str, 开销: int) -> int:
    """打一次 API, 看它报的 prompt_tokens 与本地差多少."""
    try:
        import os

        from dotenv import load_dotenv
        from openai import OpenAI
    except ImportError as exc:
        print(f"缺依赖, 对不了线上: {exc}")
        return 2
    load_dotenv(Path(__file__).resolve().parent / ".env")
    base = os.environ.get("EXEC_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or ""
    key = os.environ.get("EXEC_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    model = os.environ.get("EXEC_MODEL") or os.environ.get("OPENAI_MODEL") or ""
    if not (base and key and model):
        print("没配模型(.env 里缺 OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL)")
        return 2
    cli = OpenAI(base_url=base, api_key=key)
    本地 = tokenizer.count(文本)
    try:
        回复 = cli.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": 文本}],
            max_tokens=1,
            extra_body={"thinking": {"type": "disabled"}},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"线上没数成: {type(exc).__name__}: {str(exc)[:160]}")
        return 2
    线上 = 回复.usage.prompt_tokens if 回复.usage else None
    print(f"打给      {base}  模型 {model}")
    print(f"本地数    {本地 if 本地 is not None else '?'} token")
    print(f"线上报    {线上} prompt_tokens")
    if isinstance(线上, int) and isinstance(本地, int):
        print(f"差         {线上 - 本地}(配置里记的模板开销是 {开销})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="算 token(离线, 用本地 tokenizer.json)")
    ap.add_argument("文件们", nargs="*", help="要数的文件")
    ap.add_argument("--文本", action="append", default=[], help="直接数一段文本(可重复)")
    ap.add_argument("--目录", help="扫一个目录")
    ap.add_argument("--后缀", default="", help="跟 --目录 搭配, 如 .md,.py")
    ap.add_argument("--递归", action="store_true", help="跟 --目录 搭配")
    ap.add_argument("--排序", choices=["大小", "名字"], default="大小")
    ap.add_argument("--明细", action="store_true", help="连字符数一起给")
    ap.add_argument("--上限", type=int, default=0, help="超过就标 ⚠")
    ap.add_argument("--在线", action="store_true", help="打一次 API 对比真实 prompt_tokens(花钱)")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--词表", help="临时换一份 tokenizer.json")
    args = ap.parse_args()

    机器 = tokenizer.load(args.词表)
    if 机器 is None:
        print("没找到词表 —— 配 config/tokenizer.json 的 tokenizer_path, 或用 --词表 指定")
        return 1

    if args.在线:
        if not args.文本:
            print("--在线 要配 --文本 一起用")
            return 1
        return 在线对一下(args.文本[0], 读配置开销())

    条目: list[tuple[str, int, int]] = []  # (名字, token, 字符)

    for 文 in args.文本:
        条目.append((文[:32] + ("…" if len(文) > 32 else ""), 机器.count(文), len(文)))

    for 名 in args.文件们:
        p = Path(名).expanduser()
        if not p.is_file():
            print(f"跳过(不是文件): {名}")
            continue
        文 = p.read_text(encoding="utf-8", errors="replace")
        条目.append((str(p), 机器.count(文), len(文)))

    if args.目录:
        后缀们 = [s.strip() for s in args.后缀.split(",") if s.strip()]
        文件们 = 挑文件(Path(args.目录).expanduser(), 后缀们, args.递归)
        if not 文件们:
            print(f"{args.目录} 里没找到" + (f" {'/'.join(后缀们)}" if 后缀们 else "文件"))
            return 1
        for p in 文件们:
            文 = p.read_text(encoding="utf-8", errors="replace")
            条目.append((str(p), 机器.count(文), len(文)))

    if not 条目:
        ap.print_help()
        return 0

    if args.排序 == "大小":
        条目.sort(key=lambda item: -item[1])

    合计 = sum(t for _, t, _ in 条目)

    if args.json:
        print(
            json.dumps(
                {
                    "合计": 合计,
                    "条数": len(条目),
                    "明细": [
                        {"名字": n, "token": t, "字符": c, "每token字符": round(c / t, 2) if t else 0}
                        for n, t, c in 条目
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    宽 = max(len(n) for n, _, _ in 条目)
    for 名, t, c in 条目:
        旗 = "  ⚠ 超上限" if args.上限 and t > args.上限 else ""
        附 = f"  {c:>8} 字符  {c / t:>5.2f} 字符/token" if args.明细 and t else ""
        print(f"{t:>8} token  {名:<{宽}}{附}{旗}")
    print(f"{'-' * 20}")
    print(f"{合计:>8} token  共 {len(条目)} 份" + (f"   (本地数 + {读配置开销()} = 线上 prompt_tokens)" if not args.明细 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

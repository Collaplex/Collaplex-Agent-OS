#!/usr/bin/env python3
"""联网搜索统一入口: 搜(去 bing 拿结果) · 取(真浏览器取一页) · 正文(HTML 去壳留肉).

用法:
    .venv/bin/python skill/search/main.py <动作> [参数...]

例:
    .venv/bin/python skill/search/main.py 搜 "浙江工业职业技术学院 绍兴"
    .venv/bin/python skill/search/main.py 搜 "机器学习 教程" --pages 2 --json
    .venv/bin/python skill/search/main.py 取 "https://www.toutiao.com/"
    .venv/bin/python skill/search/main.py 正文 skill/search/cache/pages/xxxx.html
    .venv/bin/python skill/search/main.py 浏览器 status

实现分三处: serp.py(搜) / browser.py(取, 真浏览器 + 错误分类 + 落盘) / article.py(正文, 去壳留肉);
这里只负责把动作名接上、参数原样递过去 —— 输出不截断、不加工, 退出码原样带回.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent      # skill/search
SCRIPTS = HERE / "scripts"                   # 实现都在这
ROOT = HERE.parent.parent                    # 项目根 (放 .venv)

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))   # 根上的公共件
import path_locator as 件定位   # noqa: E402

# 动作名 -> (脚本文件名, 递进去的第一个参数, 一句话说明); 中英双名
ACTIONS: dict[str, tuple[str, str, str]] = {
    "搜": ("serp.py", "search", "去 bing+百度 拿结果(跨站去重): 标题/链接/摘要/来源; 搜到的自动落热库, 算一次数"),
    "search": ("serp.py", "search", "同上(英文名)"),
    "取": ("browser.py", "fetch", "真浏览器取一页: html + 截图 + 状态码 + 错误分类(超时/HTTPS/具体报错/空页面)"),
    "fetch": ("browser.py", "fetch", "同上(英文名)"),
    "正文": ("article.py", "", "HTML 去壳留肉 -> 标题 + 正文段落(原文不改写); --save --url 可顺手切片落库"),
    "article": ("article.py", "", "同上(英文名)"),
    "浏览器": ("browser.py", "", "管常驻浏览器: start / stop / status(闲置超时看门狗)"),
    "browser": ("browser.py", "", "同上(英文名)"),
    "截图": ("browser.py", "shot", "真浏览器渲染后只截一张整页图: 回截图路径(不解析正文)"),
    "shot": ("browser.py", "shot", "同上(英文名)"),
    "热库": ("corpus.py", "find", "只在热库里回查(只搜热的, 只看热窗口内)"),
    "hot": ("corpus.py", "find", "同上(英文名)"),
    "语料": ("corpus.py", "stats", "看两表: 行数/大小/来源分布/本轮还剩几次"),
    "过期": ("corpus.py", "sink", "把过期的热行沉到冷库(手动跑; 平时靠 cron)"),
    "清理": ("corpus.py", "clean", "冷库过期/超量的删掉, 截图跟着一起清(--dry 只数不删)"),
    "解析": ("serp.py", "parse", "拿存下来的结果页 HTML 离线解析(不出网/不扣数): 查是「被挡/改版」还是「真没有」"),
    "parse": ("serp.py", "parse", "同上(英文名)"),
    "find": ("retrieve.py", "find", "查命令库: 给一句话, 拿回该怎么做(用途/用法/选项/示例/备注)"),
    "index": ("retrieve.py", "index", "建/更新命令库索引(按 hash 复用向量, 不重打模型)"),
}


def python_bin() -> str:
    """优先用项目 venv 的解释器, 没有就用当前解释器."""
    candidate = ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def show_actions() -> None:
    """列出所有可用动作."""
    print("联网搜索可用动作:")
    width = max(len(name) for name in ACTIONS)
    for name, (filename, _sub, note) in ACTIONS.items():
        ready = "" if 件定位.有件(SCRIPTS, filename) else "   [缺文件]"
        print(f"  {name.ljust(width)}  {note}   ({filename}){ready}")
    print("\n跑法: .venv/bin/python skill/search/main.py <动作> [参数...]")


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("list", "help", "-h", "--help"):
        show_actions()
        return 0

    name = args[0]
    rest = args[1:]
    entry = ACTIONS.get(name)
    if entry is None:
        print(f"[错误] 没有这个动作: {name}\n")
        show_actions()
        return 2

    filename, sub, _note = entry
    script = 件定位.件路径(SCRIPTS, filename)
    if script is None:
        print(f"[错误] 实现件不在: {script}", file=sys.stderr)
        return 2

    command = [python_bin(), str(script)]
    if sub:
        command.append(sub)
    command.extend(rest)

    try:
        completed = subprocess.run(command, cwd=ROOT)
    except KeyboardInterrupt:
        return 130
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())

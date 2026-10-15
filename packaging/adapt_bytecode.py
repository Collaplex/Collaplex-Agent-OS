#!/usr/bin/env python3
"""把「按 .py 路径查存在性」的地方改成走 件定位 —— 让源码 / 字节码 / 编译件三形态都能跑。

为什么: 字节码包里 `retrieve.py` 变成了 `retrieve.pyc`, 而代码里写的是
`(SCRIPTS / "retrieve.py").is_file()` → 字节码包里必然报"件不在"（假报错）。

改动**只碰"找件"这一件事**, 不碰任何业务逻辑:
    (SCRIPTS / filename).is_file()   →   件定位.有件(SCRIPTS, filename)
    script = SCRIPTS / filename      →   script = 件定位.件路径(SCRIPTS, filename)
    if not script.is_file():         →   if script is None:
    subprocess.run([py, str(script), …]) →  件定位.跑件(script, […], ROOT, python_bin())

幂等: 已经改过的文件跳过。
"""
from __future__ import annotations

import pathlib
import sys

根 = pathlib.Path(__file__).resolve().parent.parent

技能们 = ["linux", "kali", "ops", "file", "math", "vision", "search", "timer",
        "outsource", "mtp", "rag", "skill_search"]

插入块 = """
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))   # 根上的公共件
import path_locator as 件定位   # noqa: E402
"""

替换对: list[tuple[str, str]] = [
    ('ready = "" if (SCRIPTS / filename).is_file() else "   [缺文件]"',
     'ready = "" if 件定位.有件(SCRIPTS, filename) else "   [缺文件]"'),
    ('    script = SCRIPTS / filename\n    return script if script.is_file() else None',
     '    return 件定位.件路径(SCRIPTS, filename)'),
    ('    script = SCRIPTS / filename\n    if not script.is_file():',
     '    script = 件定位.件路径(SCRIPTS, filename)\n    if script is None:'),
    ('    script = SCRIPTS / filename\n    # ★ 编译版里实现件是编进 exe 的模块，磁盘上本来就没有这个文件 —— 不要把它当缺件挡掉。\n    if not 编译版 and not script.is_file():',
     '    script = 件定位.件路径(SCRIPTS, filename)\n    # ★ 编译版里实现件是编进 exe 的模块，磁盘上本来就没有这个文件 —— 不要把它当缺件挡掉。\n    if not 编译版 and script is None:'),
    ('动作件 = SCRIPTS / "action.py"', '动作件 = 件定位.件路径(SCRIPTS, "action.py")'),
    ('    if not 动作件.is_file():', '    if 动作件 is None:'),
    # 派发: 子进程改成跑件（.py/.pyc 照样子进程; .so 只能进程内导入）
    ('        completed = subprocess.run([python_bin(), str(script), sub, *rest], cwd=ROOT)\n    except KeyboardInterrupt:\n        return 130\n    return completed.returncode',
     '        return 件定位.跑件(script, [sub, *rest], ROOT, python_bin())\n    except KeyboardInterrupt:\n        return 130'),
    ('        completed = subprocess.run([python_bin(), str(script), *rest], cwd=ROOT)\n    except KeyboardInterrupt:\n        return 130\n    return completed.returncode',
     '        return 件定位.跑件(script, rest, ROOT, python_bin())\n    except KeyboardInterrupt:\n        return 130'),
    ('    argv = [python_bin(), str(script)] + ([sub] if sub else []) + rest\n    try:\n        completed = subprocess.run(argv, cwd=ROOT)\n    except KeyboardInterrupt:\n        return 130\n    return completed.returncode',
     '    return 件定位.跑件(script, ([sub] if sub else []) + rest, ROOT, python_bin())'),
]


def 改一个(路径: pathlib.Path) -> str:
    if not 路径.is_file():
        return "文件不在"
    原 = 路径.read_text(encoding="utf-8")
    if "import 件定位" in 原:
        return "已改过, 跳过"
    新 = 原
    for 旧, 再 in 替换对:
        新 = 新.replace(旧, 再)
    # 插入 import（放在 SCRIPTS/ROOT 赋值之后）
    行们 = 新.splitlines(keepends=True)
    位置 = None
    for i, 行 in enumerate(行们):
        if 行.startswith("ROOT = ") or (位置 is None and 行.startswith("SCRIPTS = ")):
            位置 = i
    if 位置 is None:
        return "找不到插入位（没有 SCRIPTS/ROOT 赋值）"
    行们.insert(位置 + 1, 插入块)
    新 = "".join(行们)
    if 新 == 原:
        return "没有可改的点"
    路径.write_text(新, encoding="utf-8")
    return "已改"


def main() -> int:
    报表: list[str] = []
    for 技能 in 技能们:
        路径 = 根 / "skill" / 技能 / "main.py"
        报表.append(f"  {技能:<14} {改一个(路径)}")
    # 自检: 按路径查「件在不在」那处
    自检 = 根 / "selfcheck.py"
    原文 = 自检.read_text(encoding="utf-8")
    旧 = 'gone = [name for name, entry in wanted.items() if not (HERE / entry).is_file()]'
    新文 = 原文.replace(旧, 'gone = [name for name, entry in wanted.items() if 件定位.件路径(HERE, entry) is None]')
    if 新文 != 原文:
        if "import 件定位" not in 新文:
            行们 = 新文.splitlines(keepends=True)
            for i, 行 in enumerate(行们):
                if 行.startswith("HERE = "):
                    行们.insert(i + 1, "\nimport 件定位   # 常见于: 件可能以源码/字节码/编译件三种形态存在\n")
                    break
            新文 = "".join(行们)
        自检.write_text(新文, encoding="utf-8")
        报表.append("  selfcheck.py   已改（件在不在 那处）")
    else:
        报表.append("  selfcheck.py   没有可改的点（或已改过）")

    print("════ 适配结果 ════")
    print("\n".join(报表))

    print("\n════ 复查: 还有哪些地方在按 .py 查存在性 ════")
    剩: list[str] = []
    for 路径 in sorted((根 / "skill").glob("*/main.py")) + [根 / "selfcheck.py", 根 / "cli.py"]:
        for i, 行 in enumerate(路径.read_text(encoding="utf-8").splitlines(), 1):
            if "is_file()" in 行 and ".py" in 行:
                剩.append(f"  {路径.relative_to(根)}:{i}: {行.strip()[:90]}")
    print("\n".join(剩) or "  没有 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""把一个 Python 树"字节码化": 全部 .py → 只留 .pyc（源码一个不留）。

用途: 主 agent 与 skill 想以「方便分发」的形态出货（deb / exe / 解压即用）。
     ★ 这是**分发方便**，不是防看 —— .pyc 里仍有名字与文档串，只是把 .py 收起来。

用法:
    python3 打包/字节码化.py                    # 生成 dist/字节码树/
    python3 打包/字节码化.py --输出 /path/x     # 换落点
    python3 打包/字节码化.py --只验             # 只跑验证, 不重编
    python3 打包/字节码化.py --python /path/py  # 指定编译用的解释器（默认 uv 独立 3.14）

★ 硬约束: .pyc 的魔数跟着 CPython 小版本走。3.14 编的 .pyc 拿到 3.13 上直接
  "bad magic number"。所以编译用的解释器必须与目标机器的是同一小版本,
  清单里会记下版本, 验证环节也会打印。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

项目 = pathlib.Path(__file__).resolve().parent.parent
不收 = [
    "./.venv", "./.git", "./debian", "./dist", "./build-nuitka", "./打包/字节码树",
    "./.env", "./state", "./logs", "./__pycache__", "./vendor", "./实验", "./diagrams",
    "./out", "./skill/rag/corpus", "./skill/rag/scripts/_json-退役备份",
    "./skill/search/logs", "./skill/vision/logs", "./skill/vision/tests/样本",
    "./skill/tools", "./打包", "./tests", "./web/tests",
]
不收后缀 = ["*.log", "*.log.*", "*.crv", "*.restored", "*.pyc", ".carve-backups"]
不收目录名 = ["__pycache__", "cache"]


def 找解释器(指定: str | None) -> pathlib.Path:
    if 指定:
        p = pathlib.Path(指定)
        if p.is_file():
            return p
        raise SystemExit(f"[错误] 指定的解释器不在: {p}")
    自己runtime = 项目 / "dist/collaplex-agent/runtime/python/bin/python3"
    if 自己runtime.is_file():
        return 自己runtime
    家 = pathlib.Path.home() / ".local/share/uv/python"
    for 候 in sorted(家.glob("cpython-3.14*-linux-x86_64-gnu/bin/python3")):
        return 候
    return pathlib.Path(shutil.which("python3") or "/usr/bin/python3")


def 找验证解释器(指定: str | None, 编译用: pathlib.Path) -> tuple[pathlib.Path, str]:
    """验证用的解释器必须**带依赖**(psycopg/numpy/dotenv...)。

    优先级: --验证python > 项目 .venv > 自带运行时 + runtime/deps 走 PYTHONPATH。
    返回 (解释器, PYTHONPATH 补充)。
    """
    if 指定:
        return pathlib.Path(指定), ""
    venv = 项目 / ".venv/bin/python"
    if venv.is_file():
        return venv, ""
    deps = 项目 / "dist/collaplex-agent/runtime/deps"
    if deps.is_dir():
        return 编译用, str(deps)
    return 编译用, ""


def 版本号(解释器: pathlib.Path) -> str:
    return subprocess.run([str(解释器), "-c", "import sys;print('.'.join(map(str,sys.version_info[:3])))"],
                          capture_output=True, text=True).stdout.strip()


def 建树(输出: pathlib.Path) -> None:
    print("═══ 1/4 拷一份源码树（与 deb/pack_bundle 同一套排除口径）═══")
    if 输出.exists():
        shutil.rmtree(输出)
    参数 = ["tar", "-C", str(项目), "-cf", "-"]
    for 项 in 不收:
        参数.append(f"--exclude={项}")
    for 项 in 不收后缀:
        参数.append(f"--exclude={项}")
    for 名 in 不收目录名:
        参数.append(f"--exclude=*/{名}")
    参数.append(".")
    输出.mkdir(parents=True)
    r1 = subprocess.Popen(参数, stdout=subprocess.PIPE)
    r2 = subprocess.run(["tar", "-C", str(输出), "-xf", "-"], stdin=r1.stdout)
    r1.wait()
    if r1.returncode or r2.returncode:
        raise SystemExit("  拷树失败")
    (输出 / "skill/rag/corpus").mkdir(parents=True, exist_ok=True)
    (输出 / "logs").mkdir(exist_ok=True)
    数 = len(list(输出.rglob("*.py")))
    print(f"  源码 {数} 个 .py · 树 {输出}")


def 编字节码(输出: pathlib.Path, 解释器: pathlib.Path) -> dict[str, object]:
    print(f"═══ 2/4 编字节码（{解释器}）═══")
    版本 = subprocess.run([str(解释器), "-c", "import sys;print('.'.join(map(str,sys.version_info[:3])))"],
                        capture_output=True, text=True).stdout.strip()
    print(f"  解释器版本 {版本}  ★ 目标机器必须同一小版本")
    起 = time.perf_counter()
    日志 = subprocess.run([str(解释器), "-m", "compileall", "-b", "-q", "-j", "4", str(输出)],
                        capture_output=True, text=True)
    耗时 = round(time.perf_counter() - 起, 1)
    if 日志.returncode != 0:
        print("  compileall 报错:")
        print("   " + "\n   ".join(日志.stdout.strip().splitlines()[-15:]))
    pyc = list(输出.rglob("*.pyc"))
    print(f"  {耗时}s · 编出 {len(pyc)} 个 .pyc")

    print("═══ 3/4 删源码（只留 .pyc）═══")
    删 = 0
    for p in sorted(输出.rglob("*.py")):
        伴 = p.with_suffix(".pyc")
        if 伴.is_file():
            # ★ 保住权限位: 入口脚本原来是 755（能 ./main.py 直接跑), 换成 .pyc 也得能直接跑
            os.chmod(伴, p.stat().st_mode & 0o777)
        p.unlink()
        删 += 1
    print(f"  删掉 {删} 个 .py")
    for 目录 in sorted(输出.rglob("__pycache__"), reverse=True):
        shutil.rmtree(目录, ignore_errors=True)
    剩 = [str(p.relative_to(输出)) for p in 输出.rglob("*.py")]
    print(f"  复查: 树里还有 .py 吗 → {剩[:5] or '一个没有 ✓'}")
    return {"解释器版本": 版本, "编译耗时秒": 耗时, "pyc数": len(pyc), "删源码数": 删, "残留py": 剩}


def 验树(输出: pathlib.Path, 解释器: pathlib.Path, 补充路径: str = "") -> list[tuple[str, bool, str]]:
    print("═══ 4/4 验：拿字节码树真跑 ═══")
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if 补充路径:
        env["PYTHONPATH"] = 补充路径 + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    # .env 不进树（凭据不进包）: 从项目根的 .env 导出成环境变量给这次验证用
    候选 = 项目 / ".env"
    if 候选.is_file():
        for 行 in 候选.read_text(encoding="utf-8", errors="replace").splitlines():
            行 = 行.strip()
            if 行 and not 行.startswith("#") and "=" in 行:
                键, _, 值 = 行.partition("=")
                if 键 not in env:
                    env[键.strip()] = 值.strip().strip('"').strip("'")

    用例 = [
        ("自检", [str(解释器), str(输出 / "selfcheck.pyc")], "自检", 600),
        ("命令库检索", [str(解释器), str(输出 / "skill/linux/main.pyc"), "find", "磁盘还剩多少空间", "-n", "2"], "df", 600),
        ("算数", [str(解释器), str(输出 / "skill/math/main.pyc"), "calc", "1/3+1/6", "--位数", "20"], "0.5", 300),
    ]
    结果: list[tuple[str, bool, str]] = []
    for 名, 命令, 该出现, 超时 in 用例:
        r = subprocess.run(命令, cwd=输出, capture_output=True, text=True, timeout=超时, env=env)
        出 = r.stdout + r.stderr
        好 = r.returncode == 0 and 该出现 in 出
        if 名 == "自检":
            尾巴 = [x for x in 出.splitlines() if "/" in x and "通过" in x]
            详情 = (尾巴[-1].strip() if 尾巴 else 出.strip().splitlines()[-1][:70] if 出.strip() else "")
        else:
            详情 = next((x.strip() for x in 出.splitlines() if 该出现 in x), "")[:70]
        结果.append((名, 好, 详情))
        print(f"  {'✓' if 好 else '✗'} {名:<8} 退出码 {r.returncode} · {详情}")

    体积 = subprocess.run(["du", "-sm", str(输出)], capture_output=True, text=True).stdout.split()[0]
    print(f"\n  树体积 {体积} MB · 文件 {len([p for p in 输出.rglob('*') if p.is_file()])} 个")
    for 名, 好, _ in 结果:
        if not 好:
            print(f"  ★ 有没过的用例: {名} —— 别拿去打包")
    return 结果


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--输出", default=str(项目 / "dist/字节码树"))
    ap.add_argument("--python", default=None, help="编译用解释器（默认 uv 独立 3.14）")
    ap.add_argument("--验证python", default=None, help="验证用解释器（默认项目 .venv，要有依赖）")
    ap.add_argument("--只验", action="store_true")
    a = ap.parse_args()
    输出 = pathlib.Path(a.输出).resolve()
    解释器 = 找解释器(a.python)
    验证器, 补充路径 = 找验证解释器(a.验证python, 解释器)
    编版, 验版 = 版本号(解释器), 版本号(验证器)
    print(f"  编译用 {解释器} ({编版})")
    print(f"  验证用 {验证器} ({验版})" + (f" + PYTHONPATH {补充路径}" if 补充路径 else ""))
    if 编版.split(".")[:2] != 验版.split(".")[:2]:
        print("  ★ 警告: 两个解释器小版本不一致, .pyc 可能直接报 bad magic number")

    清单: dict[str, object] = {"项目": str(项目), "树": str(输出), "解释器": str(解释器),
                            "编译版本": 编版, "验证解释器": str(验证器), "验证版本": 验版}
    if not a.只验:
        建树(输出)
        清单.update(编字节码(输出, 解释器))
    结果 = 验树(输出, 验证器, 补充路径)
    清单["验证"] = [{"用例": 名, "通过": 好, "详情": 详} for 名, 好, 详 in 结果]
    清单["全过"] = all(好 for _, 好, _ in 结果)
    (输出.parent / "字节码清单.json").write_text(json.dumps(清单, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  清单 → dist/字节码清单.json · 全过: {清单['全过']}")
    return 0 if 清单["全过"] else 1


if __name__ == "__main__":
    sys.exit(main())

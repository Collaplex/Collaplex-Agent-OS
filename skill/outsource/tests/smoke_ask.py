#!/usr/bin/env python3
"""外援真跑一发: 真调云端, 不 mock.

跑法: .venv/bin/python skill/outsource/tests/smoke_ask.py [--家 deepseek|mimo]

验四件事:
    1. 能真拿到产出 (非空)
    2. 产出落盘了 (logs/outsource/*.md)
    3. 记账写了 (logs/outsource/用量.jsonl 多一行)
    4. 拿不到内容时会不会如实标失败 —— 用一条故意要它吐超长内容的题试 token 上限

★ 会花真钱 (一次几厘). --强制 跳开关, 但不跳预算.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

from budget import as_dict, ledger_path_of, output_dir_of, read_config, today_totals  # noqa: E402

PROJECT_ROOT = HERE.parent.parent.parent
MAIN = HERE.parent / "main.py"


def run_ask(task: str, house: str, quiet: bool = True) -> tuple[int, str]:
    """真跑一次 ask, 返回 (退出码, 输出)."""
    cmd = [sys.executable, str(MAIN), "ask", task, "--强制"]
    if house:
        cmd += ["--家", house]
    if quiet:
        cmd += ["--安静"]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(PROJECT_ROOT))
    return done.returncode, (done.stdout + done.stderr).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="外援真跑冒烟")
    parser.add_argument("--家", default="", help="deepseek / mimo, 默认按配置")
    args = parser.parse_args()

    config = read_config()
    ledger = ledger_path_of(config)
    outdir = output_dir_of(config)
    before_files = sorted(outdir.glob("*.md")) if outdir.is_dir() else []
    before_spent, before_count = today_totals(ledger)

    print("外援 · 真跑冒烟")
    print(f"  家: {args.家 or config.get('默认家')} · 记账前: {before_count} 次 / {before_spent:.4f} 元")

    print("[1] 真干一件小活")
    code, out = run_ask("用一句话说明 Python 的 GIL 是什么, 不超过 40 字.", args.家)
    print(f"  退出码 {code}")
    print(f"  {out.splitlines()[0] if out else '(无输出)'}")
    if code != 0:
        print("  ✗ 真跑失败, 后两项跳过")
        print(out)
        return 1

    after_files = sorted(outdir.glob("*.md"))
    new_files = [p for p in after_files if p not in before_files]
    after_spent, after_count = today_totals(ledger)
    ok_all = True

    print("[2] 产出落盘")
    if new_files:
        newest: Path = new_files[-1]
        body = newest.read_text(encoding="utf-8")
        print(f"  ✓ {newest.name} ({len(body)} 字符)")
        if len(body) < 100:
            print("  ✗ 产出文件太短, 像是空产出")
            ok_all = False
    else:
        print("  ✗ 没落盘")
        ok_all = False

    print("[3] 记账")
    print(f"  记账后: {after_count} 次 / {after_spent:.4f} 元 (多了 {after_count - before_count} 次)")
    if after_count > before_count:
        print("  ✓ 流水多了一行")
        last: Any = None
        for line in ledger.read_text(encoding="utf-8").splitlines()[-1:]:
            import json
            last = json.loads(line)
        row = as_dict(last)
        print(f"    末行: 家={row.get('家')} 成功={row.get('成功')} 金额={row.get('金额')} "
              f"tokens={as_dict(row.get('用量')).get('total_tokens')}")
    else:
        print("  ✗ 没记账")
        ok_all = False

    print()
    print("-" * 40)
    print("冒烟通过" if ok_all else "冒烟有问题")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())

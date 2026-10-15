#!/usr/bin/env python3
"""交叉验证真跑一发: 真调两家云端, 不 mock.

跑法: .venv/bin/python skill/mtp/tests/smoke_panel.py

验五件事:
    1. 两家都答上 (退出码 0)
    2. 参考材料落盘了 (logs/mtp/*.md)
    3. 材料里有"程序判出来的对照"那节
    4. 记账写了两行, 且都带 来自=mtp (钱进的是外援那个流水)
    5. 少于两家会被挡下

★ 会花真钱 (两家各一次, 一分钱以内). --强制 跳开关, 但不跳预算.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "skill" / "outsource" / "scripts"))

from budget import as_dict, ledger_path_of, read_config, today_totals  # noqa: E402

MAIN = HERE.parent / "main.py"


def run(args: list[str], timeout: float = 300.0) -> tuple[int, str]:
    """真跑一次 mtp, 返回 (退出码, 输出)."""
    done = subprocess.run([sys.executable, str(MAIN), *args], capture_output=True, text=True,
                          timeout=timeout, cwd=str(PROJECT_ROOT))
    return done.returncode, (done.stdout + done.stderr).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="交叉验证真跑冒烟")
    parser.add_argument("--家", default="deepseek,mimo", help="逗号分隔")
    args = parser.parse_args()

    money = read_config()
    ledger = ledger_path_of(money)
    before_rows = len(ledger.read_text(encoding="utf-8").splitlines()) if ledger.is_file() else 0
    outdir = PROJECT_ROOT / "logs" / "mtp"
    before_files = sorted(outdir.glob("*.md")) if outdir.is_dir() else []
    names = [item for item in args.家.split(",") if item]

    print("交叉验证 · 真跑冒烟")
    print(f"  家: {', '.join(names)} · 记账前 {before_rows} 行")

    print("[5] 少于两家必须被挡")
    code, out = run(["ask", "1+1=?", "--家", "deepseek", "--强制"])
    print(f"  退出码 {code} · {out.splitlines()[0] if out else '(无输出)'}")
    if code == 0:
        print("  ✗ 只给一家居然放行了")
        return 1
    print("  ✓ 挡住了")

    print("[1] 真跑: 两家答同一题")
    code, out = run(["ask", "1+1 等于几? 最后一行写 `答案: <数字>`", "--家", args.家, "--强制", "--安静"])
    print(f"  退出码 {code}")
    for line in out.splitlines()[:3]:
        print(f"  {line}")
    if code != 0:
        print("  ✗ 没跑成")
        print(out)
        return 1

    after_files = sorted(outdir.glob("*.md"))
    new_files = [path for path in after_files if path not in before_files]
    ok_all = True

    print("[2] 材料落盘")
    if new_files:
        newest: Path = new_files[-1]
        body = newest.read_text(encoding="utf-8")
        print(f"  ✓ {newest.name} ({len(body)} 字符)")
    else:
        print("  ✗ 没落盘")
        ok_all = False
        body = ""

    print("[3] 材料里有一致/分歧对照")
    if "## 程序判出来的对照" in body:
        print("  ✓ 有对照节")
        for line in body.splitlines():
            if line.startswith("- **"):
                print(f"    {line}")
    else:
        print("  ✗ 没有对照节")
        ok_all = False

    print("[4] 记账进的是外援那个流水")
    rows: list[dict[str, Any]] = []
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines()[before_rows:]:
            if line.strip():
                rows.append(as_dict(json.loads(line)))
    spent, count = today_totals(ledger)
    mine = [row for row in rows if row.get("来自") == "mtp"]
    print(f"  新增 {len(rows)} 行, 其中 mtp {len(mine)} 行 · 今天累计 {count} 次 / {spent:.4f} 元")
    if len(mine) >= 2:
        print(f"    {', '.join(str(row.get('家')) for row in mine)} · 合计 "
              f"{sum(float(row.get('金额', 0)) for row in mine):.5f} 元")
    else:
        print("  ✗ mtp 记账行不足两行")
        ok_all = False

    print()
    print("-" * 40)
    print("冒烟通过" if ok_all else "冒烟有问题")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())

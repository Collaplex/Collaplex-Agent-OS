#!/bin/sh
# 打 collaplex-agent-os 的 deb。两条路:
#
#   packaging/make_deb.sh              # 源码形态（包里是 .py, 老口径）
#   packaging/make_deb.sh --字节码      # 字节码形态（包里只有 .pyc —— 先跑 packaging/build_bytecode.py 并自验）
#   packaging/make_deb.sh --字节码 --验 # 打完顺便解开验一遍形态与自检
#
# ★ 产物落 <工程同级>/打包产物/deb/ —— 既不能在源树里(cp -a 会自拷贝), 也不能在 /tmp。
# ★ 字节码形态会先跑到"字节码化自验全过"才继续; 没过就**别打包**（宁可不出包）。
# ★ 变量名一律 ASCII —— 中文变量名 sh/dash 会当命令找（踩过）。
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
MODE=${1:-源码}
CHECK=${2:-}
export DEB_OUT=${DEB_OUT:-$(dirname "$ROOT")/打包产物/deb}

if [ "$MODE" = "--字节码" ]; then
    echo "═══ 先字节码化（树里 .py 全换成 .pyc, 并真跑自检/检索/算数）═══"
    "$ROOT/.venv/bin/python" "$ROOT/packaging/build_bytecode.py" || {
        echo "[错误] 字节码化自验没过 —— 不出包" >&2
        exit 1
    }
    export SRC_TREE=dist/字节码树
    echo
    echo "═══ 用 SRC_TREE=$SRC_TREE 打（源码不进包）═══"
else
    echo "═══ 源码形态（包里是 .py）═══"
fi

"$ROOT/debian/build.sh" || {
    echo "[错误] dpkg-buildpackage 没过, 看上面输出" >&2
    exit 1
}

DEB=$(ls -t "$DEB_OUT"/collaplex-agent-os_*.deb 2>/dev/null | head -1)
[ -n "$DEB" ] || { echo "[错误] $DEB_OUT 下没有 .deb 产物" >&2; exit 1; }
echo
echo "产物: $DEB  ($(du -h "$DEB" | cut -f1))"

if [ "$CHECK" = "--验" ]; then
    EXTRACT="$ROOT/dist/deb-解包"
    rm -rf "$EXTRACT"; mkdir -p "$EXTRACT"
    dpkg -x "$DEB" "$EXTRACT"
    TREE="$EXTRACT/usr/share/collaplex-agent-os"
    echo
    echo "═══ 解包验收 ═══"
    echo "  树里 .py:  $(find "$TREE" -name '*.py' | wc -l) 个"
    echo "  树里 .pyc: $(find "$TREE" -name '*.pyc' | wc -l) 个"
    echo "  入口: $(ls "$TREE"/cli.* 2>/dev/null | xargs -n1 basename | tr '\n' ' ')"
    echo "  顶层: $(ls "$TREE" | tr '\n' ' ')"
    echo "  skill 目录: $(ls "$TREE/skill" | tr '\n' ' ')"
    # 真跑: 自检（.env 从仓库根借一份给这次验证用, 包里是没有的）
    ENTRY="$TREE/selfcheck.pyc"
    [ -f "$ENTRY" ] || ENTRY="$TREE/selfcheck.py"
    echo "  ── 跑自检（形态: $(basename "$ENTRY")）──"
    # ★ .env 只**补缺**、不覆盖已有变量 —— 直接 `. .env` 会把当前 shell 的库变量盖掉,
    #   盖出"连不上库"的假报错（在仓库里用同样的盖法也报 3 项, 可见与包无关）。
    "$ROOT/.venv/bin/python" - "$ENTRY" "$ROOT/.env" <<'PY' | tail -6 | sed 's/^/    /'
import os, pathlib, subprocess, sys
入口, env文件 = sys.argv[1], sys.argv[2]
env = dict(os.environ, PYTHONUTF8="1")
p = pathlib.Path(env文件)
if p.is_file():
    for 行 in p.read_text(encoding="utf-8", errors="replace").splitlines():
        行 = 行.strip()
        if 行 and not 行.startswith("#") and "=" in 行:
            键, _, 值 = 行.partition("=")
            env.setdefault(键.strip(), 值.strip())
r = subprocess.run([sys.executable, 入口], env=env, capture_output=True, text=True)
sys.stdout.write(r.stdout + r.stderr)
PY
fi

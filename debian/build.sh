#!/bin/sh
# 打 collaplex-agent-os 的 deb —— 一条命令, 在打包机(或本机)跑。
#
#   debian/build.sh              # 打到 /tmp/deb-out/, 需要本机有 dpkg-buildpackage
#   debian/build.sh user@host    # 先 rsync 到远端那台干净机再打(推荐: 打包机专机专用)
#
# ★ 什么进包、什么不进包, 只看下面这段 RSYNC_EXCLUDES —— 改口径改这里, 别在命令行上手敲。
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(dirname "$HERE")                 # 项目根
TARGET=${1:-local}

# ---- 不进包的东西 -----------------------------------------------------------
# 运行时/构建产物: 由 postinst 在新机建, 进包会把新机的路径写死
# ★ 日志(*.log): 自己机器上跑出来的, 进包又大又可能带本地路径(踩过一次 15M embed-server.log)
# 2.5G 的实验目录与 vendor/llama.cpp(376M): 不属于运行时
# 凭据与备份: .env 只进 .env.example(全空值)
EXCLUDES="
--exclude=.venv --exclude=.git --exclude=dist --exclude=build-nuitka
--exclude=__pycache__ --exclude=*.pyc
--exclude=.env --exclude=.env.bak-* --exclude=.backup
--exclude=state --exclude=logs --exclude=*.log
--exclude=_json-retired-backup
--exclude=实验 --exclude=vendor/llama.cpp
"

if [ "$TARGET" = local ]; then
    # ★ 本地打包目录**必须在源树之外**: 这条路是 cp -a 整份源码树(排除只在 rules 的 tar 那步生效),
    #   落点若在源树里(如 dist/deb)就会"把目录复制到自身"直接失败。
    #   也别用 /tmp —— 本机 /tmp 是 7.2G 的 tmpfs 且会被定时清空, 3.6G 拷一份直接撑满(踩过)。
    OUT=${DEB_OUT:-$(dirname "$SRC")/打包产物/deb}
    rm -rf "$OUT"; mkdir -p "$OUT"
    cp -a "$SRC" "$OUT/src"
    cd "$OUT/src"
else
    echo "→ 同步到 $TARGET:~/build (排除: venv/git/日志/实验/凭据)"
    # ★ 必须先清空: rsync 的 --delete 不会删"接收端被 exclude 的旧文件",
    #   上一版同步过去的日志会原地留着, 下一次照样被打进包(踩过一次)
    ssh "$TARGET" 'rm -rf ~/build && mkdir -p ~/build'
    rsync -a --delete $EXCLUDES "$SRC/" "$TARGET:~/build/" || {
        echo "rsync 失败 —— 远端 ~/build 要先建好: ssh $TARGET 'mkdir -p ~/build'"; exit 1; }
    cd "$SRC"
    # 在远端打
    ssh "$TARGET" 'cd ~/build && rm -rf debian/.debhelper && dpkg-buildpackage -b -us -uc >/tmp/build.log 2>&1; echo "  远端 build 退出码 $?"; tail -3 /tmp/build.log'
    ssh "$TARGET" 'ls -la ~/collaplex-agent-os_*.deb | tail -1'
    exit 0
fi

echo "→ packaging (版本见 debian/changelog)"
rm -rf debian/.debhelper
dpkg-buildpackage -b -us -uc
echo "→ 产物:"
ls -la ../collaplex-agent-os_*.deb | tail -1
echo "→ 装到这台干净机验证: sudo apt-get install -y ./$(ls ../collaplex-agent-os_*.deb | tail -1 | xargs basename)"
echo "→ 装完还得建表/填凭据, 见 deployment-first-run.md"

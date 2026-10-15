#!/usr/bin/env bash
# 把数据/配置/脚本挂进编译产物目录。
#
# 为什么这么做：Nuitka 编译后，每个模块的 __file__ 都指向 dist 里的"虚拟位置"
# （实测 <dist>/web/bridge.py、<dist>/parser/adapters/__init__.py），而项目里
# 一律用「自己文件所在目录」往上数来定项目根 ⇒ **dist 就是"项目根"**。
# 于是把该在根下的东西挂进 dist，代码一行都不用改。
#
# ★ 挂的是软链：skill 改动即时生效（不用重编）、state/logs 与源码树共享。
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
# dist 目录名跟着入口脚本走（cli.py → cli.dist），自动认一下，别写死
DIST="$(ls -d "$ROOT"/编译产物/*.dist 2>/dev/null | head -1)"
if [ -z "$DIST" ] || [ ! -d "$DIST" ]; then
  echo "还没编出来：$ROOT/编译产物/*.dist"
  exit 1
fi
case "$DIST" in
  *.dist) : ;;
  *) echo "认出来的目录不像 Nuitka 产物，停手：$DIST"; exit 1 ;;
esac

link() {
  local name="$1"
  if [ ! -e "$ROOT/$name" ]; then
    echo "  跳过（源码树里没有）：$name"
    return
  fi
  rm -rf "$DIST/$name"
  ln -s "$ROOT/$name" "$DIST/$name"
  echo "  挂 $name"
}

echo "== 数据树与配置（config / state / logs / skill / vendor / .venv / .env / icon） =="
for n in config state logs skill vendor .venv .env icon.txt; do link "$n"; done

echo "== 子进程要调的同项目文件（自检 / 对话 / 看门狗 / 算 token / 起模型） =="
for n in start_models.sh local_fallback.sh pack_bundle.sh selfcheck.py main.py watchdog.py count_tokens.py; do link "$n"; done

echo "== web 前端（静态件 + 本地前端库） =="
mkdir -p "$DIST/web"
rm -rf "$DIST/web/static"
ln -s "$ROOT/web/static" "$DIST/web/static"
echo "  挂 web/static"
if [ -d "$ROOT/web/vendor" ]; then
  rm -rf "$DIST/web/vendor"
  ln -s "$ROOT/web/vendor" "$DIST/web/vendor"
  echo "  挂 web/vendor"
fi

echo
echo "完事。跑法："
echo "  $DIST/collaplex-agent 自检"
echo "  $DIST/collaplex-agent web --端口 8791"

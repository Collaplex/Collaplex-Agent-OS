#!/bin/bash
# 打一个「解压即用」的包 —— 不编译, 但把**解释器 + 依赖**都塞进去。
#
# 目标: 拷到另一台 Linux(x86_64) 上, 解压就能跑, 不用装 Python、不用装依赖。
# 做不到的(如实写进 解压即用.md): 模型服务、.env 凭据、网络、外部工具(carve)。
#
# 用法: ./pack_bundle.sh          # 产出 dist/collaplex-agent-<日期>.tar.zst
#
# 为什么这么打:
#   - 用 python-build-standalone 的独立解释器(自带 libpython, 零系统依赖) —— 不是 venv,
#     venv 里的 bin/python 是软链 + pyvenv.cfg 写死绝对路径, 搬机器就废
#   - 依赖装到 runtime/deps(--target), 启动器把它塞进 PYTHONPATH —— 绕开 venv 的路径写死
#   - ★ 项目代码一行不用改: 不用碰 __file__(那是编译成 onefile 才有的坑) —— 这就是不编译的好处
set -euo pipefail

PROJECT=$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)
DIST="$PROJECT/dist"
BUNDLE="$DIST/collaplex-agent"
STAMP=$(date +%Y%m%d)
OUT="$DIST/collaplex-agent-$STAMP.tar.zst"

echo "═══ 1/6 找自带解释器 (python-build-standalone, 零系统依赖) ═══"
# ★ 用 uv 官方管的 install_only 版当基座: 它天生已是精简版(107MB)。
#   别用 ~/.hermes/tools 那份(401MB, 里面积了 200MB 的 debug 段),
#   更别对它 strip —— 那个 build 的 ELF 布局特殊(.dynstr 不在 segment 里),
#   削一次就 "symbol lookup error / undefined symbol"(踩过)。
PYROOT=""
for cand in "$HOME"/.local/share/uv/python/cpython-3.14*-linux-x86_64-gnu \
            "${UV_PYTHON_INSTALL_DIR:-/nonexistent}"/cpython-3.14*-linux-x86_64-gnu; do
    if [ -x "$cand/bin/python3" ]; then PYROOT="$cand"; break; fi
done
if [ -z "$PYROOT" ]; then
    echo "  本地没有, 用 uv 下一个(约 50MB, 装到 ~/.local/share/uv/python)"
    uv python install 3.14
    for cand in "$HOME"/.local/share/uv/python/cpython-3.14*-linux-x86_64-gnu; do
        if [ -x "$cand/bin/python3" ]; then PYROOT="$cand"; break; fi
    done
fi
[ -n "$PYROOT" ] || { echo "[错误] 拿不到独立解释器" >&2; exit 1; }
echo "  $PYROOT"

echo "═══ 2/6 复制解释器到包里, 然后瘦身(测试套件/tcl-tk/调试符号都别带) ═══"
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/runtime"
cp -a "$PYROOT" "$BUNDLE/runtime/python"
PY="$BUNDLE/runtime/python"
BEFORE=$(du -sm "$PY" | cut -f1)
rm -rf "$PY/include" "$PY/share" "$PY/lib/tcl9.0" "$PY"/lib/libtcl*.so "$PY"/lib/libtk*.so \
       "$PY"/lib/python3.14/{tkinter,idlelib,turtledemo,ensurepip,venv} \
       "$PY"/lib/python3.14/test "$PY"/bin/idle3* "$PY"/bin/pip*
# ★ 别 strip! 这个 python-build-standalone 的 ELF 布局特殊(.dynstr 不在 segment 里),
#   strip 一削就 "symbol lookup error / undefined symbol"(踩过两次)。
#   只删没用的目录: 401MB -> 96MB, 解释器照样跑。削完当场自检。
"$PY/bin/python3" -c 'import sys; print("  解释器自检 ok:", sys.version.split()[0], "·", sys.prefix)'
echo "  $(du -sm "$PY" | cut -f1) MB (瘦身前 $BEFORE MB)"

echo "═══ 3/6 装依赖到 runtime/deps (不进 venv, 走 PYTHONPATH) ═══"
uv pip install --quiet --target "$BUNDLE/runtime/deps" --python "$PY/bin/python3" \
    -r "$PROJECT/requirements.txt"
echo "  $(du -sm "$BUNDLE/runtime/deps" | cut -f1) MB: $(ls "$BUNDLE/runtime/deps" | tr '\n' ' ')"

echo "═══ 4/6 放项目本体 (不带 venv / .env / 日志 / 缓存) ═══"
tar -C "$PROJECT" -cf - \
    --exclude='./.venv' --exclude='./.git' --exclude='./dist' --exclude='./build-nuitka' \
    --exclude='./.env' --exclude='./.backup' --exclude='./state' --exclude='./logs' --exclude='./__pycache__' \
    --exclude='*/__pycache__' --exclude='./skill/rag/corpus/*' --exclude='./skill/*/cache' \
    --exclude='*.crv' --exclude='.carve-backups' --exclude='*.restored' \
    . | tar -C "$BUNDLE" -xf -
mkdir -p "$BUNDLE/skill/rag/corpus" "$BUNDLE/logs"
echo "  项目本体 $(du -sm --exclude=runtime "$BUNDLE" | cut -f1) MB (含语料与索引)"

echo "═══ 5/6 写启动器 + 说明 ═══"
cat > "$BUNDLE/run.sh" <<'LAUNCHER'
#!/bin/sh
# Collaplex Agent —— 解压即用启动器 (自带解释器与依赖, 机器上不用装 Python)
#
#   ./run.sh              起对话
#   ./run.sh --自检       只跑自检, 看这个包在你这台机器上健不健康
#
# 还需要三样**不在包里**的东西, 见同目录 解压即用.md:
#   .env(模型配置) · 向量服务(检索用) · 网络
set -u
REAL=$(readlink -f -- "$0" 2>/dev/null) || REAL=$0
HERE=$(CDPATH= cd -- "$(dirname -- "$REAL")" && pwd)
PY="$HERE/runtime/python/bin/python3"
[ -x "$PY" ] || { echo "[错误] 自带解释器不在: $PY" >&2; exit 2; }
export PYTHONPATH="$HERE/runtime/deps${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUTF8=1
case "${1:-}" in
    --自检|--selfcheck) exec "$PY" "$HERE/selfcheck.py" ;;
esac
[ -f "$HERE/.env" ] || echo "[提示] 包不带 .env(凭据不进包)。照 .env.example 建一份再跑, 否则模型调用会失败。"
exec "$PY" "$HERE/main.py"
LAUNCHER
cat > "$BUNDLE/解压即用.md" <<'MD'
# Collaplex Agent —— 解压即用包

**这是什么**：不编译，但把**解释器和依赖**都打进来了 —— 另一台 Linux(x86_64) 上解压就能跑，
不用装 Python、不用装依赖。项目代码**一行没改**（所以源码版的调试手段全都在）。

## 三步跑起来

```bash
tar -I zstd -xf collaplex-agent-<日期>.tar.zst     # 1. 解压（xz 也行：tar -Jxf …）
cd collaplex-agent
cp .env.example .env && $EDITOR .env                # 2. 填 .env（键名照抄，值从原来那台搬）
./run.sh                                            # 3. 起对话
./run.sh --自检                                      #    只跑自检
```

## 包里有什么

```
run.sh                  启动器（自带解释器，不碰系统 python）
runtime/python/         Python 3.14.6（python-build-standalone，自带 libpython）
runtime/deps/           openai / python-dotenv / numpy
main.py sub_agent.py …  项目本体（源码，未编译）
skill/                  14 个 skill：seek / rag / skill_search / linux / kali / file / math / search / vision / timer / orchestra / outsource / mtp / ops（含命令库语料与索引）
config/                 配置与提示词
.env.example            只有键名，值留空 —— ★凭据不进包
```

## 包里**没有**的（目标机器上得自己准备）

| 缺什么 | 不管它会怎样 | 怎么办 |
|---|---|---|
| `.env` | 模型调用全失败 | 照 `.env.example` 填 |
| 向量服务（`.env` 里 `EMBEDDING_BASE_URL` 指的那个） | 记忆 / 命令库检索全失败（报错会直说缺什么） | 在目标机器起一个，或把 URL 指向已有的 |
| 网络 | 云端模型调不通 | — |
| `carve`（本机在 `~/.local/bin/carve`） | file skill 的读写命令跑不了，其余不受影响 | 单独装或把那个文件一起拷过去 |
| 本机实情 | linux skill 会照**目标机器**的实际状况回答 | 正常，本来就是这意思 |

## 平台

x86_64 Linux（glibc）。ARM / 手机不行 —— 那份走源码或 deb 包。

## 重打这个包

在本机项目根跑 `./pack_bundle.sh`（约 2 分钟），产出落在 `dist/`。
MD
chmod +x "$BUNDLE/run.sh"
# ★ 凭据不进包: 只从 .env 抄**键名**, 值一律留空
if [ -f "$PROJECT/.env" ]; then
    grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$PROJECT/.env" > "$BUNDLE/.env.example" || true
    sed -i 's/$/<在这里填>/' "$BUNDLE/.env.example"
else
    cat > "$BUNDLE/.env.example" <<'ENVTPL'
OPENAI_API_KEY=<在这里填>
OPENAI_BASE_URL=<在这里填>
OPENAI_MODEL=<在这里填>
EMBEDDING_BASE_URL=<在这里填>
EMBEDDING_MODEL=<在这里填>
# 外援 / 交叉验证（skill/outsource、skill/mtp）用的云端凭据
DEEPSEEK_API_KEY=<在这里填>
DEEPSEEK_BASE_URL=<在这里填>
MIMO_API_KEY=<在这里填>
MIMO_BASE_URL=<在这里填>
# 可选：想让 exec / 子 agent 单独走云端，才填这两组（不填=跟 OPENAI_* 共用一套）
EXEC_API_KEY=<在这里填>
EXEC_BASE_URL=<在这里填>
EXEC_MODEL=<在这里填>
SUBAGENT_API_KEY=<在这里填>
SUBAGENT_BASE_URL=<在这里填>
SUBAGENT_MODEL=<在这里填>
DEBUG=0
ENVTPL
fi
echo "  run.sh(可执行) + .env.example(只有键名, 值留空)"

echo "═══ 6/6 压包 (zstd) ═══"
cd "$DIST"
tar -cf - collaplex-agent | zstd -q -f -12 -T0 -o "$OUT"
echo
echo "产物: $OUT"
echo "  压缩包 $(du -h "$OUT" | cut -f1)  ·  解压后 $(du -sh "$BUNDLE" | cut -f1)"

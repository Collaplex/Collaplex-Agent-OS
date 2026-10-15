#!/bin/bash
# 推到 Gitea —— 主仓 + 每个 skill 一个独立仓, 全部公开。
#
# 用法:
#   ./push_gitea.sh              # 全推(主仓 + 所有 skill)
#   ./push_gitea.sh main         # 只推主仓
#   ./push_gitea.sh rag          # 只推某个 skill (seek / rag / search / skill_search / linux / file / outsource / mtp / math / vision / ops)
#
# 仓库布局:
#   collaplex-agent                 整个项目
#   collaplex-skill-rag             skill/rag        -> collaplex-skill-rag
#   collaplex-skill-linux           skill/linux      -> collaplex-skill-linux
#   collaplex-skill-file            skill/file       -> collaplex-skill-file
#   collaplex-skill-seek            skill/seek       -> collaplex-skill-seek
#   collaplex-skill-search          skill/search     -> collaplex-skill-search(联网搜索)
#   collaplex-skill-router          skill/skill_search -> collaplex-skill-router(技能路由; 原名 -search, 2026-10-09 让给联网搜索)
#
# ★ 凭据不写在这个文件里: 从别处**现成的带凭据 remote**里现取(本机惯例: 带凭据的那个叫 gitea)。
#   换机器/换口令时, 改 CRED_FROM 指向一个已经有 gitea remote 的仓库即可。
#
# ★ skill 独立仓是**给阅读和引用**的: 几个 skill 之间有互相 import(linux/file 借 rag 的
#   切片与检索), 拆开单独跑不动 —— 要连着跑就放回主项目的 skill/ 底下(README 里写明了)。
set -euo pipefail

HERE=$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)
OWNER=edgevoid
HOSTWEB=https://collaplex.me/git
CRED_FROM=${CRED_FROM:-$HOME/桌面/工作区/实验/collaplex音效}
SKILLS="seek rag search skill_search linux file outsource mtp math vision ops"

# ① 取凭据(git 用户名 + 口令), 只在内存里过, 不落盘不打印
CRED=$(git -C "$CRED_FROM" remote get-url gitea 2>/dev/null || true)
if [ -z "$CRED" ]; then
    echo "[错误] 没从 $CRED_FROM 取到带凭据的 gitea remote" >&2
    exit 1
fi
GITUSER=$(printf '%s' "$CRED" | sed -E 's#^https://([^:]+):.*#\1#')
GITPASS=$(printf '%s' "$CRED" | sed -E 's#^https://[^:]+:([^@]+)@.*#\1#')
HOSTONLY=${HOSTWEB#https://}

push_url() {  # $1 = 仓库名
    printf 'https://%s:%s@%s/%s/%s.git' "$GITUSER" "$GITPASS" "$HOSTONLY" "$OWNER" "$1"
}

repo_of() {  # skill 目录名 -> 仓库名后缀(仓库统一叫 collaplex-skill-<后缀>)
    case "$1" in
        # 技能路由那个: 仓库原名 collaplex-skill-search, 2026-10-09 让给联网搜索(skill/search) → 改叫 -router
        skill_search) echo "router" ;;
        *) echo "$1" ;;
    esac
}

push_main() {
    echo "═══ 主仓 collaplex-agent ═══"
    git -C "$HERE" remote set-url origin "$HOSTWEB/$OWNER/collaplex-agent.git" 2>/dev/null \
        || git -C "$HERE" remote add origin "$HOSTWEB/$OWNER/collaplex-agent.git"
    git -C "$HERE" remote set-url gitea "$(push_url collaplex-agent)" 2>/dev/null \
        || git -C "$HERE" remote add gitea "$(push_url collaplex-agent)"
    # ★ 历史重写过(.env 从全历史清掉) ⇒ 必须强推, 否则远端还是旧历史
    git -C "$HERE" push -q --force gitea main
    echo "  ✓ 推完了 · $HOSTWEB/$OWNER/collaplex-agent"
}

# 缺 README 的 skill, 补一份短的(只在独立仓里加, 主项目不动)
write_readme() {  # $1 = skill 目录名  $2 = 目标目录
    case "$1" in
        seek)
            cat > "$2/README.md" <<'MD'
# collaplex-skill-seek

**主 skill** —— 主 agent 的系统提示词：对话与思考规范、末尾唯一标记块 json 的写法、
以及"手头没有的能力"该怎么如实说（不许编工具名、不许把命令丢给用户自己跑）。

正文就是 `SKILL.md`。这是 [collaplex-agent](https://collaplex.me/git/edgevoid/collaplex-agent)
的 `skill/seek/`，拆成独立仓只为方便阅读与引用。
MD
            ;;
        linux)
            cat > "$2/README.md" <<'MD'
# collaplex-skill-linux

**本机 Linux 命令库** —— 63 条命令知识（一命一一条 `commands/*.md`，照本机 `--help` 抄），
给执行 agent 精准找到"这台机器上该怎么干"：磁盘 / 内存 / 进程 / 端口 / 服务 / 日志，
外加能真动手的那几条（`rm` / `mkdir` / `cp` / `mv` / `nohup`）。

- 入口：`main.py`（`find` 检索 / `index` 建索引），检索件在 `scripts/retrieve.py`
- 语料：`commands/*.md` + `commands-index.json`，自测在 `tests/`
- ★ 依赖：检索借 `rag` skill 的切片 / 嵌入函数，**拆开单独跑不动** —— 放回主项目的
  `skill/linux/` 底下才跑得起来（rag 是前置件）

这是 [collaplex-agent](https://collaplex.me/git/edgevoid/collaplex-agent) 的 `skill/linux/`。
MD
            ;;
        file)
            cat > "$2/README.md" <<'MD'
# collaplex-skill-file

**读写代码的命令库** —— 16 条（一命一一条 `commands/*.md`），底下是 `carve`：
按语法结构读 / 改代码（改前自动备份、能 `undo`），不是 `sed` 那种按行硬改。

- 入口：`main.py`，检索件 `scripts/retrieve.py`，语料 `commands/*.md`
- ★ 依赖两样：① 检索借 `rag` skill 的切片 / 嵌入函数 ② `carve` 在 `PATH` 上
  （`carve-cli` 目前只在本机，`~/.local/bin/carve`）—— 拆开单独跑不动

这是 [collaplex-agent](https://collaplex.me/git/edgevoid/collaplex-agent) 的 `skill/file/`。
MD
            ;;
        search)
            cat > "$2/README.md" <<'MD'
# collaplex-skill-search

**联网搜索** —— 要查外面的事（某个网页写了什么 / 某个说法有没有出处 / 某个网址通不通）都走这里：
先看**热库**有没有（省一次出网）→ 没有再打 **bing + 百度** 拿候选（跨站去重）→ 用**真浏览器**把页取回来 →
**去壳留肉**成正文 → 结果落**热库**备回查。

- 八个动作（`commands/*.md`）：`搜`（bing+百度一起打）· `取`（真浏览器取页）· `正文`（去壳留肉，`--save` 落库）·
  `浏览器`（常驻浏览器管理）· `热库`（回查搜过取过的东西）· `语料`（库总览）· `过期`（热库沉冷）· `清理`（冷库到点/超量清）
- 实现件在 `scripts/`：`serp.py`(搜) · `browser.py`(取) · `article.py`(正文) · `corpus.py`(热库/冷库) · `fetch.py`(HTTP 直抓) · `retrieve.py`(命令库检索)
- ★ **红线：只回原文片段 + 链接** —— 不复述、不改写、不做总结推理；取不到就把具体报错带回来，不编内容
- ★ **每站取页路不一样**：bing 用真浏览器，百度只能 HTTP 直抓（真浏览器打百度是空页面）
- ★ 落库两张表（`search_hot` 检索用的热库 / `search_corpus` 只留存的冷库，90 天 / 2GB 封顶），去重按 `(地址, 原文哈希)`；
  页面截图跟 TTL 一起清；单轮命令条数有 100 次闸（状态落 `cache/budget.json`）
- ★ 依赖：落库的切片 / 嵌入借 `rag` skill，PG 用 `.env` 的 `RAG_PG_DSN` —— **拆开单独跑不动**，
  放回主项目的 `skill/search/` 底下才跑得起来（rag 是前置件）

这是 [collaplex-agent](https://collaplex.me/git/edgevoid/collaplex-agent) 的 `skill/search/`。
MD
            ;;
        outsource)
            cat > "$2/README.md" <<'MD'
# collaplex-skill-outsource

**外援** —— 本地这支小模型拿不准的时候（写不出成段能跑的代码、推不动多步推理），
把**一件明确的活**交给云端强模型（默认 DeepSeek）做，拿回**能直接用的产出**。

- 四个件：`main.py` 分发 · `scripts/budget.py`（开关 / 日预算 / 次数 / 按实际用量算钱）
  · `scripts/ask.py`（程序拼任务 → 真调用 → 产出落盘 → 写流水）· `scripts/status.py`
- ★ **默认关着**（会花钱）；开了受 单次 0.3 元 / 每日 2 元 / 20 次 约束，每笔落盘
- ★ 拿不到内容一律标失败（空答 / 超时 / HTTP 错都明确报），**绝不静默当成功**
- ★ 凭据只从 `.env` / `~/.hermes/.env` 读，产出和日志里都不写 key
- 实测（6 道题，程序判分）：本地 5/6、外援 6/6；**外援主要买的是速度**（0.8~2.5 秒 vs 本地 28~156 秒），
  一道约 1.2 厘

这是 [collaplex-agent](https://collaplex.me/git/edgevoid/collaplex-agent) 的 `skill/outsource/`。
MD
            ;;
        mtp)
            cat > "$2/README.md" <<'MD'
# collaplex-skill-mtp

**交叉验证（MTP）** —— 同一个问题问**两家以上不同模型**，把各自的答案**并排**摆出来，
再把程序判得出的**分歧点**挑出来，当**参考资料**交给本地小模型，让它自己综合。

- 位置是**第二级**：本地卡住 → 外援（一级）→ 外援也不行才轮到它
- 三个件：`main.py` 分发 · `scripts/panel.py`（并行问几家 → 答案指纹 → 一致/分歧分组 → 出材料）
  · `scripts/status.py`
- ★ **不替调用方下结论**：只做"并排 + 挑分歧"
- ★ **钱袋子沿用外援**（`skill/outsource/resources/outsource.json`）：家的凭据 / 价目 / 预算 / 记账都在那边
- ★ 答案指纹靠末行约定：系统提示词要求各家末行写 `答案: ...`
- ★ 依赖：借 outsource 的 `budget.py` / `ask.py`，**拆开单独跑不动** —— 放回主项目 `skill/` 底下才跑得起来

这是 [collaplex-agent](https://collaplex.me/git/edgevoid/collaplex-agent) 的 `skill/mtp/`。
MD
            ;;
        math)
            cat > "$2/README.md" <<'MD'
# collaplex-skill-math

**算数命令库** —— 12 个动作（`calc` 表达式 · `num` 分解/质数/阶乘/组合 · `solve` 方程 ·
`linalg` 线代 · `poly` 多项式 · `calculus` 微积分 · `stats` 统计 · `prob` 概率 ·
`money` 钱 · `units` 换算 · `plot` 出图 · `date` 日期），一动作一条 `commands/*.md`。

**存在的唯一目的：不让模型自己硬算。** 结论里只要出现数字的运算结果，就先写命令、拿命令的输出说话 ——
有理数精确 ＋ `Decimal` 高精度，`sqrt` / `ln` / `sin` / 阶乘 / 百分号 / `^` 都认。
命令说"算不了"就如实回报原因，**不许**改口自己估一个补上。

- 入口：`main.py`（`find` 查命令库 / `index` 建索引），检索件 `scripts/retrieve.py`，
  语料 `commands/*.md` ＋ `commands-index.json`，自测在 `tests/`
- ★ 依赖：检索借 `rag` skill 的切片 / 嵌入函数，**拆开单独跑不动** —— 放回主项目的
  `skill/math/` 底下才跑得起来（rag 是前置件）

这是 [collaplex-agent](https://collaplex.me/git/edgevoid/collaplex-agent) 的 `skill/math/`。
MD
            ;;
        vision)
            cat > "$2/README.md" <<'MD'
# collaplex-skill-vision（看图）

一张本机图片 → 一段文字。★ **图不寄存**: 那一次请求发出去就散了, 回来的是文字 ——
不进会话历史、不进库、不落第二份。

两路走: 主路 = `.env` 里的云端视觉（`OPENAI_*`）; 不成自动兜底本地 llama.cpp 的 `qwen3-vl-8b`
（起它要带 `--mmproj`; 显存紧还得配 `--no-mmproj-offload`, 视觉塔算在 CPU 上）; 两条都不通就照实说, 不编。

    .venv/bin/python main.py 看图 <图片路径> [--问 "问什么"]
    .venv/bin/python main.py 状态 [--真读]      # --真读: 真送一张图, 验"能不能读图"

这是 [collaplex-agent](https://collaplex.me/git/edgevoid/collaplex-agent) 的 `skill/vision/`。
MD
            ;;
        ops)
            cat > "$2/README.md" <<'MD'
# collaplex-skill-ops（这套系统自己的使用与维护手册）

问"这套系统怎么起 / 怎么用 / 怎么维护 / 怎么排错"时的落点。28 条一条一件：
总入口与启动页两按钮 · 网页版与设置页八节 · 本地模型 8790+8199 · 记忆库 PG 两个实例 · 自检 30 项 ·
看门狗 · 日志哪件事看哪份 · 命令行跑一轮 · 三层记忆 · 上下文与记忆预算 · 清洗管线 · 清洗的症状与坑 ·
灌二层嵌入 · 命令库怎么查 · skill 清单与挑选 · 外援与交叉验证 · 定时 · 编排 · 看图 · 联网搜索 ·
长活后台作业 · 改代码的规矩 · 加新 skill 的落地清单 · 打包与开源发布 · 配置都在哪 · 首次部署 ·
排错对照表 · 一轮对话内部分工。

- 语料 `commands/*.md` ＋ `commands-index.json`，自测在 `tests/`（检索对照：43 例该命中 ＋ 4 例库里没有）
- ★ 依赖：检索借 `rag` skill 的切片 / 嵌入函数，**拆开单独跑不动** —— 放回主项目的
  `skill/ops/` 底下才跑得起来（rag 是前置件）

这是 [collaplex-agent](https://collaplex.me/git/edgevoid/collaplex-agent) 的 `skill/ops/`。
MD
            ;;
    esac
}

push_skill() {  # $1 = skill 目录名
    local name=$1 repo branch tmp
    repo="collaplex-skill-$(repo_of "$name")"
    branch="publish-$name"
    echo "═══ $repo (skill/$name) ═══"

    git -C "$HERE" branch -D "$branch" >/dev/null 2>&1 || true
    git -C "$HERE" subtree split -q -P "skill/$name" -b "$branch"

    tmp=$(mktemp -d)
    git clone -q --single-branch --branch "$branch" "$HERE" "$tmp/repo"
    cp "$HERE/LICENSE" "$tmp/repo/LICENSE"
    [ -f "$tmp/repo/README.md" ] || write_readme "$name" "$tmp/repo"
    git -C "$tmp/repo" add -A
    git -C "$tmp/repo" -c user.name=edgevoid -c user.email=edgevoid@gitea.local commit -q \
        -m "开源: 加 LICENSE 与 README(独立仓的打包件, 主项目里没有这两份)"
    git -C "$tmp/repo" push -q --force "$(push_url "$repo")" HEAD:main
    rm -rf "$tmp"
    git -C "$HERE" branch -D "$branch" >/dev/null 2>&1 || true
    echo "  ✓ 推完了 · $HOSTWEB/$OWNER/$repo"
}

case "${1:-all}" in
    all)
        push_main
        for s in $SKILLS; do push_skill "$s"; done
        ;;
    main) push_main ;;
    *) push_skill "$1" ;;
esac

echo
echo "完成。仓库: $HOSTWEB/$OWNER"

# 打包与发布 · 三种交付形态

**用途**：把系统搬到别的机器 / 发出去。三种形态各管一段，别混。

**① 解压即用包（推荐给"能搬走的东西"）**
- `./pack_bundle.sh`　约 2 分钟 → `dist/collaplex-agent-<日期>.tar.zst`（约 46~48 MB，解开 188 MB）
- 带解释器（python-build-standalone 的 install_only 版）+ `runtime/deps` + `run.sh`（塞 `PYTHONPATH`），**项目代码一行不改**
- 包里**没有** `.env`（只给键名留 `.env.example`）、没有向量服务 / 网络 / `carve`；`dist/` 进 `.gitignore`
- ★ 基座那份解释器**绝不能 strip**（`symbol lookup error: undefined symbol`）；要瘦只删没用目录（`tcl`/`tk`/`idle`）

**② 编译成独立可执行件（Nuitka，★ 不含 skill）**
- `bash build.sh`（自己 setsid 脱离会话跑，日志 `logs/编译.log`，约 25 分钟）→ `bash mount_data.sh`（把 config/state/logs/skill 等软链进产物，必须做）
- ★ 必须 `--include-package`：`openai / pydantic / anyio / jiter / sniffio / h11`（漏 `openai` 编译能过、首页能开，**真打一轮就炸**）
- skill 是指回源目录的软链 ⇒ **skill 改动即时生效，不用重编**

**③ 开源到 Gitea（一 skill 一仓）**
- `./push_gitea.sh`（全推）/ `main`（只推主仓）/ `<skill>`（推一个）；用 `git subtree split -P skill/<名>` 拆历史，**skill 必须先提交进主仓**，且**仓库要先建**（Gitea 不许 push-to-create）
- ★ 发之前**全历史扫凭据**（`git log --all --oneline -- .env` + `git grep <真值> $(git rev-list --all)`），历史里进过 `.env` 就用 `filter-branch` 清 + 强推；扫描词只取密钥类（KEY/TOKEN/SECRET/PASSWORD），别把 URL / 模型名当搜索词
- 推完验收：匿名能看到仓库页 / raw 文件 / 归档（`REQUIRE_SIGNIN_VIEW` 要为 false），每个仓真克隆一遍核密钥 0 命中

**新机器上手**：见项目根 `deployment-first-run.md`（PG + pgvector → 空库先建表四步 → 凭据与模型服务 → `collaplex-agent 自检` + 一问一答）。

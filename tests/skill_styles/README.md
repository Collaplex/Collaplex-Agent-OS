# 对照实验材料 · skill 的写法

这里是**实验用**的 skill 版本，不是生产件 —— 生产的那份仍在 `config/skills/judge.md`，本目录不参与运行。

| 版本 | 来源 | 行数 |
|---|---|---|
| `judge-current.md` | `config/skills/judge.md` 的**逐字节拷贝**（冻结当"对照臂"） | 84 |
| `judge-stamped.md` | 新写法（老板的想法：先洗脑型约束，再"能干什么 / 不能干什么 / 需要做什么"） | 48 |
| `judge-current-speak.md` | 同现行，只把"只输出 JSON"换成"你怎么判的就原原本本说出来" | 83 |
| `judge-stamped-speak.md` | 同钢印，同上放开契约 | 47 |

两版**只换写法、不换内容**：判据点一一对应（结果落点 / 要出一个数 / 本系统手册 / 上文指代 / 短句不看长短 / 算数的例外），
产出契约都是 `{"need": bool, "wanted": str}` —— 否则对照的变量就不止一个了；
"说话版"只动**输出形态那一处要求**（为了看"钢印会不会让模型自言自语"），判据一个字不改。

两个探针：

```bash
# ① 答对没有（判据准不准）：5 组 28 题 × 版本 × 2 模型
.venv/bin/python tests/skill_style_probe.py
.venv/bin/python tests/skill_style_probe.py --只 3            # 单题重跑（项目惯例）
.venv/bin/python tests/skill_style_probe.py --版本 judge-stamped.md

# ② 输出长成什么样（不判对错，只收形态）：4 个"说"场景 × 版本 × 2 模型
.venv/bin/python tests/skill_voice_probe.py
```

① 判据 = `need` 与期望是否一致（主判据）+ 字符数 + 耗时；② 判据 = 形态：
自言自语标记（第一人称独白 / 自问自答）、表演标记（自我介绍开场 / emoji / 括号写动作）、
守不守契约（JSON / 散文 / 两样都有 / 没契约）、有没有把判据念出来。

题组 1~3 直接取现成回归 `skill/linux/tests/left_chain_probe.py` 的用例（同源，不另抄一份），
题组 4~5 取现行 skill 里"实测每次都漏"的那两张表。同一题的各版 × 两模型**紧挨着跑**，
让当时的环境（模型负载 / 网络）对各版是一样的（老板口径：单组排除耦合与突发）。

产物：`logs/对照-skill写法-<日期>.{txt,jsonl}`（① 汇总 + 逐题明细 + 每发原文）·
`logs/对照-skill输出形态-<日期>.txt`（② 逐手原文 + 形态汇总）。

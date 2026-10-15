---
name: orchestra
description: 任务编排 —— 把一轮里要干的活儿先攒成清单，再逐条推进。清单落冷库按对话分行，web 上显示在输入框上面，收工撤单后自己消失。
version: 1.0.0
author: edgevoid
compatibility: 需要冷库(RAG_PG_DSN)；web 面靠 web/server.py 的 /api/清单
trigger_keywords: [编排, 清单, 活儿单, 攒任务, 逐条执行, 任务面板, orchestra]
allowed_tools: [terminal]
conflict_skills: []
---

# 任务编排

## 任务目标

把一件大活儿拆成**清单**再逐条干：先攒、够了一收 → 立单 → 逐条执行 → 逐条验收 → 全好了收工。
判断归**主 agent**（它才是编排者）；干活的模型不许自判自己那件好了。

## 触发条件

**启用**（主 agent 判断）：
- 一轮里有 3 件以上的活儿要干，且彼此有先后（前一件的产出是后一件的输入）
- 老板明确说「排个单」「按清单来」「一件一件做」
- 跨轮/跨重启的活儿（清单在库里，断了能接着推）

**禁止**：
- 只有 1 件活儿 —— 直接干，别为它立单（那是给清单加税）
- 活儿还没想清楚 —— 先想清楚再立单，清单里不许有「看着办」这种条目
- 想拿它当待办记事本 —— 它不是记事情的地方，是要**执行**的活儿单

## 输入

条目数组，每条至少一句「说明」，可选「做法」「判据」：

```json
[{"说明": "勘察落点", "做法": "grep main.py 找 continue", "判据": "指出行号"},
 {"说明": "写 skill", "做法": "main.py + metadata", "判据": "CLI 跑得通"}]
```

## 执行步骤

1. **攒**：把活儿逐条列出来（说明 / 做法 / 判据）。上限 20 件 —— 超了就说明该拆成两轮。
   ★ **「做法」要写能直接跑的命令**，别写「走 math skill 真算」这种话（2026-10-09 真机踩过：
   注入给下一轮时，模型拿到这种话会开始臆造 `<tool_call>` 语法绕圈，七分钟不收敛）。
   写成 `.venv/bin/python skill/math/main.py calc "111*111"` 这种，一轮就落地。
2. **立单**：`main.py plan --json -` （stdin 递数组）。整份盖掉这一对话原来的单。
3. **递出去**：`main.py next` 拿下一件 → 派给干活的 → 一发出去就 `main.py doing <序号>`。
4. **验收后再标**：主 agent 看产出对不对 → 对就 `main.py done <序号> --产出 "..."`；不对 `main.py retry <序号>` 重来（上限 3 次，事不过三）→ 到顶 `main.py blocked <序号> --产出 "为什么卡"`。
5. **全好了收工**：`main.py finish` 撤单（web 面板自己消失）。

## 输出格式

- `list`：`任务 2/5（对话 cli）` + 逐条 `序号. [状态] 说明`（有重试次数/产出就带上）
- `next --json`：下一件的完整条目（JSON）
- 其余动作：照抄命令输出，别加工

## 边界与错误处理

| 情况 | 怎么办 |
| --- | --- |
| 条目超过上限 | 报「一张单最多 N 件」并退出码 1 —— 让主 agent 拆两轮，别自己截断 |
| 有条目没写「说明」 | 报「不许有无名活儿」退出码 1 —— 回去补 |
| 序号不存在 | 退出码 3，人话说明「没有第 N 件」 |
| 重试到 3 次 | CLI 会提示「到顶了，该标卡住」——由主 agent 决定标卡住还是改做法，**不许无限重试** |
| 冷库不通 | 打一行中文报错，退出码 1；清单不会静默变空（静默当空表会把别人的单覆盖掉） |
| 一次对话里 exec 次数到 50 | 框架侧拦；主 agent 要把清单现状交代清楚再停 |

## Few-shot 示例

```
$ echo '[{"说明":"勘察落点"},{"说明":"写 skill"}]' | .venv/bin/python skill/orchestra/main.py plan --json -
{"对话": "cli", "件数": 2, "单": [{"序号": 1, "说明": "勘察落点", "状态": "待做", ...}]}

$ .venv/bin/python skill/orchestra/main.py list
任务 0/2（对话 cli）
  1. [待做] 勘察落点
  2. [待做] 写 skill

$ .venv/bin/python skill/orchestra/main.py doing 1 && .venv/bin/python skill/orchestra/main.py done 1 --产出 "main.py:795 / main.py:686"
$ .venv/bin/python skill/orchestra/main.py list
任务 1/2（对话 cli）
  1. [好了] 勘察落点  ← main.py:795 / main.py:686
  2. [待做] 写 skill

$ .venv/bin/python skill/orchestra/main.py finish
撤了 1 行（对话 cli）—— web 面板会自己消失
```

## 注意事项

- **判断归主 agent**：`done` 是主 agent 验收后才调的，别让干活的自己标好了。
- **卡住要留痕**：做不了的件标 `卡住`，不许从单里删掉或静默跳过。
- **一件一行**：清单显示在 web 输入框上面，一条一行；报告里也别把多条串成一行。
- **断电续干**：库里那份就是现场，进程起来读回来接着推。

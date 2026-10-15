---
name: skill_search
description: skill 检索：给一句话，找出该用哪个 skill，返回命中的 skill 描述和相对目录。
trigger_keywords: [找 skill, 用哪个 skill, skill 检索, 技能检索, 技能路由, 该用哪个工具, 有没有现成的工具]
version: 1.0.0
---

# skill 检索

一句话进去，**该用哪个 skill** 出来 —— 连同它的描述和相对目录。

## 什么时候用

- 手上有个活，不确定项目里有没有现成的 skill 能做 → 先 `find` 一下
- 要路由：拿到命中的相对目录，再去读那个目录的 `SKILL.md` 正文
- 加完新 skill 之后，`index` 刷新一次，让它可被检索到

## 什么时候别用

- **不回答内容问题。** 问"这个设计怎么写的"该走 `rag`，这里只认"哪个 skill 干这个"
- 别拿它当 skill 清单用 —— 要列清单直接 `ls skill/`

## 语料是什么

每个 skill 目录下的 `SKILL.md` 的 **frontmatter**（`---` 之间那段 YAML）。
一个 skill 一条，不切片。

所以 frontmatter 写得越清楚（`description` + `trigger_keywords`），越容易被检索到 ——
**这两个字段就是检索信号本身**。

## 怎么跑

```bash
# 前提: 向量服务起着（跟 rag 共用同一个服务，起一次就够）
.venv/bin/python skill/skill_search/scripts/embed_server.sh start

# 建/刷新索引（加完 skill 或改了 frontmatter 之后跑）
.venv/bin/python skill/skill_search/main.py index

# 检索
.venv/bin/python skill/skill_search/main.py find "把 PDF 转成 markdown"
.venv/bin/python skill/skill_search/main.py find "..." -n 5 --json
.venv/bin/python skill/skill_search/main.py find          # 交互模式
```

## 返回什么

```json
{
  "query": "把 PDF 转成 markdown",
  "hit": true,
  "threshold": null,
  "results": [
    {
      "rank": 1,
      "score": 0.6123,
      "index": 1,
      "source": "skill/rag",
      "name": "rag",
      "description": "资料检索：查询进，原文片段出。只读。",
      "text": "name: rag\ndescription: ..."
    }
  ]
}
```

- `source` 就是**相对目录**，拿到后去读 `<source>/SKILL.md` 正文
- `description` 从 frontmatter 里抽出来单独给，方便直接看
- `text` 是整段 frontmatter 原文

## 边界

| 情况 | 表现 |
|---|---|
| 索引不存在 | 报错并提示先跑 `index`，退出码 1 |
| 向量服务没起 | 连试 3 次后报错，不会被静默吞掉 |
| 某个 skill 没有 SKILL.md 或没有 frontmatter | 打印 `[跳过]`，不中断 |
| `hit_threshold` 是 `null`（默认） | 不过滤，top-k 全给，由调用方判断 |
| 想限定只认高分 | 在 `resources/skill_index.json` 里把 `hit_threshold` 设成数字 |

**阈值默认不设**（`hit_threshold: null`）。当前 3 条语料下相关/无关的分离在 **0.49** 附近
（±0.05），但样本太少不足为凭，所以不硬套。想开就把配置里那项设成 `0.49`。

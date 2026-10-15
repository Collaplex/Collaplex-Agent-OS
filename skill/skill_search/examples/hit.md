# 例：命中

真实抓取的输出，不是手写的。

## 终端形态

```
$ .venv/bin/python skill/skill_search/main.py find "我要查点资料"

查询: 我要查点资料
索引 3 个 skill
----------------------------------------------------------------
[1] 相似度 0.7015   rag
    目录: skill/rag
    描述: 资料检索。把问题丢进来，拿回最相关的原文片段；只回原文，不做推理和总结。
----------------------------------------------------------------
[2] 相似度 0.5302   seek
    目录: skill/seek
    描述: 模型默认思考技能，模仿人的自然思考方式
----------------------------------------------------------------
[3] 相似度 0.4981   skill_search
    目录: skill/skill_search
    描述: skill 检索：给一句话，找出该用哪个 skill，返回命中的 skill 描述和相对目录。
----------------------------------------------------------------
```

## JSON 形态（`--json`，给程序读的就是这个）

```json
{
  "query": "我要查点资料",
  "hit": true,
  "threshold": null,
  "results": [
    {
      "rank": 1,
      "score": 0.701468,
      "index": 0,
      "source": "skill/rag",
      "text": "name: rag\ndescription: 资料检索。把问题丢进来，拿回最相关的原文片段；只回原文，不做推理和总结。",
      "name": "rag",
      "description": "资料检索。把问题丢进来，拿回最相关的原文片段；只回原文，不做推理和总结。"
    },
    {
      "rank": 2,
      "score": 0.530172,
      "index": 1,
      "source": "skill/seek",
      "text": "name: seek\ndescription: 模型默认思考技能，模仿人的自然思考方式",
      "name": "seek",
      "description": "模型默认思考技能，模仿人的自然思考方式"
    },
    {
      "rank": 3,
      "score": 0.498083,
      "index": 2,
      "source": "skill/skill_search",
      "text": "name: skill_search\ndescription: skill 检索：给一句话，找出该用哪个 skill，返回命中的 skill 描述和相对目录。\ntrigger_keywords: [找 skill, 用哪个 skill, skill 检索, 技能检索, 技能路由, 该用哪个工具, 有没有现成的工具]\nversion: 1.0.0",
      "name": "skill_search",
      "description": "skill 检索：给一句话，找出该用哪个 skill，返回命中的 skill 描述和相对目录。"
    }
  ]
}
```

看点：`source` 就是**相对目录**，拿到后去读 `<source>/SKILL.md` 正文；
`description` 是 frontmatter 里那个字段，直接可读。

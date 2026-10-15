# 例：未命中

真实抓取的输出，不是手写的。

```
$ .venv/bin/python skill/rag/main.py recall "红烧肉怎么做才好吃"

查询: 红烧肉怎么做才好吃
阈值: 0.53
  2 二层 · 热 RAG（原始未清洗，已向量）: 未命中  (top1 0.3324, 库 375 条)
  3 三层 · 冷 RAG（完整记忆与知识）: 未命中  (top1 0.2269, 库 2 条)
两层都没命中
```

## JSON 形态

```json
{
  "query": "红烧肉怎么做才好吃",
  "tier": null,
  "tier_name": null,
  "hit": false,
  "threshold": 0.53,
  "trace": [
    {
      "tier": "2",
      "name": "二层 · 热 RAG（原始未清洗，已向量）",
      "state": "未命中",
      "count": 375,
      "best": 0.332421
    },
    {
      "tier": "3",
      "name": "三层 · 冷 RAG（完整记忆与知识）",
      "state": "未命中",
      "count": 2,
      "best": 0.226919
    }
  ],
  "results": []
}
```

看点：两层都 `未命中` 之后才 `hit: false`、`results` 空数组。
**这就是真没检索到**，不是出错 —— 拿到的模型应当老实说不知道。

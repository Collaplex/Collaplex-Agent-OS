# skill_search 回归用例

## 这组用例是干嘛的

回答一个问题：**换了模型 / 改了 frontmatter / 加了 skill 之后，还认不认得该用哪个？**

探针是 6 条"该命中"（指向某个具体 skill）+ 6 条"该不命中"（跟 skill 无关的日常话）。

## 怎么跑

```bash
# 1. 向量服务
.venv/bin/python skill/skill_search/scripts/embed_server.sh start

# 2. 逐条跑，看 top1 的 name 和 score
.venv/bin/python skill/skill_search/main.py find "<query>" -n 1 --json
```

## 判定标准

| 检查项 | 通过条件 |
|---|---|
| **top1 是不是对的 skill** | `name` 跟 `expect` 一致（硬指标） |
| **相关分数** | 不低于 `baseline` 太多（跌 > 0.05 要查原因） |
| **无关分数** | 明显低于相关侧，别跟相关侧糊在一起 |

## 实测基线（2026-10-05，语料 3 条：`rag` / `seek` / `skill_search`）

### 该命中

| id | 查询 | 期望 | 实测 top1 | 分数 |
|---|---|---|---|---|
| hit-01 | 我要查点资料 | `rag` | `skill/rag` | **0.7015** |
| hit-02 | 这个任务该用哪个技能 | `skill_search` | `skill/skill_search` | **0.7342** |
| hit-03 | 帮我一步步想清楚这个问题 | `seek` | `skill/seek` | **0.5669** |
| hit-04 | 找一份文档里的原文 | `rag` | `skill/rag` | **0.7107** |
| hit-05 | 把一段话向量化存起来 | `seek` | `skill/seek` | **0.5416** |
| hit-06 | 有没有现成的办法按描述找工具 | `skill_search` | `skill/skill_search` | **0.6082** |

### 该不命中

| id | 查询 | 实测 top1 | 分数 |
|---|---|---|---|
| miss-01 | 今天晚饭吃什么 | `seek` | 0.3411 |
| miss-02 | 明天的天气如何 | `seek` | 0.3884 |
| miss-03 | 帮我订一张机票 | `skill_search` | 0.4105 |
| miss-04 | 这首歌叫什么名字 | `skill_search` | 0.4286 |
| miss-05 | 怎么给多肉浇水 | `seek` | 0.2286 |
| miss-06 | 快递到哪了 | `rag` | 0.4440 |

**缝**：相关最低 0.5416 / 无关最高 0.4440 —— 交界在 **0.49** 附近，两侧余量约 ±0.05。

## 阈值为什么不设

配置里 `hit_threshold` 是 `null`（不过滤），理由**不是**分不开 —— 上表的分离度（±0.05）
比 rag 那边（±0.03）还宽。真正的理由是**语料只有 3 条**：

"无关最高 0.4440" 是在 3 个候选里挑最不相干的一个。skill 涨到几十个之后，
任何一句话都"总有最近的一个"，无关侧会被推上去，这个 0.49 就必须重标。

**现在想开**：`resources/skill_index.json` 把 `hit_threshold` 设成 `0.49` 即可，代码不用动。

## 加 skill 之后要做什么

1. 在 `skill/` 下建目录、写带 frontmatter 的 `SKILL.md`
2. 跑 `index`（全量重建，没变的复用向量，很快）
3. 跑一遍上面的探针表，看有没有把谁挤掉 —— **新 skill 的 description 写得跟老的全都很像时，
   最容易互相抢**。这就是为什么 frontmatter 要写具体，别写"通用助手"这种词

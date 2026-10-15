# 联网搜索 · 先看热库再出网

**用途**：要查外面的事（某网页写了什么、某说法有没有出处、某网址通不通）走 `skill/search`。流程：**先看热库有没有**（省一次出网）→ 没有再打 bing+百度拿候选 → 用**真浏览器**把页取回来 → 去壳留肉成正文 → 结果落热库备回查。

**用法（动作名就是中文那几个）**
- `./.venv/bin/python skill/search/main.py 搜 "关键词"`　bing+百度（跨站去重：标题 / 链接 / 摘要 / 来源）
- `… skill/search/main.py 取 "<url>"`　真浏览器取一页（html + 截图 + 状态码 + 错误分类）
- `… skill/search/main.py 正文 --save --url "<url>"`　HTML 去壳留肉 → 标题 + 正文段落（原文不改写，可顺手切片落库）
- `… skill/search/main.py 浏览器 start|stop|status`　管常驻浏览器（闲置超时看门狗）
- `… skill/search/main.py 截图 "<url>"`　只截一张整页图，回截图路径
- `… skill/search/main.py 热库 "关键词"`　只在热库里回查（省出网）
- `… skill/search/main.py find "网页取正文"`　查它的命令库（9 条）

**备注**
- ★ **只回原文片段与链接** —— 不复述、不改写、不做总结推理；取不到就**把具体报错带回来，不编内容**。
- 两表落冷库：`search_hot`（热库，按 TTL / 体积闸控制）与 `search_corpus`（语料层），建表用 `… skill/search/scripts/corpus.py schema`。
- 搜索这事在 web 问答里也一样：先热库、再出网、落库备查。

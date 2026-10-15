# -*- coding: utf-8 -*-
"""测老板定的三条切片路由是不是真的各走各的。

  ① 结构化文件 -> 按标记切（md 按标题 / py 按 def-class）
  ② 对话       -> 按一问一答切
  ③ 连续文本   -> 按语义切

判据不能只看"切出来多大" —— 得看它**走的是哪条**。这里用"切片边界认不认标记"来判:
  - 按标记切的, 边界落在标题/def
  - 按问答对切的, 边界落在 **用户**
  - 按语义切的, 边界落在句号(句子攒到相似度掉下去才断), 不认任何标记
"""
from __future__ import annotations

import sys
import urllib.request
import json as _json
from pathlib import Path

sys.path.insert(0, "/home/lou/桌面/collaplex_agent/skill/rag/scripts")
import chunker  # noqa: E402

项目根 = Path("/home/lou/桌面/collaplex_agent")


def 嵌入(文本: list[str]) -> list[list[float]]:
    """调本地嵌入服务(8199)。"""
    请求 = urllib.request.Request(
        "http://127.0.0.1:8199/v1/embeddings",
        data=_json.dumps({"input": 文本, "model": "qwen3-embedding"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(请求, timeout=120) as 响应:  # noqa: S310
        包 = _json.loads(响应.read())
    return [d["embedding"] for d in 包["data"]]


def 看(名: str, 片: list[str]) -> None:
    if not 片:
        print(f"  {名:<36} 空")
        return
    首 = [c.strip().splitlines()[0][:26] for c in 片 if c.strip()]
    标题 = sum(1 for x in 首 if x.startswith("#"))
    def线 = sum(1 for x in 首 if x.startswith(("def ", "class ", "async def ")))
    用户 = sum(1 for x in 首 if x.startswith("**用户**"))
    print(f"  {名:<36} {len(片):>3} 片   标题开头 {标题:>3}   def 开头 {def线:>3}   用户开头 {用户:>3}")


print("══ ① 结构化文件（按标记切）")
md = 项目根 / "skill/rag/SKILL.md"
看("SKILL.md 走 split_rules", chunker.split_rules(md.read_text(encoding="utf-8"), ".md", 800))
py = 项目根 / "skill/rag/scripts/chunker.py"
看("chunker.py 走 split_rules", chunker.split_rules(py.read_text(encoding="utf-8"), ".py", 800))

print()
print("══ ② 对话（按一问一答切）")
对话 = max((项目根 / "skill/rag/corpus/hermes-history").glob("*.md"), key=lambda p: p.stat().st_size)
看("对话走 split_file_semantic", [c for c, _ in chunker.split_file_semantic(str(对话), 800)])

print()
print("══ ③ 连续文本（按语义切）")
连续 = 项目根 / "skill/rag/scripts/_三路由测试文本.txt"
连续.write_text(
    "深度学习模型的训练通常需要大量标注数据。反向传播通过链式法则计算梯度，"
    "再交给优化器更新参数。学习率过大会震荡，过小则收敛缓慢。\n\n"
    "今天中午食堂的红烧肉偏咸，米饭倒是蒸得不错。下午想去操场跑几圈，"
    "但是天气预报说傍晚有雷阵雨，带伞比较稳妥。\n\n"
    "上海证券交易所的科创板对未盈利企业有特殊上市标准。注册制改革后，"
    "信息披露成为监管核心，中介机构的责任被显著加重。\n\n"
    "那只橘猫又蹲在窗台上了，尾巴一甩一甩的。它盯着楼下的麻雀看了很久，"
    "最后还是没有扑出去，转身跳下窗台去喝水了。\n\n"
    "分布式数据库的一致性模型有强一致、最终一致等几种。CAP 理论指出"
    "一致性、可用性、分区容错性三者不可兼得，实际系统只能做取舍。\n\n"
    "楼下便利店的关东煮涨价了，萝卜从两块变成两块五。店员说是因为"
    "最近进货成本高，冬天萝卜不好种，她也没办法。\n\n"
    "编译器的前端负责词法分析和语法分析，生成抽象语法树。后端做优化和"
    "目标代码生成。中间表示的设计质量直接决定优化能走多远。\n\n"
    "邻居家的小孩昨天学会了骑自行车，摔了三次终于掌握平衡。他爸爸在后面"
    "扶着车座跑了小半条街，累得直喘气，他妈妈在旁边拍手叫好。他爷爷搬了"
    "个小板凳坐在树荫下看着，手里摇着蒲扇，时不时喊一声慢点骑别摔着。\n\n"
    "量子计算里的退相干时间是衡量量子比特质量的核心指标之一，它决定了"
    "量子态能维持多久而不被环境噪声破坏。超导量子比特的退相干时间通常在"
    "几十到几百微秒之间，而离子阱方案能做得更长，但操作速度偏慢。\n\n"
    "小区门口的早餐摊最近换了老板，原来那对夫妻回老家了。新老板做的"
    "豆浆偏甜，油条倒是炸得酥脆。常来的几个老人说味道还行，就是出摊"
    "时间比原来晚了一刻钟，上班的人有点赶不上。\n\n"
    "集装箱船的载箱量用 TEU 衡量，一艘两万箱级别的船长度接近四百米。"
    "这类船的港口停靠需要专门的深水泊位和大型岸桥，装卸效率以每小时"
    "多少自然箱计。航线调度要考虑油价、运河费和港口拥堵。\n\n"
    "楼上的装修持续了三个星期，电钻声从早上八点准时响起。据说是在"
    "重做整体厨房，把原来的承重墙位置挪了。物业贴过一张整改通知，"
    "后来好像协商解决了，动静小了一些。\n\n"
    "铁路的道岔是列车换线的关键设备，高速道岔的尖轨可以在几十毫秒内"
    "完成转换。无砟轨道的沉降控制要求极严，路基施工完成后要静置观测"
    "相当长时间才能铺轨。寒冷地区的道岔还要配电加热融雪装置。",
    encoding="utf-8",
)
片 = [c for c, _ in chunker.split_file_semantic(str(连续), 800, 嵌入)]
看("连续文本走 split_file_semantic", 片)
print()
print("  ★ 按语义切的标志: 断点该落在『话题换』的地方（上面三段话题完全不相干）")
for i, c in enumerate(片, 1):
    print(f"     [{i}] {c.strip().splitlines()[0][:52]!r}")

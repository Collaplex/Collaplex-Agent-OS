"""检索降级路的回归测试 —— 嵌入服务挂了的时候, 不许再对用户说"我没有记忆"。

★ 这条回归的来由(2026-10-11 实测): 嵌入服务(:8199)被内核 OOM 杀了, 老板问
"你还记得之前那个做盒子的那个作业吗?", 检索整条 0 命中, 主 agent 就答
"不好意思, 我没有之前对话的记忆 —— 每次对话对我来说都是全新的"。
把**服务故障**说成了**能力缺失** —— 用户以为这机器不记事, 实际是服务没起。

所以这里量的两件事:
  ① 语义路不可用时**不能整条塌掉**: 要退到关键词兜底(ILIKE), 把字面命中的原文取回来;
  ② 退不下去也要把实况**带出去**(note/告警), 让主 agent 能照实说是服务的问题。

用法: ./.venv/bin/python tests/test_recall_degraded.py
"""

import json
import os
import pathlib
import subprocess
import sys
from typing import Any, cast

根 = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(根))
sys.path.insert(0, str(根 / "skill" / "rag" / "scripts"))

RECALL = 根 / "skill" / "rag" / "scripts" / "recall.py"
死端口 = "http://127.0.0.1:9/v1"  # 9 号端口是 discard, 没人听 —— 稳连不上
凑的词 = "纸盒外包装 作业"

通过 = 0
失败: list[str] = []


def 判(条件: bool, 说明: str) -> None:
    global 通过
    if 条件:
        通过 += 1
        print(f"  ok  {说明}")
    else:
        失败.append(说明)
        print(f"  ✗   {说明}")


def 跑检索(base_url: str | None) -> dict[str, Any]:
    env = dict(os.environ)
    if base_url:
        env["EMBEDDING_BASE_URL"] = base_url
    done = subprocess.run(
        [sys.executable, str(RECALL), 凑的词, "-n", "3", "--json"],
        capture_output=True, text=True, cwd=str(根), env=env, check=False, timeout=180,
    )
    raw = done.stdout
    起点 = raw.find("{")
    if 起点 < 0:
        raise AssertionError(f"没拿到 JSON (退出码 {done.returncode}): {raw[:300]}")
    return json.loads(raw[起点:])


def main() -> int:
    print("-- ① 语义路不可用(嵌入指到死端口) -> 关键词兜底")
    try:
        降 = 跑检索(死端口)
    except AssertionError as error:
        print(f"  ✗   {error}")
        return 1
    判(bool(降.get("hit")), "还是一条都不塌: hit=True")
    判(降.get("降级") == "关键词兜底", f"标了降级路: {降.get('降级')!r}")
    兜回 = cast(list[Any], 降.get("results") or [])
    判(len(兜回) > 0, f"字面捞回了 {len(兜回)} 条")
    说明 = str(降.get("note") or "")
    判("没走通" in 说明, f"note 说清了原因: {说明[:90]}")

    print("-- ② sub_agent 那层: 实况要带得出去")
    import sub_agent  # noqa: E402  (sys.path 插好之后再导)

    os.environ["EMBEDDING_BASE_URL"] = 死端口
    try:
        rag = json.loads((根 / "config" / "sub_agent.json").read_text(encoding="utf-8"))["rag"]
        hits = sub_agent.recall_memory([凑的词], dict(rag))
        告警 = sub_agent.取检索告警()
        块 = sub_agent.检索告警块()
    finally:
        os.environ.pop("EMBEDDING_BASE_URL", None)
    判(len(hits) > 0, f"检索记忆取回 {len(hits)} 条(靠兜底)")
    判(len(告警) > 0, "告警非空(不是静默)")
    判("不许说" in 块 and "我没有之前的记忆" in 块, "给主 agent 的硬话里点名禁了那句话")

    print("-- ③ 服务在的时候: 走语义路, 不许出降级标记")
    try:
        正 = 跑检索(None)
    except AssertionError as error:
        print(f"  ?   服务没起, 这步跳过: {error}")
        return 收尾()
    判(bool(正.get("hit")), "语义路命中")
    判(not 正.get("降级"), f"没有降级标记: {正.get('降级')!r}")
    return 收尾()


def 收尾() -> int:
    print()
    if 失败:
        print(f"FAIL 检索降级 {通过} 过 / {len(失败)} 败")
        for x in 失败:
            print(f"  - {x}")
        return 1
    print(f"OK 检索降级 {通过}/{通过}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""第一个程序: 用 openai 库调一次 API.

跑法:  .venv/bin/python mvp_os.py
前提:  本机派发网关起着 (cd ~/桌面/工作区/实验/llama派发面板 && ./启动.sh)
"""

import json
from pathlib import Path

from openai import OpenAI

# ---------------------------------------------------------------- 参数
BASE_URL = "http://127.0.0.1:8790/v1"  # 网关的 OpenAI 兼容入口
MODEL = "deepseek-v4-pro-9b"           # 模型别名
QUESTION = "一个笼子里鸡和兔共 35 个头、94 只脚, 鸡兔各几只? 只给数字."

# 网关是"单 key 派发"的设计, 没 key 会被挡在门外.
# key 由面板生成, 存在它自己的台账里 - 这里实时取一把, 不硬编码在代码里.
KEYS_FILE = Path.home() / "桌面/工作区/实验/llama派发面板/state/keys.json"
API_KEY = json.loads(KEYS_FILE.read_text(encoding="utf-8"))["keys"][0]["key"]

# ---------------------------------------------------------------- 客户端
# 地址 + key + 超时 交给客户端持有, 之后调用无需再传.
client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=180)

# ---------------------------------------------------------------- 调用
# 一次 chat 请求: 一条 user 消息进去, 一条 assistant 消息出来.
response = client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "user", "content": QUESTION}],
)

# ---------------------------------------------------------------- 出结果
message = response.choices[0].message

# 这个模型带思考. 思考在 reasoning_content 里 (不是 OpenAI 标准字段, SDK 收在 model_extra),
# 正文在 content 里. 两样分开取, 不要混.
reasoning = (message.model_extra or {}).get("reasoning_content", "")

print(f"思考: {reasoning}")
print(f"回答: {message.content}")

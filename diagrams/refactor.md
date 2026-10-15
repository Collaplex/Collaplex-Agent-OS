def main() -> None:
    while True:
        width = get_terminal_width()  # 获取终端宽度
        这边加上一个装饰条用来然后下一行写调用了哪些skill。   
        print(f"=" * width)
        user_message = input(">") # 示例用户消息
        if user_message == "/exit":
            print("已退出")
            break
        print(f"-" * width)
        """创建助手并发送示例消息。"""
        assistant = StreamingChatAssistant.from_env()
        _, _, stats = assistant.chat(user_message)

        if stats["tokens_per_second"] is not None:
            print(
                "Token 用量："
                f"输入 {stats['prompt_tokens']}，"
                f"输出 {stats['completion_tokens']}，"
                f"合计 {stats['total_tokens']}；"
                f"生成速度 {stats['tokens_per_second']:.2f} tokens/s"
            )
        else:
            print("Token 用量或生成速度不可用（接口未返回 usage 数据）。")
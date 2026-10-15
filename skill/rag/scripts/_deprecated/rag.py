def split_markdown_scanner(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)  # 保留换行符
    chunks: list[str] = []

    current_lines: list[str] = []
    in_code_block = False
    code_fence: str | None = None  # 记录 ``` 还是 ~~~

    for line in lines:
        stripped = line.lstrip()

        # ---------- 代码块状态 ----------
        if not in_code_block:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                # 进入代码块前，先把之前攒的内容存起来
                if current_lines:
                    chunks.append("".join(current_lines))
                    current_lines = []
                in_code_block = True
                code_fence = stripped[:3]
                current_lines.append(line)
                continue
        else:
            # 已经在代码块里
            current_lines.append(line)
            if code_fence is not None and stripped.startswith(code_fence):
                # 代码块结束，整块存入 chunks
                chunks.append("".join(current_lines))
                current_lines = []
                in_code_block = False
                code_fence = None
            continue

        # ---------- 标题状态 ----------
        if stripped.startswith("#"):
            # 遇到新标题，把之前攒的正文存起来
            if current_lines:
                chunks.append("".join(current_lines))
                current_lines = []
            current_lines.append(line)
            continue

        # ---------- 普通行 ----------
        current_lines.append(line)

    # 收尾：不要忘了最后一段
    if current_lines:
        chunks.append("".join(current_lines))

    return chunks
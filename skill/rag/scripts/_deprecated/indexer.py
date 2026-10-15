import os
import json
import hashlib
import numpy as np
from chunker import split_file

# ============================================================
# 哈希工具
# ============================================================

def file_hash(path, algo="sha256"):
    """算整个文件的哈希"""
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest()[:16]


def text_hash(text, algo="sha256"):
    """算一段文本的哈希"""
    return hashlib.new(algo, text.encode("utf-8")).hexdigest()[:16]


# ============================================================
# 建记录：切块 + 打标
# ============================================================

def build_records(files, chunk_size=800):
    """
    把文件列表切成块，生成记录列表（还没算向量）。
    """
    records = []

    for filepath in files:
        if not os.path.isfile(filepath):
            print(f"[跳过] 不存在: {filepath}")
            continue

        src_hash = file_hash(filepath)
        chunks = split_file(filepath, chunk_size)

        for i, chunk in enumerate(chunks):
            records.append({
                "id": f"{filepath}::{i}",
                "source": filepath,
                "source_hash": src_hash,
                "chunk_index": i,
                "chunk_hash": text_hash(chunk),
                "text": chunk,
                "char_count": len(chunk),
                "embedding": None,
            })

    return records


# ============================================================
# 算向量：批量 encode
# ============================================================

def embed_records(records, model, batch_size=32, show_progress=True):
    """
    给所有还没向量的记录算 embedding。
    已经有 embedding 的记录会跳过（方便增量更新）。
    """
    # 找出需要算向量的
    pending = [r for r in records if r.get("embedding") is None]
    if not pending:
        print("[embed] 所有记录都已有向量，跳过")
        return records

    texts = [r["text"] for r in pending]

    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=show_progress,
    )

    for r, emb in zip(pending, embeddings):
        r["embedding"] = emb.tolist()

    return records


# ============================================================
# 增量更新：根据哈希判断哪些文件变了
# ============================================================

def find_changed_files(files, old_records):
    """
    对比旧记录，找出内容变了的文件。
    返回 (changed_files, unchanged_files)
    """
    old_hashes = {}
    for r in old_records:
        old_hashes[r["source"]] = r["source_hash"]

    changed = []
    unchanged = []
    for f in files:
        if not os.path.isfile(f):
            continue
        h = file_hash(f)
        if old_hashes.get(f) != h:
            changed.append(f)
        else:
            unchanged.append(f)

    return changed, unchanged


# ============================================================
# 存 / 读 JSON
# ============================================================

def save_index(records, json_path):
    """把记录列表存成 JSON"""
    os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"[save] 已写入 {json_path}，共 {len(records)} 条")


def load_index(json_path):
    """从 JSON 读回记录列表"""
    if not os.path.exists(json_path):
        return []
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 对外入口：一条龙
# ============================================================

def build_index(files, model, json_path="index.json", chunk_size=800):
    """
    完整流程：
    1. 读取旧索引（如果有）
    2. 找出变了的文件
    3. 只重新切变了的文件，保留没变文件的旧记录
    4. 给新记录算向量
    5. 存 JSON
    """
    old_records = load_index(json_path)

    if old_records:
        changed, unchanged = find_changed_files(files, old_records)
        print(f"[增量] 变化: {len(changed)} 个，未变: {len(unchanged)} 个")

        # 保留没变文件的记录
        kept = [r for r in old_records if r["source"] in unchanged]
        # 重新切变了的文件
        new_records = build_records(changed, chunk_size)
        records = kept + new_records
    else:
        print("[全量] 没有旧索引，重新构建")
        records = build_records(files, chunk_size)

    # 算向量（只算 embedding 为 None 的）
    records = embed_records(records, model)

    save_index(records, json_path)
    return records


def main():
        # 1. 加载 embedding 模型
    model = SentenceTransformer("BAAI/bge-small-zh-v1.5")

    # 2. 准备文件列表
    files = [
        "docs/skill.md",
        "docs/pi.md",
        "docs/descartes.md",
    ]

    # 3. 一条龙构建索引
    records = build_index(files, model, json_path="index.json")

    print(f"总记录数: {len(records)}")
    print(f"第一条: {records[0]['id']}")
    print(f"向量维度: {len(records[0]['embedding'])}")
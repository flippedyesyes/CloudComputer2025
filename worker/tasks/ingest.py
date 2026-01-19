import json
import os
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from bson import ObjectId
from groq import Groq
from openai import OpenAI
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "learning_agent")
KIMI_MODEL = os.getenv("KIMI_MODEL", "moonshot-v1-8k")
SUMMARY_MAX_CHARS = int(os.getenv("SUMMARY_MAX_CHARS", "10000"))
SUMMARY_CHUNK_CHARS = int(os.getenv("SUMMARY_CHUNK_CHARS", "4000"))

# M2：知识树生成输入长度（避免超长）
TREE_CONTEXT_MAX_CHARS = int(os.getenv("TREE_CONTEXT_MAX_CHARS", "12000"))


def _get_db():
    client = MongoClient(MONGO_URI)
    return client[MONGO_DB_NAME]


def _materials_col(db):
    return db["materials"]


def _material_texts_col(db):
    return db["material_texts"]


def _knowledge_nodes_col(db):
    return db["knowledge_nodes"]


def _split_text(text: str, max_chars: int = 2000) -> List[str]:
    text = text.strip()
    if not text:
        return []
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _download_to_temp(url: str) -> Path:
    suffix = Path(url).suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fp:
        urllib.request.urlretrieve(url, fp.name)
        return Path(fp.name)


def _resolve_file_path(file_url: str) -> Path:
    if file_url.startswith("http://") or file_url.startswith("https://"):
        return _download_to_temp(file_url)
    return Path(file_url)


def _extract_text_with_kimi(file_path: Path) -> str:
    api_key = os.getenv("MOONSHOT_API_KEY")
    if not api_key:
        raise RuntimeError("MOONSHOT_API_KEY is required for pdf/docx ingest")
    client = OpenAI(api_key=api_key, base_url="https://api.moonshot.cn/v1")
    file_object = client.files.create(file=file_path, purpose="file-extract")
    return client.files.content(file_id=file_object.id).text


def _extract_text_with_groq(file_path: Path) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is required for audio ingest")
    client = Groq(api_key=api_key)
    with file_path.open("rb") as file:
        transcription = client.audio.transcriptions.create(
            file=(file_path.name, file.read()),
            model="whisper-large-v3",
            temperature=0,
            response_format="verbose_json",
        )
    return transcription.text


def _call_kimi_chat(prompt: str, system: str) -> str:
    api_key = os.getenv("MOONSHOT_API_KEY")
    if not api_key:
        raise RuntimeError("MOONSHOT_API_KEY is required")
    client = OpenAI(api_key=api_key, base_url="https://api.moonshot.cn/v1")
    resp = client.chat.completions.create(
        model=KIMI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return (resp.choices[0].message.content or "").strip()


def _summarize_text(text: str, target_chars: int) -> str:
    chunks = _split_text(text, SUMMARY_CHUNK_CHARS)
    summaries = []
    for idx, chunk in enumerate(chunks, 1):
        prompt = (
            "Summarize the following content into concise bullet points with clear section hints. "
            "Keep it brief (roughly 400-600 chars).\n"
            f"Chunk {idx}/{len(chunks)}:\n{chunk}"
        )
        summaries.append(_call_kimi_chat(prompt, system="You summarize study materials."))
    merged = "\n".join(summaries)
    if len(merged) <= target_chars:
        return merged
    prompt = (
        "Compress the following summary into a structured outline within "
        f"{target_chars} characters.\n"
        f"{merged}"
    )
    return _call_kimi_chat(prompt, system="You summarize study materials.")


def _maybe_build_summary(text: str) -> str:
    if len(text) <= SUMMARY_MAX_CHARS:
        return ""
    try:
        return _summarize_text(text, SUMMARY_MAX_CHARS)
    except Exception as exc:
        print(f"[ingest] summary skipped: {exc}")
        return ""


def _strip_code_fence(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return s


def _build_knowledge_tree(text: str) -> List[Dict]:
    """
    M2：生成章/节树（level=1/2），输出 JSON 数组：
    [
      {"title":"第1章 ...","level":1,"order":0},
      {"title":"1.1 ...","level":2,"order":0,"parent_order":0}
    ]
    """
    ctx = text.strip()[:TREE_CONTEXT_MAX_CHARS]
    prompt = (
        "从以下学习资料中，提取“章节目录结构”。\n"
        "要求：\n"
        "1) 只输出 JSON 数组；不要输出任何解释文字。\n"
        "2) 仅做两层：章(level=1) 与 节(level=2)。\n"
        "3) 每个对象字段：title(str), level(int), order(int), parent_order(int, 可选，仅节需要)。\n"
        "4) order / parent_order 从 0 开始递增。\n"
        "5) title 必须短且像目录（不要整段句子）。\n\n"
        f"资料内容：\n{ctx}\n"
    )
    raw = _call_kimi_chat(prompt, system="You are an information extraction engine. Output JSON only.")
    data = json.loads(_strip_code_fence(raw))
    if not isinstance(data, list):
        raise ValueError("knowledge tree must be a JSON array")
    # 轻校验
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("each node must be object")
        if "title" not in item or "level" not in item or "order" not in item:
            raise ValueError("node missing required fields")
        if int(item["level"]) not in (1, 2):
            raise ValueError("level must be 1 or 2")
    return data


def ingest_material(material_id: str):
    db = _get_db()
    materials = _materials_col(db)
    material_texts = _material_texts_col(db)
    knowledge_nodes = _knowledge_nodes_col(db)

    material = materials.find_one({"_id": ObjectId(material_id)})
    if not material:
        print(f"[ingest] material not found: {material_id}")
        return

    materials.update_one({"_id": ObjectId(material_id)}, {"$set": {"status": "processing"}})

    file_url = material.get("file_url")
    source_type = material.get("source_type")
    notebook_id = material.get("notebook_id")
    if not file_url:
        materials.update_one(
            {"_id": ObjectId(material_id)},
            {"$set": {"status": "failed", "error_message": "file_url missing"}},
        )
        return

    temp_path: Path | None = None
    try:
        file_path = _resolve_file_path(file_url)
        temp_path = file_path if file_url.startswith("http") else None
        if not file_path.exists():
            raise FileNotFoundError(f"file not found: {file_path}")

        if source_type in {"pdf", "docx"}:
            text = _extract_text_with_kimi(file_path)
        elif source_type == "audio":
            text = _extract_text_with_groq(file_path)
        else:
            raise RuntimeError(f"unsupported source_type: {source_type}")

        chunks = _split_text(text)
        if not chunks:
            raise RuntimeError("extracted text is empty")

        now = datetime.utcnow()
        material_texts.delete_many({"material_id": material_id, "kind": "full"})
        docs = [
            {"material_id": material_id, "kind": "full", "chunk_index": idx, "text": chunk, "created_at": now}
            for idx, chunk in enumerate(chunks)
        ]
        material_texts.insert_many(docs)

        summary_text = _maybe_build_summary(text)
        summary_count = 0
        if summary_text:
            summary_chunks = _split_text(summary_text)
            if summary_chunks:
                material_texts.delete_many({"material_id": material_id, "kind": "summary"})
                summary_docs = [
                    {"material_id": material_id, "kind": "summary", "chunk_index": idx, "text": chunk, "created_at": now}
                    for idx, chunk in enumerate(summary_chunks)
                ]
                material_texts.insert_many(summary_docs)
                summary_count = len(summary_chunks)

        # ---------------- M2 新增：生成知识体系树并入库 ----------------
        # 输入优先用 summary（更像目录提取），没有 summary 就用原文前一段
        tree_source = summary_text or text
        try:
            tree = _build_knowledge_tree(tree_source)
            knowledge_nodes.delete_many({"material_id": material_id})
            chapter_id_by_order: Dict[int, ObjectId] = {}

            # --- M2 加强：给每个章/节绑定 source_chunk_indexes（用于按知识区域出题）---
            # 这里做一个“可用且稳定”的粗绑定：
            # - 章节点：按章数把全文 chunks 均分成连续区间
            # - 节节点：在所属章区间内再均分
            num_chunks = len(chunks)
            chapters = sorted([it for it in tree if int(it.get("level", 0)) == 1], key=lambda x: int(x.get("order", 0)))
            chapter_ranges: Dict[int, tuple[int, int]] = {}
            if chapters and num_chunks > 0:
                c = len(chapters)
                for idx, ch in enumerate(chapters):
                    order = int(ch.get("order", idx))
                    start = int((idx * num_chunks) / c)
                    end = int(((idx + 1) * num_chunks) / c) - 1
                    if end < start:
                        end = start
                    chapter_ranges[order] = (start, min(end, num_chunks - 1))

            # 预先整理每个章下的节
            sections_by_parent: Dict[int, List[Dict]] = {}
            for it in tree:
                if int(it.get("level", 0)) != 2:
                    continue
                po = int(it.get("parent_order", 0))
                sections_by_parent.setdefault(po, []).append(it)
            for po, secs in sections_by_parent.items():
                sections_by_parent[po] = sorted(secs, key=lambda x: int(x.get("order", 0)))

            inserts = []
            for item in tree:
                level = int(item["level"])
                order = int(item["order"])
                title = str(item["title"]).strip()
                if level == 1:
                    rng = chapter_ranges.get(order)
                    src = list(range(rng[0], rng[1] + 1)) if rng else []
                    doc = {
                        "material_id": material_id,
                        "notebook_id": notebook_id,
                        "parent_id": None,
                        "title": title,
                        "level": 1,
                        "order": order,
                        "source_chunk_indexes": src,
                        "created_at": now,
                    }
                    res = knowledge_nodes.insert_one(doc)
                    chapter_id_by_order[order] = res.inserted_id
                else:
                    parent_order = int(item.get("parent_order", 0))
                    parent_id = chapter_id_by_order.get(parent_order)

                    # 在章区间内均分节区间
                    src: List[int] = []
                    rng = chapter_ranges.get(parent_order)
                    secs = sections_by_parent.get(parent_order) or []
                    if rng and secs:
                        start, end = rng
                        length = end - start + 1
                        s = len(secs)
                        idx = next((i for i, sitem in enumerate(secs) if int(sitem.get("order", -1)) == order), 0)
                        sub_start = start + int((idx * length) / s)
                        sub_end = start + int(((idx + 1) * length) / s) - 1
                        if sub_end < sub_start:
                            sub_end = sub_start
                        sub_end = min(sub_end, end)
                        src = list(range(sub_start, sub_end + 1))

                    doc = {
                        "material_id": material_id,
                        "notebook_id": notebook_id,
                        "parent_id": str(parent_id) if parent_id else None,
                        "title": title,
                        "level": 2,
                        "order": order,
                        "source_chunk_indexes": src,
                        "created_at": now,
                    }
                    inserts.append(doc)

            if inserts:
                knowledge_nodes.insert_many(inserts)
        except Exception as exc:
            # 不让知识树失败拖死 ingest：M2 允许降级
            print(f"[ingest] knowledge tree skipped: {exc}")

        materials.update_one(
            {"_id": ObjectId(material_id)},
            {"$set": {"status": "ready", "text_chunk_count": len(chunks), "summary_chunk_count": summary_count}},
        )
    except Exception as exc:
        materials.update_one(
            {"_id": ObjectId(material_id)},
            {"$set": {"status": "failed", "error_message": str(exc)}},
        )
        print(f"[ingest] failed: {exc}")
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

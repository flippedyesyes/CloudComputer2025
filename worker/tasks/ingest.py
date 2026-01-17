import os
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import List

from bson import ObjectId
from groq import Groq
from openai import OpenAI
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "learning_agent")
KIMI_MODEL = os.getenv("KIMI_MODEL", "moonshot-v1-8k")
SUMMARY_MAX_CHARS = int(os.getenv("SUMMARY_MAX_CHARS", "10000"))
SUMMARY_CHUNK_CHARS = int(os.getenv("SUMMARY_CHUNK_CHARS", "4000"))


def _get_db():
    client = MongoClient(MONGO_URI)
    return client[MONGO_DB_NAME]


def _materials_col(db):
    return db["materials"]


def _material_texts_col(db):
    return db["material_texts"]


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


def _call_kimi_chat(prompt: str) -> str:
    api_key = os.getenv("MOONSHOT_API_KEY")
    if not api_key:
        raise RuntimeError("MOONSHOT_API_KEY is required for summary")
    client = OpenAI(api_key=api_key, base_url="https://api.moonshot.cn/v1")
    resp = client.chat.completions.create(
        model=KIMI_MODEL,
        messages=[
            {"role": "system", "content": "You summarize study materials."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


def _summarize_text(text: str, target_chars: int) -> str:
    chunks = _split_text(text, SUMMARY_CHUNK_CHARS)
    summaries = []
    for idx, chunk in enumerate(chunks, 1):
        prompt = (
            "Summarize the following content into concise bullet points with clear section hints. "
            "Keep it brief (roughly 400-600 chars).\n"
            f"Chunk {idx}/{len(chunks)}:\n{chunk}"
        )
        summaries.append(_call_kimi_chat(prompt))
    merged = "\n".join(summaries)
    if len(merged) <= target_chars:
        return merged
    prompt = (
        "Compress the following summary into a structured outline within "
        f"{target_chars} characters.\n"
        f"{merged}"
    )
    return _call_kimi_chat(prompt)


def _maybe_build_summary(text: str) -> str:
    if len(text) <= SUMMARY_MAX_CHARS:
        return ""
    try:
        return _summarize_text(text, SUMMARY_MAX_CHARS)
    except Exception as exc:
        print(f"[ingest] summary skipped: {exc}")
        return ""


def ingest_material(material_id: str):
    db = _get_db()
    materials = _materials_col(db)
    material_texts = _material_texts_col(db)

    material = materials.find_one({"_id": ObjectId(material_id)})
    if not material:
        print(f"[ingest] material not found: {material_id}")
        return

    materials.update_one(
        {"_id": ObjectId(material_id)},
        {"$set": {"status": "processing"}},
    )

    file_url = material.get("file_url")
    source_type = material.get("source_type")
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
            {
                "material_id": material_id,
                "kind": "full",
                "chunk_index": idx,
                "text": chunk,
                "created_at": now,
            }
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
                    {
                        "material_id": material_id,
                        "kind": "summary",
                        "chunk_index": idx,
                        "text": chunk,
                        "created_at": now,
                    }
                    for idx, chunk in enumerate(summary_chunks)
                ]
                material_texts.insert_many(summary_docs)
                summary_count = len(summary_chunks)

        materials.update_one(
            {"_id": ObjectId(material_id)},
            {
                "$set": {
                    "status": "ready",
                    "text_chunk_count": len(chunks),
                    "summary_chunk_count": summary_count,
                }
            },
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

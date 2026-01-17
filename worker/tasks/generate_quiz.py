import json
import os
from datetime import datetime
from typing import Any, Dict, List

from bson import ObjectId
from openai import OpenAI
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "learning_agent")
KIMI_API_KEY = os.getenv("MOONSHOT_API_KEY")
KIMI_MODEL = os.getenv("KIMI_MODEL", "moonshot-v1-8k")
CONTEXT_MAX_CHARS = int(os.getenv("CONTEXT_MAX_CHARS", "10000"))


def _get_db():
    client = MongoClient(MONGO_URI)
    return client[MONGO_DB_NAME]


def _quizzes_col(db):
    return db["quizzes"]


def _questions_col(db):
    return db["questions"]


def _material_texts_col(db):
    return db["material_texts"]


def _load_material_texts(db, material_ids: List[str], max_chars: int) -> str:
    summary = _load_material_texts_by_kind(db, material_ids, "summary", max_chars)
    if summary:
        return summary
    return _load_material_texts_by_kind(db, material_ids, "full", max_chars)


def _load_material_texts_by_kind(
    db, material_ids: List[str], kind: str, max_chars: int
) -> str:
    collected: List[str] = []
    total = 0
    for material_id in material_ids:
        cursor = _material_texts_col(db).find(
            {"material_id": material_id, "kind": kind}
        ).sort("chunk_index", 1)
        for doc in cursor:
            chunk = doc.get("text", "")
            if not chunk:
                continue
            if total + len(chunk) > max_chars:
                break
            collected.append(chunk)
            total += len(chunk)
        if total >= max_chars:
            break
    return "\n".join(collected)


def _call_kimi(prompt: str) -> str:
    if not KIMI_API_KEY:
        raise RuntimeError("MOONSHOT_API_KEY is required for quiz generation")
    client = OpenAI(api_key=KIMI_API_KEY, base_url="https://api.moonshot.cn/v1")
    resp = client.chat.completions.create(
        model=KIMI_MODEL,
        messages=[
            {"role": "system", "content": "You are a quiz generator. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return text


def _parse_questions(raw: str) -> List[Dict[str, Any]]:
    cleaned = _strip_code_fence(raw)
    data = json.loads(cleaned)
    if isinstance(data, dict) and "questions" in data:
        data = data["questions"]
    if not isinstance(data, list):
        raise ValueError("questions should be a list")
    return data


def _validate_questions(questions: List[Dict[str, Any]], expected_count: int) -> None:
    if not questions:
        raise ValueError("empty questions")
    if expected_count and len(questions) != expected_count:
        raise ValueError("question count mismatch")
    for q in questions:
        if q.get("type") not in {"mcq", "blank", "short"}:
            raise ValueError("invalid question type")
        if not q.get("stem"):
            raise ValueError("missing stem")
        if not q.get("answer_key"):
            raise ValueError("missing answer_key")
        if q.get("difficulty") not in {"L1", "L2", "L3"}:
            raise ValueError("invalid difficulty")
        if q["type"] == "mcq":
            options = q.get("options") or []
            if not isinstance(options, list) or len(options) < 3:
                raise ValueError("mcq options invalid")
        if q["type"] == "short" and not q.get("rubric"):
            raise ValueError("short answer missing rubric")


def generate_quiz(quiz_id: str):
    db = _get_db()
    quiz = _quizzes_col(db).find_one({"_id": ObjectId(quiz_id)})
    if not quiz:
        print(f"[generate_quiz] quiz not found: {quiz_id}")
        return

    _quizzes_col(db).update_one({"_id": ObjectId(quiz_id)}, {"$set": {"status": "processing"}})

    material_ids = quiz.get("material_ids", [])
    num_questions = int(quiz.get("num_questions", 5))
    type_mix = quiz.get("type_mix") or {"mcq": 0.6, "short": 0.4}
    difficulty_mix = quiz.get("difficulty_mix") or {"L1": 0.4, "L2": 0.4, "L3": 0.2}

    try:
        context = _load_material_texts(db, material_ids, CONTEXT_MAX_CHARS)
        if not context:
            raise RuntimeError("no material text available")

        prompt = (
            "Generate questions based on the study material.\n"
            f"Total questions: {num_questions}\n"
            f"Type mix: {json.dumps(type_mix)}\n"
            f"Difficulty mix: {json.dumps(difficulty_mix)}\n"
            "Return JSON array. Each item fields:\n"
            "- type: mcq, blank, or short\n"
            "- stem: question text\n"
            "- options: array (mcq only)\n"
            "- answer_key: correct option letter or reference answer\n"
            "- rubric: scoring rubric (short only)\n"
            "- difficulty: L1/L2/L3\n"
            "- knowledge_points: array of strings (key concepts)\n"
            "- analysis: short explanation for the answer\n"
            "For blank questions, use stem with a blank like '____' and provide the exact answer_key.\n"
            "Material:\n"
            f"{context}\n"
        )
        raw = _call_kimi(prompt)
        questions = _parse_questions(raw)
        _validate_questions(questions, num_questions)

        now = datetime.utcnow()
        docs = []
        for q in questions:
            knowledge_points = q.get("knowledge_points")
            if not isinstance(knowledge_points, list):
                knowledge_points = []
            analysis = q.get("analysis") or q.get("explanation") or ""
            doc = {
                "quiz_id": quiz_id,
                "type": q["type"],
                "stem": q["stem"],
                "options": q.get("options"),
                "answer_key": q["answer_key"],
                "rubric": q.get("rubric"),
                "difficulty": q["difficulty"],
                "material_ids": material_ids,
                "knowledge_points": knowledge_points,
                "analysis": analysis,
                "created_at": now,
            }
            docs.append(doc)
        result = _questions_col(db).insert_many(docs)
        question_ids = [str(_id) for _id in result.inserted_ids]

        _quizzes_col(db).update_one(
            {"_id": ObjectId(quiz_id)},
            {"$set": {"status": "ready", "question_ids": question_ids}},
        )
    except Exception as exc:
        _quizzes_col(db).update_one(
            {"_id": ObjectId(quiz_id)},
            {"$set": {"status": "failed", "error_message": str(exc)}},
        )
        print(f"[generate_quiz] failed: {exc}")

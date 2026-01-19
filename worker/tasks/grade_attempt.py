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


def _get_db():
    client = MongoClient(MONGO_URI)
    return client[MONGO_DB_NAME]


def _attempts_col(db):
    return db["attempts"]


def _quizzes_col(db):
    return db["quizzes"]


def _questions_col(db):
    return db["questions"]


def _mistakes_col(db):
    return db["mistakes"]


def _mastery_col(db):
    return db["mastery"]


def _call_kimi(prompt: str) -> str:
    if not KIMI_API_KEY:
        raise RuntimeError("MOONSHOT_API_KEY is required for grading")
    client = OpenAI(api_key=KIMI_API_KEY, base_url="https://api.moonshot.cn/v1")
    resp = client.chat.completions.create(
        model=KIMI_MODEL,
        messages=[
            {"role": "system", "content": "You are a fair grader. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return text


def _parse_grade(raw: str) -> Dict[str, Any]:
    cleaned = _strip_code_fence(raw)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("grading result must be an object")
    return data


def _grade_short_answer(question: Dict[str, Any], answer: Any) -> Dict[str, Any]:
    rubric = question.get("rubric", "")
    reference = question.get("answer_key", "")
    knowledge_points = question.get("knowledge_points", [])
    prompt = (
        "Grade the student's short answer based on the rubric and reference answer.\n"
        "Return JSON with fields: score (0-1), is_correct (true/false), "
        "missing_points (array of strings), error_tags (array of strings), "
        "error_analysis (string), feedback (string).\n"
        f"Question: {question['stem']}\n"
        f"Rubric: {rubric}\n"
        f"Reference answer: {reference}\n"
        f"Knowledge points: {knowledge_points}\n"
        f"Student answer: {answer}\n"
    )
    raw = _call_kimi(prompt)
    result = _parse_grade(raw)
    if "score" not in result:
        raise ValueError("grading result missing score")
    return result


def _grade_mcq(question: Dict[str, Any], answer: Any) -> Dict[str, Any]:
    correct = str(question.get("answer_key", "")).strip()
    given = str(answer or "").strip()
    is_correct = given.lower() == correct.lower()
    # 注意：M3 才需要 TutorCheck 防泄露；M2 这里保持 M1 行为
    feedback = "答案正确。" if is_correct else f"答案错误。正确答案为 {correct}。"
    return {
        "score": 1.0 if is_correct else 0.0,
        "is_correct": is_correct,
        "missing_points": [],
        "error_tags": [] if is_correct else ["选择题错误"],
        "error_analysis": "" if is_correct else "选项不正确。",
        "feedback": feedback,
    }


def _grade_blank(question: Dict[str, Any], answer: Any) -> Dict[str, Any]:
    correct = str(question.get("answer_key", "")).strip()
    given = str(answer or "").strip()
    if correct and given and given.lower() == correct.lower():
        return {
            "score": 1.0,
            "is_correct": True,
            "missing_points": [],
            "error_tags": [],
            "error_analysis": "",
            "feedback": "答案正确。",
        }
    result = _grade_short_answer(question, answer)
    if not result.get("is_correct", False):
        result.setdefault("error_tags", []).append("填空题错误")
    return result


def _update_mistakes(
    db,
    student_id: str,
    notebook_id: str,
    question_id: str,
    error_tags: List[str],
    error_analysis: str,
    knowledge_points: List[str],
):
    _mistakes_col(db).update_one(
        {"student_id": student_id, "question_id": question_id},
        {
            "$setOnInsert": {"notebook_id": notebook_id},
            "$set": {"last_wrong_at": datetime.utcnow(), "last_error_analysis": error_analysis},
            "$inc": {"wrong_count": 1},
            "$addToSet": {
                "error_tags": {"$each": error_tags},
                "knowledge_points": {"$each": knowledge_points},
            },
        },
        upsert=True,
    )


def _update_mastery(db, student_id: str, notebook_id: str, node_ids: List[str], is_correct: bool):
    # IMPORTANT (M2): update only the nodes this question is tagged with.
    # Children mastery must be independent; parent mastery is computed as an aggregate
    # over children in the knowledge-tree endpoint.
    if not node_ids:
        return
    now = datetime.utcnow()
    for node_id in node_ids:
        q = {"student_id": student_id, "node_id": node_id, "notebook_id": notebook_id}
        inc = {"seen": 1, "correct": 1 if is_correct else 0, "wrong": 0 if is_correct else 1}
        _mastery_col(db).update_one(
            q,
            {"$inc": inc, "$set": {"updated_at": now}, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        doc = _mastery_col(db).find_one(q, {"seen": 1, "correct": 1})
        seen = int((doc or {}).get("seen", 0) or 0)
        correct = int((doc or {}).get("correct", 0) or 0)
        score = (correct / seen) if seen > 0 else 0.0
        _mastery_col(db).update_one(q, {"$set": {"mastery_score": float(score)}})


def grade_attempt(attempt_id: str):
    db = _get_db()
    attempt = _attempts_col(db).find_one({"_id": ObjectId(attempt_id)})
    if not attempt:
        print(f"[grade_attempt] attempt not found: {attempt_id}")
        return

    _attempts_col(db).update_one({"_id": ObjectId(attempt_id)}, {"$set": {"status": "processing"}})

    quiz = _quizzes_col(db).find_one({"_id": ObjectId(attempt["quiz_id"])})
    if not quiz:
        _attempts_col(db).update_one(
            {"_id": ObjectId(attempt_id)},
            {"$set": {"status": "failed", "error_message": "quiz not found"}},
        )
        return

    questions = list(_questions_col(db).find({"quiz_id": attempt["quiz_id"]}))
    answers = attempt.get("answers", {})

    grading_details = []
    total_score = 0.0
    try:
        for q in questions:
            qid = str(q["_id"])
            answer = answers.get(qid)

            knowledge_points = q.get("knowledge_points", [])
            node_ids = q.get("node_ids", [])  # M2：绑定的章节/知识点

            if q.get("type") == "short":
                result = _grade_short_answer(q, answer)
            elif q.get("type") == "blank":
                result = _grade_blank(q, answer)
            else:
                result = _grade_mcq(q, answer)

            score_value = float(result.get("score", 0.0) or 0.0)
            is_correct = bool(result.get("is_correct", False))
            mistake_added = not is_correct
            total_score += score_value

            grading_details.append(
                {
                    "question_id": qid,
                    "result": result,
                    "score": score_value,
                    "is_correct": is_correct,
                    "mistake_added": mistake_added,
                    "knowledge_points": knowledge_points,
                    "node_ids": node_ids,
                    "analysis": q.get("analysis"),
                }
            )

            if mistake_added:
                _update_mistakes(
                    db,
                    attempt.get("student_id", "demo_user"),
                    quiz.get("notebook_id"),
                    qid,
                    result.get("error_tags", []),
                    result.get("error_analysis", ""),
                    knowledge_points,
                )

            # ---------------- M2 新增：回写 mastery ----------------
            _update_mastery(
                db,
                student_id=attempt.get("student_id", "demo_user"),
                notebook_id=quiz.get("notebook_id"),
                node_ids=node_ids,
                is_correct=is_correct,
            )

        _attempts_col(db).update_one(
            {"_id": ObjectId(attempt_id)},
            {"$set": {"status": "done", "score": total_score, "grading": grading_details}},
        )
    except Exception as exc:
        _attempts_col(db).update_one(
            {"_id": ObjectId(attempt_id)},
            {"$set": {"status": "failed", "error_message": str(exc)}},
        )
        print(f"[grade_attempt] failed: {exc}")

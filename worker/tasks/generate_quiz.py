import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from openai import OpenAI
from pymongo import MongoClient

from checkers.gate import run_with_checker
from checkers.quiz_check import QuizCheck
from checkers.base import CheckStatus

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


def _knowledge_nodes_col(db):
    return db["knowledge_nodes"]


def _get_descendants(db, root_node_id: str) -> List[Dict[str, Any]]:
    """Return all descendant nodes including the root.

    Used for M2 mastery: each question should be tagged to a specific (sub)knowledge node
    so that children mastery are independent. Parent mastery will be aggregated on read.
    """
    if not root_node_id:
        return []
    # BFS over parent_id links; parent_id is stored as string id.
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    queue: List[str] = [root_node_id]
    seen.add(root_node_id)
    while queue:
        cur = queue.pop(0)
        node = _knowledge_nodes_col(db).find_one({"_id": ObjectId(cur)})
        if node:
            out.append(
                {
                    "id": str(node.get("_id")),
                    "title": node.get("title"),
                    "parent_id": node.get("parent_id"),
                }
            )
        for row in _knowledge_nodes_col(db).find({"parent_id": cur}, {"_id": 1}):
            cid = str(row.get("_id"))
            if cid and cid not in seen:
                seen.add(cid)
                queue.append(cid)
    return out


def _leaf_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pick leaf nodes from a flat list based on parent links."""
    if not nodes:
        return []
    children_of = {}
    for n in nodes:
        pid = n.get("parent_id")
        if pid:
            children_of.setdefault(pid, 0)
            children_of[pid] += 1
    leaves = [n for n in nodes if children_of.get(n.get("id"), 0) == 0]
    # If tree is a single node, treat it as leaf.
    return leaves or nodes


# =========================
# Context loading (M1)
# =========================

def _load_material_texts(
    db,
    material_ids: List[str],
    max_chars: int,
) -> str:
    """
    M2 仍然使用 M1 的全文 / summary 作为 context，
    章节限制通过 prompt 约束（而不是切 chunk）
    """
    summary = _load_material_texts_by_kind(db, material_ids, "summary", max_chars)
    if summary:
        return summary
    return _load_material_texts_by_kind(db, material_ids, "full", max_chars)


def _load_material_texts_for_chunk_indexes(
    db,
    material_id: str,
    chunk_indexes: List[int],
    max_chars: int,
) -> str:
    """Load only specific chunks (used for M2 node-scoped quiz generation)."""
    if not chunk_indexes:
        return ""
    collected: List[str] = []
    total = 0
    cursor = (
        _material_texts_col(db)
        .find({"material_id": material_id, "kind": "full", "chunk_index": {"$in": chunk_indexes}})
        .sort("chunk_index", 1)
    )
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
    # fallback to summary if full chunks missing
    if not collected:
        cursor = (
            _material_texts_col(db)
            .find({"material_id": material_id, "kind": "summary", "chunk_index": {"$in": chunk_indexes}})
            .sort("chunk_index", 1)
        )
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


def _load_material_texts_by_kind(
    db, material_ids: List[str], kind: str, max_chars: int
) -> str:
    collected: List[str] = []
    total = 0
    for material_id in material_ids:
        cursor = (
            _material_texts_col(db)
            .find({"material_id": material_id, "kind": kind})
            .sort("chunk_index", 1)
        )
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
    # NOTE:
    # LLMs occasionally return a different number of questions than requested.
    # For a smoother demo experience, we don't fail the whole job on count mismatch.
    # The caller will slice or accept a smaller set.
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


# =========================
# Main job
# =========================

def generate_quiz(quiz_id: str):
    db = _get_db()
    quiz = _quizzes_col(db).find_one({"_id": ObjectId(quiz_id)})
    if not quiz:
        print(f"[generate_quiz] quiz not found: {quiz_id}")
        return

    _quizzes_col(db).update_one(
        {"_id": ObjectId(quiz_id)}, {"$set": {"status": "processing"}}
    )

    material_ids = quiz.get("material_ids", [])
    num_questions = int(quiz.get("num_questions", 5))
    type_mix = quiz.get("type_mix") or {"mcq": 0.6, "short": 0.4}
    difficulty_mix = quiz.get("difficulty_mix") or {"L1": 0.4, "L2": 0.4, "L3": 0.2}

    # === M2：章节信息（统一字段名：node_id）===
    node_id = quiz.get("node_id")
    # NOTE: We will tag each question with a *specific* node_id (usually a leaf under this node)
    # so that children mastery are independent.
    fallback_node_ids = [node_id] if node_id else []

    node_title: Optional[str] = None
    node_chunk_indexes: List[int] = []
    node_material_id: Optional[str] = None
    if node_id:
        node = _knowledge_nodes_col(db).find_one({"_id": ObjectId(node_id)})
        if node:
            node_title = node.get("title")
            node_material_id = node.get("material_id")
            idxs = node.get("source_chunk_indexes") or []
            if isinstance(idxs, list):
                node_chunk_indexes = [int(x) for x in idxs if str(x).isdigit()]

    # Build candidate leaf nodes under the selected node for per-child mastery.
    leaf_candidates: List[Dict[str, Any]] = []
    leaf_title_to_id: Dict[str, str] = {}
    if node_id:
        descendants = _get_descendants(db, node_id)
        leaf_candidates = _leaf_nodes(descendants)
        # Map by normalized title (strip spaces)
        for n in leaf_candidates:
            t = (n.get("title") or "").strip()
            if t:
                leaf_title_to_id[t] = n.get("id")

    try:
        # 优先按 node 的 chunk_indexes 取 context；没有就退回 M1 的全文/summary
        context = ""
        if node_id and node_chunk_indexes and node_material_id:
            context = _load_material_texts_for_chunk_indexes(
                db,
                material_id=str(node_material_id),
                chunk_indexes=node_chunk_indexes,
                max_chars=CONTEXT_MAX_CHARS,
            )
        if not context:
            context = _load_material_texts(db, material_ids, CONTEXT_MAX_CHARS)
        if not context:
            raise RuntimeError("no material text available")

        # ---------------- Prompt ----------------
        prompt = "Generate questions based on the study material.\n"

        if node_title:
            prompt += (
                f"IMPORTANT: Only generate questions related to the chapter/section "
                f"titled '{node_title}'. Do NOT include content from other chapters.\n"
            )

        prompt += (
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
            "- node_title: one title picked EXACTLY from the provided node title list (if provided)\n"
            "For blank questions, use stem with a blank like '____' and provide the exact answer_key.\n"
            "Material:\n"
            f"{context}\n"
        )

        if leaf_candidates:
            titles = [ (c.get("title") or "").strip() for c in leaf_candidates if (c.get("title") or "").strip() ]
            # Keep list short to reduce prompt size
            titles = titles[:30]
            prompt += (
                "\nNode title list (choose the best matching one for each question and output it as node_title):\n"
                + "\n".join([f"- {t}" for t in titles])
                + "\n"
            )

        questions, check_result = run_with_checker(
            prompt=prompt,
            call_llm=_call_kimi,
            checker=QuizCheck(expected_count=num_questions),
            context={"expected_count": num_questions},
            max_retries=2,
        )

        # For safety: if the check layer escalates, fail the job explicitly.
        if check_result.status == CheckStatus.ESCALATE or not questions:
            raise ValueError(f"quiz check failed: {check_result.reason}")

        # LLM may return more/less than requested. We make this robust so the UI
        # won't stay in "processing" due to a strict count check.
        if num_questions and len(questions) > num_questions:
            questions = questions[:num_questions]
        actual_count = len(questions)
        if actual_count == 0:
            raise ValueError("empty questions")

        # If fewer than requested, we still proceed and record the actual count.
        if actual_count != num_questions:
            _quizzes_col(db).update_one(
                {"_id": ObjectId(quiz_id)},
                {"$set": {"num_questions": actual_count}},
            )

        now = datetime.utcnow()
        docs = []
        # round-robin fallback among leaf candidates if LLM doesn't provide node_title
        rr = 0
        for q in questions:
            knowledge_points = q.get("knowledge_points")
            if not isinstance(knowledge_points, list):
                knowledge_points = []

            analysis = q.get("analysis") or q.get("explanation") or ""

            # Determine node_ids for this question
            node_ids: List[str] = []
            node_title_out = (q.get("node_title") or "").strip()
            if node_title_out and node_title_out in leaf_title_to_id:
                node_ids = [leaf_title_to_id[node_title_out]]
            elif leaf_candidates:
                # fallback: assign evenly across leaf nodes
                nid = leaf_candidates[rr % len(leaf_candidates)].get("id")
                rr += 1
                if nid:
                    node_ids = [nid]
            else:
                node_ids = fallback_node_ids

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

                # === M2：绑定知识节点（用于掌握度回流；每题尽量绑定到子节点/叶子节点）===
                "node_ids": node_ids,
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

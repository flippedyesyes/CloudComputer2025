# 提交作答
# 投递 grade_attempt job
# 查询判卷结果

from fastapi import APIRouter

router = APIRouter()

@router.post("/{quiz_id}/submit")
def submit_attempt(quiz_id: str):
    return {"attempt_id": "demo", "status": "grading"}

@router.get("/{attempt_id}")
def get_attempt(attempt_id: str):
    return {"attempt_id": attempt_id, "status": "done"}

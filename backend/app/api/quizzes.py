# 创建 quiz
# 投递 generate_quiz job

from fastapi import APIRouter

router = APIRouter()

@router.post("/generate")
def generate_quiz():
    return {"quiz_id": "demo", "status": "queued"}

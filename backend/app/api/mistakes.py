# 查询错题
# 不走 LLM

from fastapi import APIRouter

router = APIRouter()

@router.get("/")
def list_mistakes():
    return {"mistakes": []}

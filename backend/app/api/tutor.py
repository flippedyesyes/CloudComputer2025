# 在学生已经做错之后
# 启动一个 多轮对话 session
# 每一轮给「提示 / 反问 / 引导」

from fastapi import APIRouter

router = APIRouter()

@router.post("/start")
def start_tutor():
    return {"session_id": "demo", "step": 1}


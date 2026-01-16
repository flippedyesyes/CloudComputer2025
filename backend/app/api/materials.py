# 接教材 / 文本
# 创建 material 记录
# 投递 ingest job

from fastapi import APIRouter

router = APIRouter()

@router.post("/")
def upload_material():
    return {"material_id": "demo", "status": "queued"}

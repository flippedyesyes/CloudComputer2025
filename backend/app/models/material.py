# 不仅仅是 text，还承载：
# ingest 状态
# 后续知识拆解的来源

from pydantic import BaseModel

class Material(BaseModel):
    id: str
    content: str
    status: str  # uploaded / ingested

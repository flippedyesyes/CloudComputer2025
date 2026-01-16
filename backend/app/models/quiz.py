from pydantic import BaseModel
from typing import List

class Quiz(BaseModel):
    id: str
    material_id: str
    status: str
    question_ids: List[str] = []

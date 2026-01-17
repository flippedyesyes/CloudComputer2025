from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Quiz(BaseModel):
    id: Optional[str] = None
    notebook_id: str
    material_ids: List[str] = Field(default_factory=list)
    status: str = "generating"
    question_ids: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    error_message: Optional[str] = None

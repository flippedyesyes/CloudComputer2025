from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Mistake(BaseModel):
    id: Optional[str] = None
    notebook_id: Optional[str] = None
    student_id: str
    question_id: str
    wrong_count: int = 0
    error_tags: List[str] = Field(default_factory=list)
    knowledge_points: List[str] = Field(default_factory=list)
    last_error_analysis: Optional[str] = None
    last_wrong_at: Optional[datetime] = None

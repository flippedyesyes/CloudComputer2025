from pydantic import BaseModel

class Mastery(BaseModel):
    node_id: str
    seen: int = 0
    correct: int = 0
    mastery_score: float = 0.0

from pydantic import BaseModel

class Attempt(BaseModel):
    id: str
    quiz_id: str
    status: str
    score: float | None = None

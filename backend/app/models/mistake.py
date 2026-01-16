from pydantic import BaseModel

class Mistake(BaseModel):
    question_id: str
    count: int

from pydantic import BaseModel

class Question(BaseModel):
    id: str
    quiz_id: str
    stem: str
    answer_key: str
    difficulty: str

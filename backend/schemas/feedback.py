from pydantic import BaseModel
from datetime import datetime


class FeedbackCreate(BaseModel):
    feedback_type: str  # 'like' or 'dislike'


class FeedbackOut(BaseModel):
    id: int
    message_id: int
    feedback_type: str
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackStatsOut(BaseModel):
    total_likes: int
    total_dislikes: int
    recent_dislikes: list[dict]  # [{question, answer, user, created_at}]
    recent_likes: list[dict]

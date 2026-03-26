from pydantic import BaseModel
from datetime import datetime


class AskRequest(BaseModel):
    question: str


class MessageOut(BaseModel):
    id: int
    chat_id: int
    role: str
    content: str
    sources: list = []
    images: list = []
    created_at: datetime

    model_config = {"from_attributes": True}


class AskResponse(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut

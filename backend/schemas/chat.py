from pydantic import BaseModel
from datetime import datetime


class ChatCreate(BaseModel):
    title: str = "Новый чат"


class ChatUpdate(BaseModel):
    title: str


class ChatOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

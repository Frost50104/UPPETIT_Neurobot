from pydantic import BaseModel
from datetime import datetime


class KBStatusOut(BaseModel):
    is_ready: bool
    chunk_count: int
    last_sync: datetime | None = None
    last_sync_status: str | None = None


class KBSyncOut(BaseModel):
    id: int
    status: str
    files_count: int
    chunks_count: int
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    triggered_by_name: str | None = None

    model_config = {"from_attributes": True}

from pydantic import BaseModel
from datetime import datetime


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    is_active: bool
    must_change_password: bool
    roles: list[str]
    created_at: datetime
    last_login: datetime | None = None


class UserCreate(BaseModel):
    username: str
    full_name: str
    password: str
    role_name: str = "employee"


class UserUpdate(BaseModel):
    full_name: str | None = None
    username: str | None = None
    role_name: str | None = None
    new_password: str | None = None

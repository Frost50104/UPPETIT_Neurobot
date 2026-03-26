import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models.user import User
from models.chat import Chat
from schemas.chat import ChatCreate, ChatUpdate, ChatOut
from core.auth import get_current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chats", tags=["chats"])


@router.get("", response_model=list[ChatOut])
async def list_chats(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Chat)
        .where(Chat.user_id == current_user.id)
        .order_by(Chat.updated_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=ChatOut)
async def create_chat(
    data: ChatCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    chat = Chat(user_id=current_user.id, title=data.title)
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return chat


@router.patch("/{chat_id}", response_model=ChatOut)
async def rename_chat(
    chat_id: int,
    data: ChatUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    chat = await _get_user_chat(chat_id, current_user.id, db)
    chat.title = data.title
    await db.commit()
    await db.refresh(chat)
    return chat


@router.delete("/{chat_id}")
async def delete_chat(
    chat_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    chat = await _get_user_chat(chat_id, current_user.id, db)
    await db.delete(chat)
    await db.commit()
    return {"ok": True}


async def _get_user_chat(chat_id: int, user_id: int, db: AsyncSession) -> Chat:
    result = await db.execute(
        select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id)
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return chat

import asyncio
import logging
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone
from database import get_db
from models.user import User
from models.chat import Chat
from models.message import Message
from schemas.message import AskRequest, MessageOut, AskResponse
from core.auth import get_current_active_user
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/chats/{chat_id}/messages", tags=["messages"])


@router.get("", response_model=list[MessageOut])
async def list_messages(
    chat_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_chat_ownership(chat_id, current_user.id, db)
    result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.asc())
    )
    return result.scalars().all()


@router.post("", response_model=AskResponse)
async def ask_question(
    chat_id: int,
    data: AskRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if getattr(request.app.state, "kb_rebuilding", False):
        raise HTTPException(status_code=503, detail="kb_rebuilding")

    chat = await _verify_chat_ownership(chat_id, current_user.id, db)

    # Save user message
    user_msg = Message(
        chat_id=chat_id,
        role="user",
        content=data.question,
    )
    db.add(user_msg)
    await db.flush()

    # Call RAG pipeline in thread pool
    answerer = request.app.state.answerer
    try:
        result = await asyncio.to_thread(answerer.answer, data.question)
    except Exception as exc:
        logger.error("RAG pipeline error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при обработке вопроса. Попробуйте позже.")

    # Convert absolute image paths to relative filenames for the API
    image_filenames = []
    for img_path in result.images:
        filename = os.path.basename(img_path)
        if os.path.isfile(img_path):
            image_filenames.append(filename)

    # Save assistant message
    assistant_msg = Message(
        chat_id=chat_id,
        role="assistant",
        content=result.text,
        sources=result.sources,
        images=image_filenames,
    )
    db.add(assistant_msg)

    # Update chat timestamp
    chat.updated_at = datetime.now(timezone.utc)

    # Auto-title on first message — generate short summary via GPT
    msg_count = await db.execute(
        select(func.count()).select_from(Message).where(Message.chat_id == chat_id)
    )
    if msg_count.scalar() <= 2:  # First exchange: user + assistant messages
        chat.title = await _generate_chat_title(request.app, data.question)

    await db.commit()
    await db.refresh(user_msg)
    await db.refresh(assistant_msg)

    return AskResponse(
        user_message=MessageOut.model_validate(user_msg),
        assistant_message=MessageOut.model_validate(assistant_msg),
    )


async def _generate_chat_title(app, question: str) -> str:
    """Generate a short chat title from the first question using GPT."""
    try:
        client = app.state.openai_client
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Сгенерируй очень короткое название чата (3-5 слов) "
                        "на основе вопроса пользователя. Только название, без кавычек и точки."
                    ),
                },
                {"role": "user", "content": question},
            ],
            max_tokens=30,
            temperature=0.3,
        )
        title = (response.choices[0].message.content or "").strip().strip('"\'.')
        return title[:60] if title else question[:60].strip()
    except Exception as exc:
        logger.warning("Failed to generate chat title: %s", exc)
        return question[:60].strip()


async def _verify_chat_ownership(chat_id: int, user_id: int, db: AsyncSession) -> Chat:
    result = await db.execute(
        select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id)
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return chat

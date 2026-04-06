import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database import get_db
from models.user import User
from models.message import Message
from models.chat import Chat
from models.feedback import MessageFeedback
from schemas.feedback import FeedbackCreate, FeedbackOut, FeedbackStatsOut
from core.auth import get_current_active_user
from core.rbac import require_permission, Perm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/messages", tags=["feedback"])


@router.post("/{message_id}/feedback", response_model=FeedbackOut)
async def submit_feedback(
    message_id: int,
    data: FeedbackCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if data.feedback_type not in ("like", "dislike"):
        raise HTTPException(status_code=400, detail="feedback_type must be 'like' or 'dislike'")

    # Verify message exists and user owns the chat
    msg = await db.get(Message, message_id)
    if not msg or msg.role != "assistant":
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    result = await db.execute(
        select(Chat).where(Chat.id == msg.chat_id, Chat.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    # Get the user question (previous message in chat)
    result = await db.execute(
        select(Message)
        .where(Message.chat_id == msg.chat_id, Message.role == "user", Message.id < msg.id)
        .order_by(Message.id.desc())
        .limit(1)
    )
    user_msg = result.scalar_one_or_none()
    question_text = user_msg.content if user_msg else ""

    # Upsert: update existing or create new
    result = await db.execute(
        select(MessageFeedback).where(MessageFeedback.message_id == message_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.feedback_type = data.feedback_type
        feedback = existing
    else:
        feedback = MessageFeedback(
            message_id=message_id,
            user_id=current_user.id,
            feedback_type=data.feedback_type,
            question=question_text,
            answer=msg.content,
        )
        db.add(feedback)

    await db.commit()
    await db.refresh(feedback)
    return feedback


@router.delete("/{message_id}/feedback", status_code=204)
async def remove_feedback(
    message_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MessageFeedback).where(
            MessageFeedback.message_id == message_id,
            MessageFeedback.user_id == current_user.id,
        )
    )
    feedback = result.scalar_one_or_none()
    if feedback:
        await db.delete(feedback)
        await db.commit()


@router.get("/{message_id}/feedback", response_model=FeedbackOut | None)
async def get_feedback(
    message_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MessageFeedback).where(
            MessageFeedback.message_id == message_id,
            MessageFeedback.user_id == current_user.id,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Admin stats endpoint
# ---------------------------------------------------------------------------

stats_router = APIRouter(prefix="/api/admin/feedback", tags=["admin-feedback"])


@stats_router.get("/stats", response_model=FeedbackStatsOut)
async def feedback_stats(
    current_user: User = Depends(require_permission(Perm.KB_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    # Counts
    likes_q = await db.execute(
        select(func.count()).select_from(MessageFeedback)
        .where(MessageFeedback.feedback_type == "like")
    )
    dislikes_q = await db.execute(
        select(func.count()).select_from(MessageFeedback)
        .where(MessageFeedback.feedback_type == "dislike")
    )

    # Recent dislikes (last 50)
    result = await db.execute(
        select(MessageFeedback)
        .where(MessageFeedback.feedback_type == "dislike")
        .order_by(MessageFeedback.created_at.desc())
        .limit(50)
    )
    dislikes = result.scalars().all()

    recent_dislikes = []
    for fb in dislikes:
        user = await db.get(User, fb.user_id)
        recent_dislikes.append({
            "question": fb.question,
            "answer": fb.answer[:500],
            "user": user.full_name if user else "?",
            "created_at": fb.created_at.isoformat(),
        })

    # Recent likes (last 50)
    result = await db.execute(
        select(MessageFeedback)
        .where(MessageFeedback.feedback_type == "like")
        .order_by(MessageFeedback.created_at.desc())
        .limit(50)
    )
    likes = result.scalars().all()

    recent_likes = []
    for fb in likes:
        user = await db.get(User, fb.user_id)
        recent_likes.append({
            "question": fb.question,
            "answer": fb.answer[:500],
            "user": user.full_name if user else "?",
            "created_at": fb.created_at.isoformat(),
        })

    return FeedbackStatsOut(
        total_likes=likes_q.scalar() or 0,
        total_dislikes=dislikes_q.scalar() or 0,
        recent_dislikes=recent_dislikes,
        recent_likes=recent_likes,
    )

from sqlalchemy import String, Text, DateTime, ForeignKey, func, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from database import Base


class MessageFeedback(Base):
    __tablename__ = "message_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True, unique=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    feedback_type: Mapped[str] = mapped_column(String(8))  # 'like' or 'dislike'
    question: Mapped[str] = mapped_column(Text)  # original user question
    answer: Mapped[str] = mapped_column(Text)  # bot answer that was rated
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    message: Mapped["Message"] = relationship("Message")
    user: Mapped["User"] = relationship("User")

    from models.message import Message  # noqa: F811
    from models.user import User  # noqa: F811

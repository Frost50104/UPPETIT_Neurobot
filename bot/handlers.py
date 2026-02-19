"""
Aiogram 3 message handlers for the UPPETIT knowledge bot.

Dependency injection
────────────────────
aiogram 3 resolves handler parameters by name from the dispatcher's
workflow_data (set via ``dp["key"] = value`` in main.py):
  • settings     → config.Settings
  • vector_store → vector_store.VectorStore
  • answerer     → rag_answerer.RAGAnswerer
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message

if TYPE_CHECKING:
    from config import Settings
    from rag_answerer import RAGAnswerer
    from vector_store import VectorStore

logger = logging.getLogger(__name__)
router = Router()

# ─────────────────────────────────────────────────────────────────────────────
# Static message text
# ─────────────────────────────────────────────────────────────────────────────

_WELCOME = (
    "Привет! Я корпоративный ассистент UPPETIT.\n\n"
    "Задайте любой вопрос о компании — я отвечу строго на основе "
    "официальной базы знаний.\n\n"
    "Команды:\n"
    "/help — правила использования\n"
    "/reload_kb — обновить базу знаний (только администраторы)"
)

_HELP = (
    "Правила использования\n\n"
    "• Задавайте вопросы на любом языке.\n"
    "• Бот отвечает ТОЛЬКО на основе базы знаний UPPETIT.\n"
    "• Если нужной информации нет — бот честно об этом сообщит.\n"
    "• Бот не использует интернет и не додумывает ответы.\n\n"
    "Если ответ кажется неполным:\n"
    "• Перефразируйте вопрос.\n"
    "• Обратитесь к HR или непосредственному руководителю."
)


# ─────────────────────────────────────────────────────────────────────────────
# Access-control helpers
# ─────────────────────────────────────────────────────────────────────────────

def _allowed(chat_id: int, user_id: int, settings: "Settings") -> bool:
    """Return True if the user/chat is permitted to use the bot."""
    if not settings.ALLOWED_CHAT_IDS:
        return True
    return chat_id in settings.ALLOWED_CHAT_IDS or user_id in settings.ALLOWED_CHAT_IDS


def _is_admin(user_id: int, settings: "Settings") -> bool:
    """Return True if the user can run admin commands."""
    return not settings.ADMIN_IDS or user_id in settings.ADMIN_IDS


# ─────────────────────────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def start_handler(message: Message, settings: "Settings") -> None:
    if not _allowed(message.chat.id, message.from_user.id, settings):
        return
    await message.answer(_WELCOME)


@router.message(Command("help"))
async def help_handler(message: Message, settings: "Settings") -> None:
    if not _allowed(message.chat.id, message.from_user.id, settings):
        return
    await message.answer(_HELP)


@router.message(Command("reload_kb"))
async def reload_kb_handler(
    message: Message,
    settings: "Settings",
    vector_store: "VectorStore",
) -> None:
    if not _allowed(message.chat.id, message.from_user.id, settings):
        return
    if not _is_admin(message.from_user.id, settings):
        await message.answer("У вас нет прав для этой команды.")
        return

    status = await message.answer("Обновление базы знаний…")
    try:
        await asyncio.to_thread(_sync_rebuild, settings, vector_store)
        await status.edit_text(
            f"База знаний обновлена.\nЗагружено чанков: {vector_store.chunk_count}"
        )
    except FileNotFoundError:
        await status.edit_text(
            f"Файл не найден: {settings.KB_FILE}\n"
            "Поместите файл в корень проекта и повторите попытку."
        )
    except ValueError as exc:
        await status.edit_text(f"Ошибка при чтении файла: {exc}")
    except Exception as exc:
        logger.error("reload_kb failed: %s", exc, exc_info=True)
        await status.edit_text(f"Непредвиденная ошибка: {exc}")


@router.message(F.text)
async def question_handler(
    message: Message,
    bot: Bot,
    settings: "Settings",
    answerer: "RAGAnswerer",
) -> None:
    if not _allowed(message.chat.id, message.from_user.id, settings):
        return

    question = (message.text or "").strip()
    if not question:
        return

    user_id = message.from_user.id
    username = message.from_user.username or str(user_id)
    logger.info("Question from @%s (id=%d): %.120s", username, user_id, question)

    thinking = await message.answer("Ищу информацию в базе знаний…")

    try:
        result = await asyncio.to_thread(answerer.answer, question)
    except Exception as exc:
        logger.error("RAG error for user %d: %s", user_id, exc, exc_info=True)
        await thinking.delete()
        await message.answer(
            "Произошла ошибка при обработке вопроса.\n"
            "Попробуйте позже или обратитесь к администратору."
        )
        return

    logger.info(
        "Answered @%s: found=%s sources=%s",
        username,
        result.found,
        result.sources,
    )

    await thinking.delete()

    # Send answer (split if it exceeds Telegram's 4096-char limit).
    for part in _split_message(result.text, settings.TELEGRAM_MESSAGE_LIMIT):
        await message.answer(part)

    # Send attached images (only those that still exist on disk).
    for img_path in result.images:
        if os.path.exists(img_path):
            try:
                await bot.send_photo(
                    chat_id=message.chat.id,
                    photo=FSInputFile(img_path),
                    caption="Изображение из базы знаний",
                )
            except Exception as exc:
                logger.warning("Could not send image '%s': %s", img_path, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Sync helpers (run in thread pool)
# ─────────────────────────────────────────────────────────────────────────────

def _sync_rebuild(settings: "Settings", vector_store: "VectorStore") -> None:
    """Full KB rebuild: parse docx → chunk → embed → save index."""
    from chunker import chunk_sections
    from kb_loader import load_knowledge_base

    sections = load_knowledge_base(settings.KB_FILE, settings.IMAGES_DIR)
    chunks = chunk_sections(sections, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
    vector_store.build(chunks)


def _split_message(text: str, limit: int) -> list[str]:
    """Split *text* into ≤ *limit*-character parts at natural boundaries."""
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        split_at = text.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        parts.append(text[:split_at].strip())
        text = text[split_at:].strip()

    return [p for p in parts if p]

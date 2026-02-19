"""
Entry point for the UPPETIT Knowledge Bot.

Startup sequence
────────────────
1. Set up structured logging (console + file).
2. Create runtime directories.
3. Initialise OpenAI client, VectorStore, RAGAnswerer.
4. Load existing FAISS index from disk — or build it from the docx if absent.
5. Start aiogram 3 long-polling loop.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from openai import OpenAI

from config import settings
from chunker import chunk_sections
from kb_loader import load_knowledge_base
from rag_answerer import RAGAnswerer
from vector_store import VectorStore
from bot.handlers import router


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

def _setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
    ]
    err_handler = logging.FileHandler("logs/errors.log", encoding="utf-8")
    err_handler.setLevel(logging.ERROR)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)

    err_handler.setFormatter(fmt)
    root.addHandler(err_handler)

    # Suppress verbose third-party loggers.
    for noisy in ("httpx", "httpcore", "openai", "aiogram.event"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge base initialisation
# ─────────────────────────────────────────────────────────────────────────────

def _init_knowledge_system() -> tuple[VectorStore, RAGAnswerer]:
    """
    Build or load the vector store, then return a ready RAGAnswerer.

    If the docx is missing at startup the bot still starts — it will just
    respond that the KB is not loaded until /reload_kb is called.
    """
    openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

    store = VectorStore(
        storage_dir=settings.STORAGE_DIR,
        embedding_model=settings.EMBEDDING_MODEL,
        openai_client=openai_client,
    )

    if not store.load():
        log = logging.getLogger(__name__)
        try:
            log.info("Building index from '%s'…", settings.KB_FILE)
            sections = load_knowledge_base(settings.KB_FILE, settings.IMAGES_DIR)
            chunks = chunk_sections(sections, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
            store.build(chunks)
        except FileNotFoundError:
            log.warning(
                "Knowledge base file '%s' not found. "
                "Bot will start in degraded mode. "
                "Add the file and run /reload_kb.",
                settings.KB_FILE,
            )
        except Exception as exc:
            log.error("Failed to build index: %s", exc, exc_info=True)

    answerer = RAGAnswerer(
        vector_store=store,
        openai_client=openai_client,
        chat_model=settings.CHAT_MODEL,
        top_k=settings.TOP_K,
        max_tokens=settings.MAX_TOKENS,
        min_score=settings.MIN_SCORE,
    )

    return store, answerer


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    _setup_logging()
    log = logging.getLogger(__name__)

    settings.ensure_dirs()
    log.info("Starting UPPETIT Knowledge Bot…")

    vector_store, answerer = _init_knowledge_system()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=None),
    )

    dp = Dispatcher()

    # Inject shared objects into every handler via aiogram's workflow_data.
    dp["settings"] = settings
    dp["vector_store"] = vector_store
    dp["answerer"] = answerer

    dp.include_router(router)

    log.info("Polling started. Press Ctrl+C to stop.")
    try:
        await dp.start_polling(bot, allowed_updates=["message"])
    finally:
        await bot.session.close()
        log.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        # Treat empty string env vars as "not set" → use field default.
        # This prevents JSON-decode errors for List fields set to "" in .env.
        env_ignore_empty=True,
    )

    # ── Secrets ───────────────────────────────────────────────────────────────
    BOT_TOKEN: str
    OPENAI_API_KEY: str

    # ── Access control ─────────────────────────────────────────────────────────
    # Comma-separated Telegram user IDs. Empty = any user can call /reload_kb.
    ADMIN_IDS: List[int] = []
    # Comma-separated chat/user IDs allowed to use the bot. Empty = allow everyone.
    ALLOWED_CHAT_IDS: List[int] = []

    # ── Paths ──────────────────────────────────────────────────────────────────
    KB_FILE: str = "Information bank.docx"
    STORAGE_DIR: str = "./storage"
    IMAGES_DIR: str = "./kb_images"

    # ── Chunking ───────────────────────────────────────────────────────────────
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 150

    # ── RAG ────────────────────────────────────────────────────────────────────
    TOP_K: int = 6
    # Minimum cosine similarity to include a chunk in context (0..1).
    MIN_SCORE: float = 0.20

    # ── OpenAI ─────────────────────────────────────────────────────────────────
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    CHAT_MODEL: str = "gpt-4o-mini"
    MAX_TOKENS: int = 1500

    # ── Telegram ───────────────────────────────────────────────────────────────
    TELEGRAM_MESSAGE_LIMIT: int = 4096

    @field_validator("ADMIN_IDS", "ALLOWED_CHAT_IDS", mode="before")
    @classmethod
    def _parse_id_list(cls, value: object) -> list[int]:
        if isinstance(value, list):
            return value
        if not value or (isinstance(value, str) and not value.strip()):
            return []
        return [int(i.strip()) for i in str(value).split(",") if i.strip()]

    def ensure_dirs(self) -> None:
        """Create all required runtime directories."""
        Path(self.STORAGE_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.IMAGES_DIR).mkdir(parents=True, exist_ok=True)
        Path("logs").mkdir(parents=True, exist_ok=True)


settings = Settings()

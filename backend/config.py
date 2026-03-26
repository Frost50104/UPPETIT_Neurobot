
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "Neurobot"
    app_env: str = "production"  # "production" | "staging"
    debug: bool = False
    sql_echo: bool = False
    secret_key: str
    allowed_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Database
    database_url: str  # postgresql+asyncpg://user:pass@host/db

    # Redis
    redis_url: str = "redis://localhost:6379/1"

    # JWT
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # OpenAI
    openai_api_key: str
    embedding_model: str = "text-embedding-3-small"
    chat_model: str = "gpt-4o-mini"
    max_tokens: int = 1500

    # RAG
    chunk_size: int = 800
    chunk_overlap: int = 150
    top_k: int = 6
    min_score: float = 0.20
    min_semantic_score: float = 0.20
    storage_dir: str = "storage"
    images_dir: str = "kb_images"

    # Google Drive
    google_credentials_path: str = "google_creds.json"
    gdrive_folder_id: str = ""
    kb_downloads_dir: str = "kb_downloads"

    # Admin seed
    admin_initial_password: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()

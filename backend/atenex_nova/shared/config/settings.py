"""Atenex Nova — Shared configuration settings.

Uses pydantic-settings for environment variable loading and profile support.
"""

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[4]
STORAGE_ROOT = PROJECT_ROOT / "backend" / "storage"
DEFAULT_SQLITE_DB_PATH = PROJECT_ROOT / "backend" / "atenex_nova.db"


class Profile(StrEnum):
    """Deployment profile."""

    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class EmbeddingProfile(StrEnum):
    """Embedding dimension profile."""

    LITE = "lite"  # 256d
    STANDARD = "standard"  # 384d
    MAX = "max"  # 768d


class GenerationProfile(StrEnum):
    """LLM generation profile."""

    LITE = "lite"  # Gemma 4 E2B
    STANDARD = "standard"  # Gemma 4 E4B
    ADVANCED = "advanced"  # Gemma 4 26B/31B


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ATENEX_",
        case_sensitive=False,
    )

    # --- General ---
    app_name: str = "Atenex Nova"
    profile: Profile = Profile.DEV
    debug: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = Field(
        default=[
            "http://localhost:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
        ]
    )

    # --- Database ---
    database_url: str = f"sqlite+aiosqlite:///{DEFAULT_SQLITE_DB_PATH.as_posix()}"

    # --- Qdrant ---
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None

    # --- LLM Runtime ---
    llm_backend: Literal["llamacpp", "ollama"] = "ollama"
    llm_url: str = "http://localhost:11434"
    llm_model: str = "gemma4:e4b"

    # --- Embeddings ---
    embedding_model: str = "google/embeddinggemma-300m"
    embedding_profile: EmbeddingProfile = EmbeddingProfile.STANDARD
    embedding_batch_size: int = 32

    # --- Storage ---
    blob_store_path: Path = STORAGE_ROOT / "uploads"
    visual_pages_path: Path = STORAGE_ROOT / "visual_pages"

    # --- Worker ---
    worker_poll_interval: float = 2.0
    worker_max_retries: int = 3

    @property
    def embedding_dimensions(self) -> int:
        """Get embedding dimensions based on profile."""
        dims = {
            EmbeddingProfile.LITE: 256,
            EmbeddingProfile.STANDARD: 384,
            EmbeddingProfile.MAX: 768,
        }
        return dims[self.embedding_profile]


def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()

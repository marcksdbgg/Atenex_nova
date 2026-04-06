"""Atenex Nova — Shared configuration settings.

Uses pydantic-settings for environment variable loading and profile support.
"""

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Profile(str, Enum):
    """Deployment profile."""

    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class EmbeddingProfile(str, Enum):
    """Embedding dimension profile."""

    LITE = "lite"       # 256d
    STANDARD = "standard"  # 384d
    MAX = "max"         # 768d


class GenerationProfile(str, Enum):
    """LLM generation profile."""

    LITE = "lite"       # Gemma 4 E2B
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
    cors_origins: list[str] = Field(default=["http://localhost:5173"])

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./atenex_nova.db"

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
    blob_store_path: Path = Path("storage/uploads")

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

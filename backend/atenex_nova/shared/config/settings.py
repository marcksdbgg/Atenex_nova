"""Atenex Nova — Shared configuration settings.

Uses pydantic-settings for environment variable loading and profile support.
"""

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
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
    STANDARD = "standard"  # Gemma 4 12B
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
    strict_mode: bool | None = None

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
    llm_model: str = "gemma4:12b"

    # --- Embeddings (offline-first: Ollama local, igual que el LLM) ---
    # backend "ollama" → usa el modelo embeddinggemma servido por Ollama (sin Hugging Face).
    # backend "sentence_transformers" → carga el modelo desde disco con SentenceTransformers.
    embedding_backend: Literal["ollama", "sentence_transformers"] = "ollama"
    embedding_url: str = "http://localhost:11434"
    embedding_ollama_model: str = "embeddinggemma"
    embedding_model: str = "embeddinggemma"
    embedding_profile: EmbeddingProfile = EmbeddingProfile.STANDARD
    embedding_batch_size: int = 32

    # --- Reranker ---
    reranker_device: str = "cuda"
    reranker_fp16: bool = True
    reranker_batch_size: int = 32
    reranker_path: str | None = None

    # --- Storage ---
    blob_store_path: Path = STORAGE_ROOT / "uploads"
    visual_pages_path: Path = STORAGE_ROOT / "visual_pages"
    turbovec_path: Path = STORAGE_ROOT / "turbovec"

    # --- TurboVec / candidate index ---
    candidate_backend: Literal["auto", "purepy", "turbovec"] = "auto"
    turbovec_bit_width: int = 4

    # --- Visual indexing ---
    visual_indexing_enabled: bool = True
    visual_index_text_documents: bool = False

    # --- Worker ---
    worker_poll_interval: float = 2.0
    worker_max_retries: int = 3

    # --- Strict retrieval/generation guards ---
    require_embeddings: bool | None = None
    require_llm: bool | None = None
    require_qdrant: bool | None = None
    require_visual: bool | None = None
    require_reranker: bool | None = None
    require_ocr: bool | None = None
    enable_reranker: bool | None = None
    store_prompts: bool = False
    min_evidence_items: int = 1
    min_grounding_score: float = 0.35
    grounding_floor: float = 0.0
    allow_fallback_embeddings: bool = False

    @property
    def strict_mode_enabled(self) -> bool:
        """Strict mode defaults to true in production unless explicitly overridden."""
        if self.strict_mode is not None:
            return self.strict_mode
        return self.profile == Profile.PROD

    def _require_flag(self, configured: bool | None) -> bool:
        if configured is not None:
            return configured
        return self.strict_mode_enabled

    @property
    def embeddings_required(self) -> bool:
        return self._require_flag(self.require_embeddings)

    @property
    def llm_required(self) -> bool:
        return self._require_flag(self.require_llm)

    @property
    def qdrant_required(self) -> bool:
        return self._require_flag(self.require_qdrant)

    @property
    def visual_required(self) -> bool:
        return self._require_flag(self.require_visual)

    @property
    def reranker_required(self) -> bool:
        return self._require_flag(self.require_reranker)

    @property
    def ocr_required(self) -> bool:
        return self._require_flag(self.require_ocr)

    @property
    def reranker_enabled(self) -> bool:
        if self.enable_reranker is not None:
            return self.enable_reranker
        # Desactivado en perfil LITE (perfil bajo), activado en estándar y max (perfil medio/alto)
        return self.embedding_profile != EmbeddingProfile.LITE

    @property
    def embedding_dimensions(self) -> int:
        """Get embedding dimensions based on profile."""
        dims = {
            EmbeddingProfile.LITE: 256,
            EmbeddingProfile.STANDARD: 384,
            EmbeddingProfile.MAX: 768,
        }
        return dims[self.embedding_profile]

    @model_validator(mode="after")
    def adjust_defaults(self) -> "Settings":
        default_sqlite = f"sqlite+aiosqlite:///{DEFAULT_SQLITE_DB_PATH.as_posix()}"
        if self.database_url == default_sqlite and self.profile == Profile.PROD:
            self.database_url = "postgresql+asyncpg://atenex:atenex_dev_password@localhost:5432/atenex_nova"
        return self


def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()

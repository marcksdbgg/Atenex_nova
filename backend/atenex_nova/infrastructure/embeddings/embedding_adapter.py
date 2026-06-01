"""EmbeddingGemma adapter using SentenceTransformers with optional fallback mode."""

from __future__ import annotations

import hashlib
import logging
from math import sqrt
from typing import Any, cast

from atenex_nova.domain.repositories.embedder import Embedder
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import ServiceUnavailableError

logger = logging.getLogger(__name__)


class EmbeddingGemmaAdapter(Embedder):
    """Genera embeddings con EmbeddingGemma localmente vía SentenceTransformers."""

    def __init__(
        self,
        model_name: str = "google/embeddinggemma-300m",
        dim: int = 384,
        required: bool | None = None,
    ) -> None:
        settings = get_settings()
        self._model_name = model_name or "google/embeddinggemma-300m"
        self._dim = dim
        self._required = settings.embeddings_required if required is None else required
        self.model: Any | None = None

        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(self._model_name, truncate_dim=dim)
            self._fallback_only = False
            logger.info("EmbeddingGemmaAdapter initialized model=%s dim=%d", self._model_name, dim)
        except Exception as e:
            if self._required:
                raise ServiceUnavailableError(
                    service="embeddings",
                    message=f"failed to load model '{self._model_name}': {e}",
                ) from e
            logger.error("Failed to load SentenceTransformer, fallback enabled: %s", str(e))
            self.model = None
            self._fallback_only = True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate vectors for a list of strings."""
        clean_texts = [str(t) for t in texts]
        model = self.model
        if model is None:
            if self._required:
                raise ServiceUnavailableError(
                    service="embeddings",
                    message="embedding model unavailable and strict mode requires semantic embeddings",
                )
            return [self._fallback_embed(text) for text in clean_texts]

        # SentenceTransformers encode is synchronous and CPU/GPU heavy.
        import asyncio

        loop = asyncio.get_running_loop()
        try:
            vectors = await loop.run_in_executor(
                None,
                lambda: model.encode(clean_texts, convert_to_numpy=True),
            )
            return cast(list[list[float]], vectors.tolist())
        except Exception as exc:
            if self._required:
                raise ServiceUnavailableError(
                    service="embeddings",
                    message=f"embedding generation failed: {exc}",
                ) from exc
            logger.warning("Embedding generation failed, using fallback vectors: %s", exc)
            return [self._fallback_embed(text) for text in clean_texts]

    def _fallback_embed(self, text: str) -> list[float]:
        """Deterministic hash embedding used when the real model is unavailable."""
        vector = [0.0] * self._dim
        tokens = text.lower().split()
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = digest[0] % self._dim
            sign = 1.0 if digest[1] % 2 == 0 else -1.0
            vector[index] += sign
        norm = sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    @property
    def uses_fallback(self) -> bool:
        return self.model is None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def embedding_dim(self) -> int:
        return self._dim

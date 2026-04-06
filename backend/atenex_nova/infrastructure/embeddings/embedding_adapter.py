"""EmbeddingGemma adapter using SentenceTransformers or a deterministic fallback."""

from __future__ import annotations

import hashlib
import logging
from math import sqrt

from atenex_nova.domain.repositories.embedder import Embedder

logger = logging.getLogger(__name__)


class EmbeddingGemmaAdapter(Embedder):
    """Generates embeddings using Google's EmbeddingGemma locally via SentenceTransformers.
    Supports Matryoshka Representation Learning for flexible dimensions."""

    def __init__(self, model_name: str = "google/gemma-2-2b-it", dim: int = 384) -> None:
        # Note: the exact HuggingFace model ID for EmbeddingGemma is usually something like
        # "google/gemma-308m". If the user has a specific path, it can be passed here.
        # We use a placeholder default if the exact ID isn't 'google/embeddinggemma-308m'.
        # Assuming sentence-transformers will handle it automatically.
        self._model_name = "google/embeddinggemma-308m" if "gemma" not in model_name else model_name
        self._dim = dim
        
        try:
            from sentence_transformers import SentenceTransformer
            # truncate_dim uses Matryoshka learning to cut to the required dimension
            self.model = SentenceTransformer(self._model_name, truncate_dim=dim)
            self._fallback_only = False
            logger.info("EmbeddingGemmaAdapter initialized model=%s dim=%d", self._model_name, dim)
        except Exception as e:
            logger.error("Failed to load SentenceTransformer: %s", str(e))
            self.model = None
            self._fallback_only = True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate vectors for a list of strings."""
        clean_texts = [str(t) for t in texts]
        if self.model is None:
            return [self._fallback_embed(text) for text in clean_texts]

        # SentenceTransformers encode is synchronous and CPU/GPU heavy.
        import asyncio

        loop = asyncio.get_running_loop()
        vectors = await loop.run_in_executor(
            None,
            lambda: self.model.encode(clean_texts, convert_to_numpy=True),
        )
        return vectors.tolist()

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

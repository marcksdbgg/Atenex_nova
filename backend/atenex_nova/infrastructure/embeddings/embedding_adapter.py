"""EmbeddingGemma adapter — 100% local / offline-first.

Backend por defecto: **Ollama** (`embeddinggemma`), igual que el LLM. No requiere
Hugging Face ni autenticación: el modelo se obtiene con ``ollama pull embeddinggemma``
y se sirve en local con GPU. Backend alternativo opcional: SentenceTransformers
(carga el modelo desde disco, también local).
"""

from __future__ import annotations

import hashlib
import logging
from math import sqrt
from typing import Any, cast

import httpx

from atenex_nova.domain.repositories.embedder import Embedder
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import ServiceUnavailableError

logger = logging.getLogger(__name__)


class EmbeddingGemmaAdapter(Embedder):
    """Genera embeddings con EmbeddingGemma de forma totalmente local."""

    def __init__(
        self,
        model_name: str | None = None,
        dim: int = 384,
        required: bool | None = None,
    ) -> None:
        settings = get_settings()
        self._dim = dim
        self._required = settings.embeddings_required if required is None else required
        self._backend = settings.embedding_backend
        self.model: Any | None = None
        self._fallback_only = False

        if self._backend == "ollama":
            self._init_ollama(settings, model_name)
        else:
            self._init_sentence_transformers(settings, model_name)

    # -- Backend initialisation -------------------------------------------------

    def _init_ollama(self, settings: Any, model_name: str | None) -> None:
        """Configure the Ollama embedding backend (no network call here).

        Availability is detected lazily on first ``embed`` so construction stays cheap
        and tests that monkeypatch ``__init__`` remain compatible.
        """
        self._ollama_url = str(settings.embedding_url).rstrip("/")
        self._model_name = model_name or settings.embedding_ollama_model
        self.model = "ollama"
        logger.info(
            "EmbeddingGemmaAdapter: backend=ollama model=%s target_dim=%d url=%s",
            self._model_name,
            self._dim,
            self._ollama_url,
        )

    def _init_sentence_transformers(self, settings: Any, model_name: str | None) -> None:
        self._model_name = model_name or settings.embedding_model
        try:
            import torch
            from sentence_transformers import SentenceTransformer

            if torch.cuda.is_available():
                device = "cuda"
                logger.info(
                    "EmbeddingGemmaAdapter: CUDA available — using GPU %s",
                    torch.cuda.get_device_name(0),
                )
            else:
                device = "cpu"
                logger.warning(
                    "EmbeddingGemmaAdapter: CUDA not available — using CPU "
                    "(install torch+cu128 for GPU support)"
                )

            self.model = SentenceTransformer(self._model_name, truncate_dim=self._dim, device=device)
            if device == "cuda":
                try:
                    self.model.half()
                    logger.info("EmbeddingGemmaAdapter: switched to float16 (half precision) on GPU")
                except Exception as fp16_exc:
                    logger.warning("EmbeddingGemmaAdapter: could not switch to fp16: %s", fp16_exc)
            logger.info(
                "EmbeddingGemmaAdapter initialized backend=sentence_transformers model=%s dim=%d device=%s",
                self._model_name,
                self._dim,
                device,
            )
        except Exception as e:
            if self._required:
                raise ServiceUnavailableError(
                    service="embeddings",
                    message=f"failed to load local model '{self._model_name}': {e}",
                ) from e
            logger.warning(
                "EmbeddingGemmaAdapter: local model unavailable — deterministic hash fallback active "
                "(set ATENEX_ALLOW_FALLBACK_EMBEDDINGS=true to permit indexing with fallback vectors): %s",
                e,
            )
            self.model = None
            self._fallback_only = True

    # -- Embedding --------------------------------------------------------------

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate vectors for a list of strings."""
        clean_texts = [str(t) for t in texts]
        if self.model is None:
            if self._required:
                raise ServiceUnavailableError(
                    service="embeddings",
                    message="embedding model unavailable and strict mode requires semantic embeddings",
                )
            return [self._fallback_embed(text) for text in clean_texts]

        backend = getattr(self, "_backend", "ollama")
        try:
            if backend == "ollama":
                return await self._embed_ollama(clean_texts)
            return await self._embed_sentence_transformers(clean_texts)
        except ServiceUnavailableError:
            raise
        except Exception as exc:
            if self._required:
                raise ServiceUnavailableError(
                    service="embeddings",
                    message=f"embedding generation failed: {exc}",
                ) from exc
            logger.warning("Embedding generation failed, using fallback vectors: %s", exc)
            self._fallback_only = True
            return [self._fallback_embed(text) for text in clean_texts]

    async def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        url = f"{self._ollama_url}/api/embed"
        payload = {"model": self._model_name, "input": texts}
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        raw = data.get("embeddings") or []
        if not raw or not raw[0]:
            raise ValueError(
                f"ollama returned empty embeddings for model '{self._model_name}' "
                f"(run: ollama pull {self._model_name})"
            )
        return [self._truncate_normalize([float(x) for x in vec]) for vec in raw]

    async def _embed_sentence_transformers(self, texts: list[str]) -> list[list[float]]:
        import asyncio

        model = self.model
        assert model is not None
        loop = asyncio.get_running_loop()
        vectors = await loop.run_in_executor(
            None,
            lambda: model.encode(texts, convert_to_numpy=True),
        )
        return cast(list[list[float]], vectors.tolist())

    def _truncate_normalize(self, vector: list[float]) -> list[float]:
        """Apply Matryoshka truncation to the target dim and renormalize to unit length."""
        truncated = vector[: self._dim] if len(vector) >= self._dim else vector
        norm = sqrt(sum(value * value for value in truncated)) or 1.0
        return [value / norm for value in truncated]

    def _fallback_embed(self, text: str) -> list[float]:
        """Deterministic hash embedding used when the local model is unavailable."""
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
        return self.model is None or self._fallback_only

    def ensure_indexable(self) -> None:
        """Reject indexing when hash fallback is active unless explicitly allowed."""
        settings = get_settings()
        if self.uses_fallback and not settings.allow_fallback_embeddings:
            raise ServiceUnavailableError(
                service="embeddings",
                message=(
                    "local embedding model unavailable (hash fallback active); "
                    "start Ollama and run `ollama pull embeddinggemma`, or set "
                    "ATENEX_ALLOW_FALLBACK_EMBEDDINGS=true to index anyway"
                ),
            )

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def embedding_dim(self) -> int:
        return self._dim

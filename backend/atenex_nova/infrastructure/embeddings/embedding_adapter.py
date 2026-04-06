"""Stub: Embedding adapter. Implemented in Fase 3."""
import logging
logger = logging.getLogger(__name__)


class EmbeddingAdapter:
    """Stub adapter for EmbeddingGemma."""
    def __init__(self, model_name: str = "google/embeddinggemma-300m", dim: int = 384) -> None:
        self._model_name = model_name
        self._dim = dim
        logger.info("EmbeddingAdapter initialized (stub) → %s dim=%d", model_name, dim)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        logger.info("Stub: embed %d texts", len(texts))
        return [[0.0] * self._dim for _ in texts]

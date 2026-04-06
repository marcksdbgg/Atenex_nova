"""Ollama embedding adapter."""

import logging

import ollama

from atenex_nova.domain.repositories.embedder import Embedder

logger = logging.getLogger(__name__)


class OllamaEmbeddingAdapter(Embedder):
    """Generates embeddings using a local Ollama model."""

    def __init__(self, model_name: str = "mxbai-embed-large", dim: int = 1024) -> None:
        self._model_name = model_name
        self._dim = dim
        logger.info("OllamaEmbeddingAdapter initialized model=%s dim=%d", model_name, dim)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate vectors for a list of strings using Ollama async client."""
        client = ollama.AsyncClient()
        vectors = []
        for text in texts:
            # We embed sequentially here, could be batched if ollama supports it
            response = await client.embeddings(model=self._model_name, prompt=text)
            vectors.append(response.embedding)
        return vectors

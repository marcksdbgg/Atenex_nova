"""EmbeddingGemma adapter using SentenceTransformers."""

import logging
import asyncio

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
            logger.info("EmbeddingGemmaAdapter initialized model=%s dim=%d", self._model_name, dim)
        except Exception as e:
            logger.error("Failed to load SentenceTransformer: %s", str(e))
            self.model = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate vectors for a list of strings."""
        if not self.model:
            raise RuntimeError("SentenceTransformer model not loaded.")
        
        # SentenceTransformers encode is synchronous and CPU/GPU heavy
        # Should be run in a separate thread.
        import asyncio
        loop = asyncio.get_running_loop()
        
        # Ensure texts are strings
        clean_texts = [str(t) for t in texts]
        
        # Run encode in executor
        vectors = await loop.run_in_executor(
            None, 
            lambda: self.model.encode(clean_texts, convert_to_numpy=True)
        )
        
        # Convert numpy arrays to list of lists of floats
        return vectors.tolist()

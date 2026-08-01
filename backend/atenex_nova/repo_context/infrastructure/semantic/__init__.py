"""Optional semantic adapters.

Importing this package never requires Ollama, Qdrant, or sentence-transformers.
"""

from atenex_nova.repo_context.infrastructure.semantic.fusion import reciprocal_rank_fusion
from atenex_nova.repo_context.infrastructure.semantic.ollama_embeddings import (
    OllamaEmbeddingProvider,
)
from atenex_nova.repo_context.infrastructure.semantic.qdrant_index import (
    QdrantSemanticIndex,
)

__all__ = [
    "OllamaEmbeddingProvider",
    "QdrantSemanticIndex",
    "reciprocal_rank_fusion",
]

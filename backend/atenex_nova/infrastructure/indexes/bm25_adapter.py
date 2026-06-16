"""Infrastructure: BM25 Adapter."""

from atenex_nova.infrastructure.embeddings.bm25_encoder import BM25SparseEncoder


class BM25Adapter:
    """Adapter for local sparse BM25 indexing and scoring."""

    def __init__(self) -> None:
        self.encoder = BM25SparseEncoder()

    def score(self, query: str, texts: list[str]) -> list[float]:
        """Compute BM25 scores for a query against a list of texts."""
        if not texts:
            return []
        return self.encoder.score(query, texts)

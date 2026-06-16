"""Domain Port: DenseIndexPort protocol."""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from atenex_nova.domain.repositories.vector_index import VectorDocument


class DenseIndexPort(Protocol):
    """Protocol for full/exact dense and sparse search operations (e.g. Qdrant)."""

    async def init_collection(self, collection_name: str, vector_size: int) -> None:
        """Initialize collection if it does not exist."""
        ...

    async def delete_collection(self, collection_name: str) -> None:
        """Delete collection entirely."""
        ...

    async def delete_by_filter(self, collection_name: str, filter_dict: dict[str, str]) -> None:
        """Delete points in collection matching a payload filter."""
        ...

    async def upsert(self, collection_name: str, documents: Sequence[VectorDocument]) -> None:
        """Upsert a batch of documents containing vectors and payloads."""
        ...

    async def search(
        self,
        collection_name: str,
        query_vector: list[float] | None = None,
        limit: int = 10,
        filter_dict: Mapping[str, str] | None = None,
        query_sparse_indices: list[int] | None = None,
        query_sparse_values: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        """Search the index.

        Returns:
            A list of dicts with keys 'id', 'score', and 'payload'.
        """
        ...

    @property
    def is_available(self) -> bool:
        """Check if the service is currently reachable."""
        ...

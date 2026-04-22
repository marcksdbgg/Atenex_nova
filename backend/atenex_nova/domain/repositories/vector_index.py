"""Vector Index protocol."""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class VectorDocument(Protocol):
    id: str
    vector: list[float]
    payload: Mapping[str, Any]
    sparse_indices: list[int] | None = None
    sparse_values: list[float] | None = None


class HybridIndex(Protocol):
    """Protocol for a vector database index."""

    async def init_collection(self, collection_name: str, vector_size: int) -> None: ...
    async def delete_collection(self, collection_name: str) -> None: ...
    async def upsert(self, collection_name: str, documents: Sequence[VectorDocument]) -> None: ...
    async def search(
        self,
        collection_name: str,
        query_vector: list[float] | None = None,
        limit: int = 10,
        filter_dict: Mapping[str, str] | None = None,
        query_sparse_indices: list[int] | None = None,
        query_sparse_values: list[float] | None = None,
    ) -> list[dict[str, Any]]: ...

"""Vector Index protocol."""

from typing import Protocol


class VectorDocument(Protocol):
    id: str
    vector: list[float]
    payload: dict


class HybridIndex(Protocol):
    """Protocol for a vector database index."""

    async def init_collection(self, collection_name: str, vector_size: int) -> None: ...
    async def delete_collection(self, collection_name: str) -> None: ...
    async def upsert(self, collection_name: str, documents: list[VectorDocument]) -> None: ...
    async def search(self, collection_name: str, query_vector: list[float], limit: int = 10, filter_dict: dict | None = None) -> list[dict]: ...

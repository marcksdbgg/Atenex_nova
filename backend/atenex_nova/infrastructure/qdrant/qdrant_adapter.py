"""Stub: Qdrant vector adapter. Implemented in Fase 3."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class QdrantAdapter:
    """Stub adapter for Qdrant vector database."""

    def __init__(self, url: str = "http://localhost:6333", api_key: str | None = None) -> None:
        self._url = url
        self._api_key = api_key
        logger.info("QdrantAdapter initialized (stub) → %s", url)

    async def ensure_collection(self, name: str, vector_size: int, sparse: bool = False) -> None:
        logger.info("Stub: ensure_collection(%s, dim=%d)", name, vector_size)

    async def upsert(self, collection: str, points: list[dict[str, Any]]) -> None:
        logger.info("Stub: upsert %d points to %s", len(points), collection)

    async def search(
        self, collection: str, vector: list[float], limit: int = 10
    ) -> list[dict[str, Any]]:
        logger.info("Stub: search %s (limit=%d)", collection, limit)
        return []

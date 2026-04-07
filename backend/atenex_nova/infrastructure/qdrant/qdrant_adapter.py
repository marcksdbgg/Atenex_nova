"""Qdrant adapter with graceful local fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from atenex_nova.domain.repositories.vector_index import HybridIndex, VectorDocument

logger = logging.getLogger(__name__)


@dataclass
class QdrantDocument:
    id: str
    vector: list[float]
    payload: dict

class QdrantAdapter(HybridIndex):
    """Adapter for Qdrant vector database."""

    def __init__(self, host: str = "localhost", port: int = 6333) -> None:
        self.client = AsyncQdrantClient(host=host, port=port)
        self._available = True
        logger.info("QdrantAdapter initialized %s:%d", host, port)

    async def init_collection(self, collection_name: str, vector_size: int) -> None:
        """Create collection if it does not exist."""
        if not self._available:
            return
        try:
            exists = await self.client.collection_exists(collection_name)
            if not exists:
                await self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size, distance=models.Distance.COSINE
                    ),
                )
                logger.info("Created Qdrant collection %s", collection_name)
        except Exception as exc:
            logger.warning("Qdrant unavailable, skipping init for %s: %s", collection_name, exc)
            self._available = False

    async def delete_collection(self, collection_name: str) -> None:
        if not self._available:
            return
        try:
            exists = await self.client.collection_exists(collection_name)
            if exists:
                await self.client.delete_collection(collection_name)
                logger.info("Deleted Qdrant collection %s", collection_name)
        except Exception as exc:
            logger.warning("Qdrant unavailable, skipping delete for %s: %s", collection_name, exc)
            self._available = False

    async def delete_by_filter(self, collection_name: str, filter_dict: dict[str, str]) -> None:
        """Delete points in an existing collection using exact-match payload filters."""
        if not self._available or not filter_dict:
            return
        try:
            exists = await self.client.collection_exists(collection_name)
            if not exists:
                return

            must = [
                models.FieldCondition(key=key, match=models.MatchValue(value=value))
                for key, value in filter_dict.items()
            ]
            await self.client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(must=must),
                ),
            )
            logger.info("Deleted filtered points in %s with %s", collection_name, filter_dict)
        except Exception as exc:
            logger.warning("Qdrant unavailable, skipping filtered delete for %s: %s", collection_name, exc)
            self._available = False

    async def upsert(self, collection_name: str, documents: list[VectorDocument]) -> None:
        if not self._available:
            logger.info("Qdrant unavailable, skipping upsert for %s", collection_name)
            return
        points = [
            models.PointStruct(id=doc.id, vector=doc.vector, payload=doc.payload)
            for doc in documents
        ]
        try:
            await self.client.upsert(collection_name=collection_name, points=points)
        except Exception as exc:
            logger.warning("Qdrant upsert failed for %s: %s", collection_name, exc)
            self._available = False

    async def search(
        self, collection_name: str, query_vector: list[float], limit: int = 10, filter_dict: dict | None = None
    ) -> list[dict]:
        if not self._available:
            return []
        # Very basic translation for exact match filters, assuming a single key-value
        qdrant_filter = None
        if filter_dict:
            must = []
            for k, v in filter_dict.items():
                must.append(models.FieldCondition(key=k, match=models.MatchValue(value=v)))
            qdrant_filter = models.Filter(must=must)
            
        try:
            results = await self.client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter=qdrant_filter,
                with_payload=True,
            )
        except Exception as exc:
            logger.warning("Qdrant search failed for %s: %s", collection_name, exc)
            self._available = False
            return []
        return [
            {"id": str(res.id), "score": res.score, "payload": res.payload}
            for res in results
        ]

    @property
    def is_available(self) -> bool:
        return self._available

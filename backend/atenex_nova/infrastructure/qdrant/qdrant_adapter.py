"""Qdrant adapter."""

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
        logger.info("QdrantAdapter initialized %s:%d", host, port)

    async def init_collection(self, collection_name: str, vector_size: int) -> None:
        """Create collection if it does not exist."""
        exists = await self.client.collection_exists(collection_name)
        if not exists:
            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size, distance=models.Distance.COSINE
                ),
            )
            logger.info("Created Qdrant collection %s", collection_name)

    async def delete_collection(self, collection_name: str) -> None:
        exists = await self.client.collection_exists(collection_name)
        if exists:
            await self.client.delete_collection(collection_name)
            logger.info("Deleted Qdrant collection %s", collection_name)

    async def upsert(self, collection_name: str, documents: list[VectorDocument]) -> None:
        points = [
            models.PointStruct(id=doc.id, vector=doc.vector, payload=doc.payload)
            for doc in documents
        ]
        await self.client.upsert(collection_name=collection_name, points=points)

    async def search(
        self, collection_name: str, query_vector: list[float], limit: int = 10, filter_dict: dict | None = None
    ) -> list[dict]:
        # Very basic translation for exact match filters, assuming a single key-value
        qdrant_filter = None
        if filter_dict:
            must = []
            for k, v in filter_dict.items():
                must.append(models.FieldCondition(key=k, match=models.MatchValue(value=v)))
            qdrant_filter = models.Filter(must=must)
            
        results = await self.client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=limit,
            query_filter=qdrant_filter,
            with_payload=True
        )
        return [
            {"id": str(res.id), "score": res.score, "payload": res.payload}
            for res in results
        ]

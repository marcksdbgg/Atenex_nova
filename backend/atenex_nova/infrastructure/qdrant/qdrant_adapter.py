"""Qdrant adapter with graceful local fallback."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from atenex_nova.domain.repositories.vector_index import HybridIndex, VectorDocument
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import ServiceUnavailableError

logger = logging.getLogger(__name__)


@dataclass
class QdrantDocument:
    id: str
    vector: list[float]
    payload: Mapping[str, Any]


class QdrantAdapter(HybridIndex):
    """Adapter for Qdrant vector database."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        required: bool | None = None,
        retry_cooldown_seconds: float = 5.0,
    ) -> None:
        settings = get_settings()
        self.client = AsyncQdrantClient(host=host, port=port)
        self._available = True
        self._required = settings.qdrant_required if required is None else required
        self._failure_count = 0
        self._next_retry_at = 0.0
        self._retry_cooldown_seconds = max(retry_cooldown_seconds, 1.0)
        logger.info("QdrantAdapter initialized %s:%d", host, port)

    def _can_attempt(self) -> bool:
        if self._available:
            return True
        return time.monotonic() >= self._next_retry_at

    def _register_success(self) -> None:
        self._available = True
        self._failure_count = 0
        self._next_retry_at = 0.0

    def _register_failure(self, operation: str, exc: Exception) -> None:
        self._available = False
        self._failure_count += 1
        backoff = min(self._retry_cooldown_seconds * (2 ** (self._failure_count - 1)), 30.0)
        self._next_retry_at = time.monotonic() + backoff
        if self._required:
            raise ServiceUnavailableError("qdrant", f"{operation} failed: {exc}") from exc
        logger.warning(
            "Qdrant %s failed: %s (retry in %.1fs)",
            operation,
            exc,
            backoff,
        )

    def _guard(self, operation: str) -> bool:
        if self._can_attempt():
            return True
        wait_for = max(self._next_retry_at - time.monotonic(), 0.0)
        if self._required:
            raise ServiceUnavailableError(
                "qdrant",
                f"{operation} blocked by retry cooldown ({wait_for:.1f}s remaining)",
            )
        logger.info("Qdrant unavailable, skipping %s (retry in %.1fs)", operation, wait_for)
        return False

    async def init_collection(self, collection_name: str, vector_size: int) -> None:
        """Create collection if it does not exist."""
        if not self._guard("init_collection"):
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
            self._register_success()
        except Exception as exc:
            self._register_failure(f"init collection '{collection_name}'", exc)

    async def delete_collection(self, collection_name: str) -> None:
        if not self._guard("delete_collection"):
            return
        try:
            exists = await self.client.collection_exists(collection_name)
            if exists:
                await self.client.delete_collection(collection_name)
                logger.info("Deleted Qdrant collection %s", collection_name)
            self._register_success()
        except Exception as exc:
            self._register_failure(f"delete collection '{collection_name}'", exc)

    async def delete_by_filter(self, collection_name: str, filter_dict: dict[str, str]) -> None:
        """Delete points in an existing collection using exact-match payload filters."""
        if not filter_dict:
            return
        if not self._guard("delete_by_filter"):
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
            self._register_success()
        except Exception as exc:
            self._register_failure(f"delete filtered points in '{collection_name}'", exc)

    async def upsert(self, collection_name: str, documents: Sequence[VectorDocument]) -> None:
        if not documents:
            return
        if not self._guard("upsert"):
            return
        points = [
            models.PointStruct(id=doc.id, vector=doc.vector, payload=doc.payload)
            for doc in documents
        ]
        try:
            await self.client.upsert(collection_name=collection_name, points=points)
            self._register_success()
        except Exception as exc:
            self._register_failure(f"upsert points in '{collection_name}'", exc)

    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int = 10,
        filter_dict: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        if not self._guard("search"):
            return []
        # Very basic translation for exact match filters, assuming a single key-value
        qdrant_filter = None
        if filter_dict:
            must = []
            for k, v in filter_dict.items():
                must.append(models.FieldCondition(key=k, match=models.MatchValue(value=v)))
            qdrant_filter = models.Filter(must=must)

        try:
            results = await self.client.search(  # type: ignore[attr-defined]
                collection_name=collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter=qdrant_filter,
                with_payload=True,
            )
            self._register_success()
        except Exception as exc:
            self._register_failure(f"search collection '{collection_name}'", exc)
            return []
        return [
            {
                "id": str(res.id),
                "score": float(res.score),
                "payload": cast(dict[str, Any], res.payload or {}),
            }
            for res in results
        ]

    @property
    def is_available(self) -> bool:
        return self._available

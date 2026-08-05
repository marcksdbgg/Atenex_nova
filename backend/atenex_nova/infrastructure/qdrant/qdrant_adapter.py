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
    vector: list[float] | None
    payload: Mapping[str, Any]
    sparse_indices: list[int] | None = None
    sparse_values: list[float] | None = None


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
        exc_str = str(exc)
        self._available = False
        self._failure_count += 1
        backoff = min(self._retry_cooldown_seconds * (2 ** (self._failure_count - 1)), 30.0)
        self._next_retry_at = time.monotonic() + backoff
        if self._required:
            raise ServiceUnavailableError("qdrant", f"{operation} failed: {exc}") from exc
        if "404" in exc_str or "not found" in exc_str.lower() or "doesn't exist" in exc_str:
            logger.warning("Qdrant collection missing during %s: %s", operation, exc)
        elif (
            "400" in exc_str
            or "not existing vector name" in exc_str.lower()
            or "wrong input" in exc_str.lower()
            or "invalid" in exc_str.lower()
            or "schema" in exc_str.lower()
        ):
            logger.warning("Qdrant schema or validation failure during %s: %s", operation, exc)
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

    async def init_collection(
        self, collection_name: str, vector_size: int, *, dense_enabled: bool = True
    ) -> None:
        """Create collection if it does not exist."""
        if not self._guard("init_collection"):
            return
        try:
            exists = await self.client.collection_exists(collection_name)
            if not exists:
                if dense_enabled:
                    await self.client.create_collection(
                        collection_name=collection_name,
                        vectors_config={
                            "dense": models.VectorParams(
                                size=vector_size, distance=models.Distance.COSINE
                            )
                        },
                        sparse_vectors_config={"sparse": models.SparseVectorParams()},
                    )
                else:
                    await self.client.create_collection(
                        collection_name=collection_name,
                        sparse_vectors_config={"sparse": models.SparseVectorParams()},
                    )
                logger.info(
                    "Created Qdrant collection %s (dense=%s)",
                    collection_name,
                    dense_enabled,
                )
            else:
                info = await self.client.get_collection(collection_name)
                self._validate_collection_schema(
                    info,
                    vector_size=vector_size,
                    dense_enabled=dense_enabled,
                )
            self._register_success()
        except Exception as exc:
            self._register_failure(f"init collection '{collection_name}'", exc)

    @classmethod
    def _validate_collection_schema(
        cls,
        info: object,
        *,
        vector_size: int,
        dense_enabled: bool,
    ) -> None:
        """Reject incompatible existing collections instead of mixing generations."""

        config = cls._field(info, "config")
        params = cls._field(config, "params")
        vectors = cls._field(params, "vectors")
        sparse_vectors = cls._field(params, "sparse_vectors")

        dense = cls._field(vectors, "dense") if vectors is not None else None
        sparse = cls._field(sparse_vectors, "sparse") if sparse_vectors is not None else None
        if dense_enabled:
            if dense is None:
                raise ValueError(
                    "Qdrant schema mismatch: named dense vector 'dense' is missing; "
                    "rebuild the collection before indexing"
                )
            size = cls._field(dense, "size")
            if size is None or int(cast(Any, size)) != int(vector_size):
                raise ValueError(
                    "Qdrant schema mismatch: dense vector dimension is "
                    f"{size!r}, expected {vector_size}"
                )
        if sparse is None:
            raise ValueError(
                "Qdrant schema mismatch: named sparse vector 'sparse' is missing; "
                "rebuild the collection before indexing"
            )

    @staticmethod
    def _field(value: object, name: str) -> object | None:
        if value is None:
            return None
        if isinstance(value, Mapping):
            return value.get(name)
        return getattr(value, name, None)

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

    async def list_collections(self) -> list[dict[str, str]]:
        if not self._guard("list_collections"):
            return []
        try:
            collections = await self.client.get_collections()
            self._register_success()
            return [{"name": item.name} for item in collections.collections]
        except Exception as exc:
            self._register_failure("list collections", exc)
            return []

    async def delete_points(
        self,
        collection_name: str,
        point_ids: Sequence[str | int],
        *,
        batch_size: int = 256,
    ) -> None:
        """Delete known point IDs without ever broadening an empty selection.

        IDs are de-duplicated and sent in bounded batches. A missing collection is
        already clean, so the operation remains idempotent. Required deployments
        raise through ``_register_failure``; optional deployments expose the failed
        cleanup through ``is_available`` and the retry backoff.
        """
        if not collection_name.strip():
            raise ValueError("collection_name must not be empty")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        unique_ids = list(dict.fromkeys(point_ids))
        if not unique_ids or not self._guard("delete_points"):
            return
        try:
            exists = await self.client.collection_exists(collection_name)
            if not exists:
                self._register_success()
                return
            for offset in range(0, len(unique_ids), batch_size):
                await self.client.delete(
                    collection_name=collection_name,
                    points_selector=models.PointIdsList(
                        points=cast(
                            list[Any],
                            unique_ids[offset : offset + batch_size],
                        )
                    ),
                    wait=True,
                )
            logger.info(
                "Deleted %d explicit points in %s",
                len(unique_ids),
                collection_name,
            )
            self._register_success()
        except Exception as exc:
            self._register_failure(f"delete points in '{collection_name}'", exc)

    async def delete_by_filter(
        self,
        collection_name: str,
        filter_dict: Mapping[str, str | int | bool],
    ) -> None:
        """Delete points using a non-empty conjunction of exact payload matches."""
        if not collection_name.strip():
            raise ValueError("collection_name must not be empty")
        if not filter_dict:
            return
        if any(not key.strip() for key in filter_dict):
            raise ValueError("payload filter keys must not be empty")
        if not self._guard("delete_by_filter"):
            return
        try:
            exists = await self.client.collection_exists(collection_name)
            if not exists:
                self._register_success()
                return

            must = [
                models.FieldCondition(key=key, match=models.MatchValue(value=value))
                for key, value in filter_dict.items()
            ]
            await self.client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(must=cast(Any, must)),
                ),
                wait=True,
            )
            logger.info("Deleted filtered points in %s with %s", collection_name, filter_dict)
            self._register_success()
        except Exception as exc:
            self._register_failure(f"delete filtered points in '{collection_name}'", exc)

    async def upsert(
        self,
        collection_name: str,
        documents: Sequence[VectorDocument],
        *,
        batch_size: int = 256,
    ) -> None:
        """Upsert points in bounded, ordered, retry-safe batches.

        Stable point IDs make a retry after a partial remote write idempotent. The
        adapter is marked healthy only after every batch has completed.
        """
        if not collection_name.strip():
            raise ValueError("collection_name must not be empty")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if not documents:
            return
        if not self._guard("upsert"):
            return
        points = []
        for doc in documents:
            vector_dict: dict[str, Any] = {}
            if doc.vector is not None:
                vector_dict["dense"] = doc.vector
            if doc.sparse_indices and doc.sparse_values:
                vector_dict["sparse"] = models.SparseVector(
                    indices=doc.sparse_indices, values=doc.sparse_values
                )
            if not vector_dict:
                logger.warning("Skipping Qdrant point %s: no dense or sparse vector", doc.id)
                continue
            points.append(
                models.PointStruct(
                    id=doc.id,
                    vector=vector_dict,
                    payload=dict(doc.payload),
                )
            )
        if not points:
            return
        completed_batches = 0
        try:
            for offset in range(0, len(points), batch_size):
                await self.client.upsert(
                    collection_name=collection_name,
                    points=points[offset : offset + batch_size],
                    wait=True,
                )
                completed_batches += 1
            self._register_success()
            logger.info(
                "Upserted %d points into %s in %d batch(es)",
                len(points),
                collection_name,
                completed_batches,
            )
        except Exception as exc:
            operation = f"upsert batch {completed_batches + 1} in '{collection_name}'"
            self._register_failure(operation, exc)
            if completed_batches:
                # Optional mode may tolerate a completely unavailable Qdrant, but
                # it must never publish a prefix of a logical upsert as complete.
                raise ServiceUnavailableError(
                    "qdrant",
                    f"{operation} failed after {completed_batches} completed batch(es); "
                    "retry the idempotent upsert",
                ) from exc

    async def search(
        self,
        collection_name: str,
        query_vector: list[float] | None = None,
        limit: int = 10,
        filter_dict: Mapping[str, str] | None = None,
        query_sparse_indices: list[int] | None = None,
        query_sparse_values: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        if not self._guard("search"):
            return []
        # Very basic translation for exact match filters, assuming a single key-value
        qdrant_filter = None
        if filter_dict:
            must = []
            for k, v in filter_dict.items():
                must.append(models.FieldCondition(key=k, match=models.MatchValue(value=v)))
            qdrant_filter = models.Filter(must=cast(Any, must))

        try:
            legacy_search = getattr(self.client, "search", None)
            if callable(legacy_search):
                q_vector: Any
                if query_sparse_indices is not None and query_sparse_values is not None:
                    named_sparse_vector = vars(models)["NamedSparseVector"]
                    q_vector = named_sparse_vector(
                        name="sparse",
                        vector=models.SparseVector(
                            indices=query_sparse_indices, values=query_sparse_values
                        ),
                    )
                else:
                    named_vector = vars(models)["NamedVector"]
                    q_vector = named_vector(
                        name="dense", vector=query_vector or []
                    )

                try:
                    results = await legacy_search(
                        collection_name=collection_name,
                        query_vector=q_vector,
                        limit=limit,
                        query_filter=qdrant_filter,
                        with_payload=True,
                    )
                except Exception as exc:
                    if not (query_sparse_indices is not None and query_sparse_values is not None):
                        results = await legacy_search(
                            collection_name=collection_name,
                            query_vector=query_vector or [],
                            limit=limit,
                            query_filter=qdrant_filter,
                            with_payload=True,
                        )
                    else:
                        raise exc
            else:
                if query_sparse_indices is not None and query_sparse_values is not None:
                    query_val: Any = models.SparseVector(
                        indices=query_sparse_indices, values=query_sparse_values
                    )
                    using_val = "sparse"
                else:
                    query_val = query_vector or []
                    using_val = "dense"

                try:
                    res = await self.client.query_points(
                        collection_name=collection_name,
                        query=query_val,
                        using=using_val,
                        limit=limit,
                        query_filter=qdrant_filter,
                        with_payload=True,
                    )
                    results = res.points
                except Exception as query_exc:
                    if ("Not existing vector name" in str(query_exc) or "Not found" in str(query_exc)) and using_val == "dense":
                        res = await self.client.query_points(
                            collection_name=collection_name,
                            query=query_val,
                            using=None,
                            limit=limit,
                            query_filter=qdrant_filter,
                            with_payload=True,
                        )
                        results = res.points
                    else:
                        raise query_exc
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

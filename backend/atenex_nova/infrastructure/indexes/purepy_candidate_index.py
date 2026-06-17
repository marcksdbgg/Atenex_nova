"""Infrastructure: Pure-Python TurboQuant Candidate Index (no turbovec)."""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.ports.candidate_index import CandidateIndexPort
from atenex_nova.infrastructure.indexes.quantized_code_store import QuantizedCodeStore
from atenex_nova.infrastructure.vector_quantization.turboquant_adapter import TurboQuantAdapter

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_MAX_SIZE = 32


@dataclass
class _ProfileBatch:
    node_ids: list[str] = field(default_factory=list)
    codes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _LayerCacheEntry:
    by_profile: dict[str, _ProfileBatch] = field(default_factory=dict)


class PurePyTurboQuantCandidateIndex(CandidateIndexPort):
    """Candidate index that scores quantized SQL codes via TurboQuant IP estimation."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        quantizer: TurboQuantAdapter | None = None,
        cache_max_size: int = _DEFAULT_CACHE_MAX_SIZE,
    ) -> None:
        self._session = session
        self._store = QuantizedCodeStore(session)
        self._quantizer = quantizer or TurboQuantAdapter()
        self._cache_max_size = max(1, cache_max_size)
        self._cache: OrderedDict[tuple[str, str], _LayerCacheEntry] = OrderedDict()

    async def add_vectors(
        self,
        collection_id: str,
        memory_layer: str,
        node_ids: list[str],
        vectors: list[list[float]],
    ) -> None:
        """Invalidate layer cache; persistence is handled upstream (IngestionOrchestrator)."""
        if not node_ids:
            return
        self._invalidate_layer(collection_id, memory_layer)
        logger.debug(
            "Invalidated purepy cache for collection=%s layer=%s (%d nodes)",
            collection_id,
            memory_layer,
            len(node_ids),
        )

    async def search(
        self,
        collection_id: str,
        memory_layers: list[str],
        query_vector: list[float],
        top_n: int = 200,
    ) -> list[dict[str, Any]]:
        """Score all codes in the requested layers and return top_n candidates."""
        if not memory_layers or not query_vector:
            return []

        all_results: list[dict[str, Any]] = []
        for layer in memory_layers:
            entry = await self._load_layer(collection_id, layer)
            for profile_id, batch in entry.by_profile.items():
                if not batch.codes:
                    continue
                profile = await self._store.get_profile(profile_id)
                if profile is None:
                    logger.warning("Missing quantization profile %s; skipping batch", profile_id)
                    continue
                scores = self._quantizer.estimate_inner_products(
                    query_vector, batch.codes, profile
                )
                for node_id, score in zip(batch.node_ids, scores, strict=False):
                    all_results.append(
                        {
                            "node_id": node_id,
                            "score": float(score),
                            "memory_layer": layer,
                        }
                    )

        all_results.sort(key=lambda item: item["score"], reverse=True)
        return all_results[:top_n]

    async def remove_vectors(self, collection_id: str, node_ids: list[str]) -> None:
        """Remove quantized codes from SQL and invalidate cached layers."""
        if not node_ids:
            return
        await self._store.delete_by_node_ids(node_ids)
        self._invalidate_collection(collection_id)
        logger.info(
            "Removed %d quantized vectors for collection %s", len(node_ids), collection_id
        )

    async def delete_collection_indexes(self, collection_id: str) -> None:
        """Delete all quantized codes for the collection and clear cache."""
        await self._store.delete_by_collection(collection_id)
        self._invalidate_collection(collection_id)
        logger.info("Deleted purepy candidate index data for collection %s", collection_id)

    async def _load_layer(self, collection_id: str, memory_layer: str) -> _LayerCacheEntry:
        key = (collection_id, memory_layer)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        vectors = await self._store.get_vectors_by_layer(collection_id, memory_layer)
        by_profile: dict[str, _ProfileBatch] = {}
        for vector in vectors:
            batch = by_profile.setdefault(vector.profile_id, _ProfileBatch())
            batch.node_ids.append(vector.node_id)
            batch.codes.append(
                {
                    "idx_blob": vector.idx_blob,
                    "qjl_blob": vector.qjl_blob,
                    "residual_norm": vector.residual_norm,
                    "vector_norm": vector.vector_norm,
                }
            )

        entry = _LayerCacheEntry(by_profile=by_profile)
        self._cache[key] = entry
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_max_size:
            self._cache.popitem(last=False)
        return entry

    def _invalidate_layer(self, collection_id: str, memory_layer: str) -> None:
        self._cache.pop((collection_id, memory_layer), None)

    def _invalidate_collection(self, collection_id: str) -> None:
        keys_to_remove = [key for key in self._cache if key[0] == collection_id]
        for key in keys_to_remove:
            del self._cache[key]

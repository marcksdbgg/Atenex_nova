"""Infrastructure: TurboQuant Candidate Index."""

import contextlib
import logging
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.ports.candidate_index import CandidateIndexPort
from atenex_nova.infrastructure.indexes.quantized_code_store import QuantizedCodeStore
from atenex_nova.shared.config.settings import get_settings

logger = logging.getLogger(__name__)

_TURBOVEC_INSTALL_HINT = (
    "turbovec is required for TurboQuant candidate index operations. "
    "Install with: pip install 'atenex-nova[accel]'"
)


def _id_map_index_type() -> Any:
    try:
        from turbovec import IdMapIndex  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(_TURBOVEC_INSTALL_HINT) from exc
    return IdMapIndex


def string_to_uint64(s: str) -> int:
    """Convert a string ID deterministically to a signed 64-bit integer (fits SQLite/Postgres BigInteger)."""
    try:
        import uuid
        val = uuid.UUID(s).int
        val = val & 0xFFFFFFFFFFFFFFFF
    except ValueError:
        import hashlib
        h = hashlib.sha256(s.encode("utf-8")).digest()
        val = int.from_bytes(h[:8], byteorder="little")
    if val >= 0x8000000000000000:
        val -= 0x10000000000000000
    return val


class TurboQuantCandidateIndex(CandidateIndexPort):
    """Candidate Index implementing TurboQuantprod dense search using local turbovec indices."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._store = QuantizedCodeStore(session)
        self._settings = get_settings()
        self._storage_dir = Path(self._settings.turbovec_path)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    async def add_vectors(
        self,
        collection_id: str,
        memory_layer: str,
        node_ids: list[str],
        vectors: list[list[float]],
    ) -> None:
        """Add a batch of vectors to the local IdMapIndex file."""
        if not node_ids or not vectors:
            return

        id_map_index_cls = _id_map_index_type()
        index_path = self._storage_dir / f"{collection_id}_{memory_layer}.tvim"
        bit_width = self._settings.turbovec_bit_width if hasattr(self._settings, "turbovec_bit_width") else 4
        dim = len(vectors[0])

        if index_path.exists():
            try:
                index = id_map_index_cls.load(str(index_path))
            except Exception as e:
                logger.warning("Error loading IdMapIndex, creating fresh: %s", e)
                index = id_map_index_cls(dim=dim, bit_width=bit_width)
        else:
            index = id_map_index_cls(dim=dim, bit_width=bit_width)

        vec_array = np.array(vectors, dtype=np.float32)
        uint64_ids = np.array([string_to_uint64(nid) & 0xFFFFFFFFFFFFFFFF for nid in node_ids], dtype=np.uint64)

        # Clear existing keys first to avoid duplicates
        for uid in uint64_ids:
            with contextlib.suppress(Exception):
                index.remove(uid)

        index.add_with_ids(vec_array, uint64_ids)
        index.write(str(index_path))
        logger.info(
            "Added %d vectors to %s index: %s", len(node_ids), memory_layer, index_path.name
        )

    async def search(
        self,
        collection_id: str,
        memory_layers: list[str],
        query_vector: list[float],
        top_n: int = 200,
    ) -> list[dict[str, Any]]:
        """Search the candidate index files across memory layers and map uint64 ids back to nodes."""
        id_map_index_cls = _id_map_index_type()
        query_arr = np.array([query_vector], dtype=np.float32)
        all_candidates: list[tuple[str, float, int]] = []
        all_uint64_ids = []

        for layer in memory_layers:
            index_path = self._storage_dir / f"{collection_id}_{layer}.tvim"
            if not index_path.exists():
                continue

            try:
                index = id_map_index_cls.load(str(index_path))
                # Search the index for this layer
                scores, ids = index.search(query_arr, k=top_n)
                if len(scores) > 0 and len(ids) > 0:
                    for s, uid in zip(scores[0], ids[0], strict=False):
                        uid_val = int(uid)
                        if uid_val >= 0x8000000000000000:
                            uid_val -= 0x10000000000000000
                        all_candidates.append((layer, float(s), uid_val))
                        all_uint64_ids.append(uid_val)
            except Exception as e:
                logger.warning("Error searching index %s: %s", index_path.name, e)

        if not all_uint64_ids:
            return []

        # Resolve uint64 IDs to original UUID string node IDs in bulk from SQL
        vectors = await self._store.get_vectors_by_uint64_ids(all_uint64_ids)
        uint_to_node = {v.uint64_id: (v.node_id, v.memory_layer) for v in vectors}

        results: list[dict[str, Any]] = []
        for _layer, score, uid_val in all_candidates:
            if uid_val in uint_to_node:
                node_id, mem_layer = uint_to_node[uid_val]
                results.append(
                    {
                        "node_id": node_id,
                        "score": score,
                        "memory_layer": mem_layer,
                    }
                )

        # Sort overall results by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_n]

    async def remove_vectors(self, collection_id: str, node_ids: list[str]) -> None:
        """Remove a batch of vectors by node IDs from all collection indexes."""
        if not node_ids:
            return

        id_map_index_cls = _id_map_index_type()
        index_files = list(self._storage_dir.glob(f"{collection_id}_*.tvim"))
        uint64_ids = [string_to_uint64(nid) & 0xFFFFFFFFFFFFFFFF for nid in node_ids]

        for index_path in index_files:
            try:
                index = id_map_index_cls.load(str(index_path))
                removed_count = 0
                for uid in uint64_ids:
                    try:
                        index.remove(uid)
                        removed_count += 1
                    except Exception:
                        pass
                if removed_count > 0:
                    index.write(str(index_path))
                    logger.info("Removed %d vectors from index %s", removed_count, index_path.name)
            except Exception as e:
                logger.warning("Error removing vectors from %s: %s", index_path.name, e)

    async def delete_collection_indexes(self, collection_id: str) -> None:
        """Delete all index files associated with the collection."""
        index_files = list(self._storage_dir.glob(f"{collection_id}_*.tvim"))
        for index_path in index_files:
            try:
                index_path.unlink()
                logger.info("Deleted index file: %s", index_path.name)
            except Exception as e:
                logger.warning("Error deleting index file %s: %s", index_path.name, e)
        # Also clean up quantized code store database records
        await self._store.delete_by_collection(collection_id)

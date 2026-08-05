"""Infrastructure: Quantized Code Store."""

import logging
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.infrastructure.db.models.tables import (
    QuantizationProfileModel,
    QuantizedVectorModel,
)

logger = logging.getLogger(__name__)
_SQL_IN_BATCH_SIZE = 900


@dataclass(frozen=True, slots=True)
class QuantizedVectorWrite:
    """One quantized vector mutation resolved by ``node_id``."""

    node_id: str
    uint64_id: int
    collection_id: str
    memory_layer: str
    profile_id: str
    idx_blob: bytes
    qjl_blob: bytes
    residual_norm: float
    vector_norm: float


class QuantizedCodeStore:
    """Store for managing serialization, retrieval and deletion of quantized codes in SQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_profile(self, profile: QuantizationProfileModel) -> None:
        """Save a quantization profile to the database."""
        self._session.add(profile)

    async def get_profile(self, profile_id: str) -> QuantizationProfileModel | None:
        """Fetch a profile by its string UUID id."""
        stmt = select(QuantizationProfileModel).where(col(QuantizationProfileModel.id) == profile_id)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_profile_by_config(
        self,
        embedding_model: str,
        dimension: int,
        bit_width: int,
        codebook_version: str,
    ) -> QuantizationProfileModel | None:
        """Find an existing profile matching the configuration settings."""
        stmt = select(QuantizationProfileModel).where(
            col(QuantizationProfileModel.embedding_model) == embedding_model,
            col(QuantizationProfileModel.dimension) == dimension,
            col(QuantizationProfileModel.bit_width) == bit_width,
            col(QuantizationProfileModel.codebook_version) == codebook_version,
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def save_vector(
        self,
        node_id: str,
        uint64_id: int,
        collection_id: str,
        memory_layer: str,
        profile_id: str,
        idx_blob: bytes,
        qjl_blob: bytes,
        residual_norm: float,
        vector_norm: float,
    ) -> None:
        """Backward-compatible single-vector write."""
        await self.save_vectors(
            [
                QuantizedVectorWrite(
                    node_id=node_id,
                    uint64_id=uint64_id,
                    collection_id=collection_id,
                    memory_layer=memory_layer,
                    profile_id=profile_id,
                    idx_blob=idx_blob,
                    qjl_blob=qjl_blob,
                    residual_norm=residual_norm,
                    vector_norm=vector_norm,
                )
            ]
        )

    async def save_vectors(self, vectors: list[QuantizedVectorWrite]) -> None:
        """Insert or update a vector batch with bounded lookups and one flush."""
        if not vectors:
            return

        node_ids = [vector.node_id for vector in vectors]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("quantized vector batch contains duplicate node_ids")

        existing_by_node_id: dict[str, QuantizedVectorModel] = {}
        for offset in range(0, len(node_ids), _SQL_IN_BATCH_SIZE):
            lookup_ids = node_ids[offset : offset + _SQL_IN_BATCH_SIZE]
            result = await self._session.execute(
                select(QuantizedVectorModel).where(
                    col(QuantizedVectorModel.node_id).in_(lookup_ids)
                )
            )
            for model in result.scalars().all():
                if model.node_id in existing_by_node_id:
                    raise ValueError(
                        "multiple quantized vectors already exist for "
                        f"node_id {model.node_id}"
                    )
                existing_by_node_id[model.node_id] = model

        new_models: list[QuantizedVectorModel] = []
        for vector in vectors:
            existing = existing_by_node_id.get(vector.node_id)
            if existing is not None:
                existing.uint64_id = vector.uint64_id
                existing.collection_id = vector.collection_id
                existing.memory_layer = vector.memory_layer
                existing.profile_id = vector.profile_id
                existing.idx_blob = vector.idx_blob
                existing.qjl_blob = vector.qjl_blob
                existing.residual_norm = vector.residual_norm
                existing.vector_norm = vector.vector_norm
                continue

            new_models.append(
                QuantizedVectorModel(
                    id=new_id(),
                    node_id=vector.node_id,
                    uint64_id=vector.uint64_id,
                    collection_id=vector.collection_id,
                    memory_layer=vector.memory_layer,
                    profile_id=vector.profile_id,
                    idx_blob=vector.idx_blob,
                    qjl_blob=vector.qjl_blob,
                    residual_norm=vector.residual_norm,
                    vector_norm=vector.vector_norm,
                )
            )

        self._session.add_all(new_models)
        await self._session.flush()

    async def get_vectors_by_uint64_ids(self, uint64_ids: list[int]) -> list[QuantizedVectorModel]:
        """Fetch quantized vectors corresponding to the uint64 ids."""
        if not uint64_ids:
            return []
        stmt = select(QuantizedVectorModel).where(col(QuantizedVectorModel.uint64_id).in_(uint64_ids))
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def get_vectors_by_layer(
        self, collection_id: str, memory_layer: str
    ) -> list[QuantizedVectorModel]:
        """Fetch all quantized vectors for a collection layer."""
        stmt = select(QuantizedVectorModel).where(
            col(QuantizedVectorModel.collection_id) == collection_id,
            col(QuantizedVectorModel.memory_layer) == memory_layer,
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def count_vectors_by_layer(self, collection_id: str, memory_layer: str) -> int:
        """Count a layer without materializing its quantized payloads."""
        stmt = select(func.count()).select_from(QuantizedVectorModel).where(
            col(QuantizedVectorModel.collection_id) == collection_id,
            col(QuantizedVectorModel.memory_layer) == memory_layer,
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def delete_by_collection(self, collection_id: str) -> None:
        """Delete all quantized vectors for a collection."""
        stmt = delete(QuantizedVectorModel).where(
            col(QuantizedVectorModel.collection_id) == collection_id
        )
        await self._session.execute(stmt)

    async def delete_by_node_ids(self, node_ids: list[str]) -> None:
        """Delete specific quantized vectors by node UUIDs."""
        if not node_ids:
            return
        stmt = delete(QuantizedVectorModel).where(col(QuantizedVectorModel.node_id).in_(node_ids))
        await self._session.execute(stmt)

"""Infrastructure: Quantized Code Store."""

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.infrastructure.db.models.tables import (
    QuantizationProfileModel,
    QuantizedVectorModel,
)

logger = logging.getLogger(__name__)


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
        self, embedding_model: str, dimension: int, bit_width: int
    ) -> QuantizationProfileModel | None:
        """Find an existing profile matching the configuration settings."""
        stmt = select(QuantizationProfileModel).where(
            col(QuantizationProfileModel.embedding_model) == embedding_model,
            col(QuantizationProfileModel.dimension) == dimension,
            col(QuantizationProfileModel.bit_width) == bit_width,
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
        """Insert or update a quantized vector record."""
        stmt = select(QuantizedVectorModel).where(col(QuantizedVectorModel.node_id) == node_id)
        res = await self._session.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing:
            existing.uint64_id = uint64_id
            existing.collection_id = collection_id
            existing.memory_layer = memory_layer
            existing.profile_id = profile_id
            existing.idx_blob = idx_blob
            existing.qjl_blob = qjl_blob
            existing.residual_norm = residual_norm
            existing.vector_norm = vector_norm
        else:
            model = QuantizedVectorModel(
                id=new_id(),
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
            self._session.add(model)

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

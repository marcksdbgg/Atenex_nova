"""Integration test: collection cleanup removes quantized_vectors (SA-6 / H-2)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.application.services.collection_cleanup_service import CollectionCleanupService
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.models.tables import (
    QuantizationProfileModel,
    QuantizedVectorModel,
)
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.indexes.quantized_code_store import QuantizedCodeStore
from atenex_nova.infrastructure.indexes.turboquant_candidate_index import string_to_uint64
from atenex_nova.infrastructure.vector_quantization.turboquant_adapter import TurboQuantAdapter


@dataclass
class _NoopQdrant:
    """Minimal Qdrant stand-in for cleanup tests."""

    _available: bool = True

    async def delete_collection(self, collection_name: str) -> None:
        return None

    async def delete_by_filter(self, collection_name: str, payload_filter: dict[str, object]) -> None:
        return None

    @property
    def is_available(self) -> bool:
        return self._available


@pytest.fixture()
async def session_factory(tmp_path: Path):
    db_path = tmp_path / "cleanup-codes.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_collection_with_codes(factory) -> str:
    profile = QuantizationProfileModel(
        id=new_id(),
        algorithm="turboquant_prod",
        embedding_model="embeddinggemma",
        dimension=384,
        bit_width=4,
        rotation_seed=42,
        qjl_seed=1337,
        codebook_version="v1",
    )
    vector = [0.3] * 384

    async with factory() as session:
        collection_repo = SqlCollectionRepository(session)
        store = QuantizedCodeStore(session)
        adapter = TurboQuantAdapter()

        collection = Collection(id=new_id(), name="Cleanup Codes", description="SA-6 cleanup")
        await collection_repo.create(collection)

        await store.save_profile(profile)
        for _ in range(3):
            node_id = new_id()
            code = adapter.quantize(vector, profile)
            await store.save_vector(
                node_id=node_id,
                uint64_id=string_to_uint64(node_id),
                collection_id=collection.id,
                memory_layer="chunk",
                profile_id=profile.id,
                idx_blob=code["idx_blob"],
                qjl_blob=code["qjl_blob"],
                residual_norm=code["residual_norm"],
                vector_norm=code["vector_norm"],
            )
        await session.commit()
        return collection.id


@pytest.mark.asyncio
async def test_delete_collection_removes_quantized_vectors(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "atenex_nova.application.services.collection_cleanup_service.QdrantAdapter",
        lambda **kwargs: _NoopQdrant(),
    )

    collection_id = await _seed_collection_with_codes(session_factory)

    async with session_factory() as session:
        count_before = (
            await session.execute(
                select(func.count())
                .select_from(QuantizedVectorModel)
                .where(QuantizedVectorModel.collection_id == collection_id)
            )
        ).scalar_one()
        assert count_before == 3

        cleanup = CollectionCleanupService(session)
        deleted = await cleanup.delete_collection(collection_id)
        await session.commit()
        assert deleted is True

        count_after = (
            await session.execute(
                select(func.count())
                .select_from(QuantizedVectorModel)
                .where(QuantizedVectorModel.collection_id == collection_id)
            )
        ).scalar_one()
        assert count_after == 0

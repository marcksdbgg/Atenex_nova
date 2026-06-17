"""Integration test: single canonical dense copy (SA-5 / H-2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.application.orchestrators.ingestion_orchestrator import IngestionOrchestrator
from atenex_nova.application.policies.indexing_policy import dense_goes_to_qdrant
from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.value_objects.identifiers import JobType, new_id
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.models.tables import QuantizedVectorModel
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantDocument
from atenex_nova.shared.config.settings import EmbeddingProfile, Settings
from atenex_nova.workers.jobs.mem_builder_job import EmbedDocumentJobHandler


@dataclass
class _RecordingQdrant:
    """In-memory Qdrant stand-in that records upserts for assertions."""

    init_calls: list[tuple[str, int, bool]] = field(default_factory=list)
    upserted: list[QdrantDocument] = field(default_factory=list)
    _available: bool = True

    async def init_collection(
        self, collection_name: str, vector_size: int, *, dense_enabled: bool = True
    ) -> None:
        self.init_calls.append((collection_name, vector_size, dense_enabled))

    async def upsert(self, collection_name: str, documents: list[QdrantDocument]) -> None:
        self.upserted.extend(documents)

    @property
    def is_available(self) -> bool:
        return self._available


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> Settings:
    settings = Settings(**overrides)

    def _getter() -> Settings:
        return settings

    for target in (
        "atenex_nova.shared.config.settings.get_settings",
        "atenex_nova.workers.jobs.mem_builder_job.get_settings",
        "atenex_nova.application.orchestrators.ingestion_orchestrator.get_settings",
        "atenex_nova.infrastructure.indexes.candidate_index_factory.get_settings",
    ):
        monkeypatch.setattr(target, _getter)
    return settings


def _patch_standard_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    return _patch_settings(
        monkeypatch,
        embedding_profile=EmbeddingProfile.STANDARD,
        candidate_backend="purepy",
    )


@pytest.fixture(autouse=True)
def _mock_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fast_init(
        self: EmbeddingGemmaAdapter,
        model_name: str = "embeddinggemma",
        dim: int = 384,
        required: bool | None = None,
    ) -> None:
        self._model_name = model_name or "embeddinggemma"
        self._dim = dim
        self._required = False if required is None else required
        self.model = object()
        self._fallback_only = False

    async def _deterministic_embed(self: EmbeddingGemmaAdapter, texts: list[str]) -> list[list[float]]:
        return [[float(len(text) % 7) / 7.0] * self._dim for text in texts]

    monkeypatch.setattr(EmbeddingGemmaAdapter, "__init__", _fast_init)
    monkeypatch.setattr(EmbeddingGemmaAdapter, "embed", _deterministic_embed)


@pytest.fixture()
async def session_factory(tmp_path: Path):
    db_path = tmp_path / "single-copy.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_embeddable_document(factory) -> tuple[str, str, str]:
    async with factory() as session:
        collection_repo = SqlCollectionRepository(session)
        document_repo = SqlDocumentRepository(session)
        chunk_repo = SqlChunkRepository(session)

        collection = Collection(id=new_id(), name="Single Copy", description="SA-5 test")
        await collection_repo.create(collection)

        document = Document(
            id=new_id(),
            collection_id=collection.id,
            title="Test Doc",
            source_path="/tmp/test.md",
            mime_type="text/markdown",
            checksum="checksum",
        )
        document.mark_parsed()
        document.mark_normalized()
        document.mark_segmented()
        await document_repo.create(document)

        chunk = Chunk(
            id=new_id(),
            document_id=document.id,
            text="Canonical dense lives in quantized_vectors, not Qdrant.",
            summary="Single copy test chunk.",
            node_ids=["n1"],
            token_count=8,
        )
        await chunk_repo.create_many([chunk])
        await session.commit()
        return collection.id, document.id, chunk.id


def test_dense_goes_to_qdrant_only_for_max() -> None:
    assert dense_goes_to_qdrant(Settings(embedding_profile=EmbeddingProfile.MAX)) is True
    assert dense_goes_to_qdrant(Settings(embedding_profile=EmbeddingProfile.STANDARD)) is False
    assert dense_goes_to_qdrant(Settings(embedding_profile=EmbeddingProfile.LITE)) is False


@pytest.mark.asyncio
async def test_index_nodes_writes_quantized_codes(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_standard_settings(monkeypatch)
    collection_id = new_id()
    node_ids = [new_id(), new_id()]
    vectors = [[0.1] * 384, [0.2] * 384]

    async with session_factory() as session:
        orchestrator = IngestionOrchestrator(session)
        await orchestrator.index_nodes(
            collection_id=collection_id,
            memory_layer="chunk",
            node_ids=node_ids,
            vectors=vectors,
            embedding_model="embeddinggemma",
            dimension=384,
        )
        await session.commit()

        count_stmt = select(func.count()).select_from(QuantizedVectorModel).where(
            QuantizedVectorModel.collection_id == collection_id
        )
        count = (await session.execute(count_stmt)).scalar_one()
        assert count == 2


@pytest.mark.asyncio
async def test_standard_embed_job_sparse_only_qdrant(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_standard_settings(monkeypatch)
    recording_qdrant = _RecordingQdrant()

    monkeypatch.setattr(
        "atenex_nova.workers.jobs.mem_builder_job.QdrantAdapter",
        lambda **kwargs: recording_qdrant,
    )

    collection_id, document_id, chunk_id = await _seed_embeddable_document(session_factory)

    await EmbedDocumentJobHandler(session_factory).execute(
        Job(id=new_id(), job_type=JobType.EMBED_DOCUMENT, target_id=document_id)
    )

    assert len(recording_qdrant.init_calls) == 1
    init_name, init_dim, dense_enabled = recording_qdrant.init_calls[0]
    assert init_name == f"collection_{collection_id}"
    assert init_dim == 384
    assert dense_enabled is False

    assert len(recording_qdrant.upserted) == 1
    doc = recording_qdrant.upserted[0]
    assert doc.id == chunk_id
    assert doc.vector is None
    assert doc.sparse_indices is not None
    assert doc.sparse_values is not None

    async with session_factory() as session:
        count_stmt = select(func.count()).select_from(QuantizedVectorModel).where(
            QuantizedVectorModel.collection_id == collection_id
        )
        code_count = (await session.execute(count_stmt)).scalar_one()
        assert code_count == 1

        chunk_repo = SqlChunkRepository(session)
        chunks = await chunk_repo.get_by_document(document_id)
        chunk = next(c for c in chunks if c.id == chunk_id)
        assert chunk.embedding_ref == chunk_id


@pytest.mark.asyncio
async def test_max_profile_stores_dense_in_qdrant(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(
        monkeypatch,
        embedding_profile=EmbeddingProfile.MAX,
        candidate_backend="purepy",
    )
    recording_qdrant = _RecordingQdrant()
    monkeypatch.setattr(
        "atenex_nova.workers.jobs.mem_builder_job.QdrantAdapter",
        lambda **kwargs: recording_qdrant,
    )

    collection_id, document_id, _chunk_id = await _seed_embeddable_document(session_factory)

    await EmbedDocumentJobHandler(session_factory).execute(
        Job(id=new_id(), job_type=JobType.EMBED_DOCUMENT, target_id=document_id)
    )

    assert recording_qdrant.init_calls[0][2] is True
    assert len(recording_qdrant.upserted) == 1
    assert recording_qdrant.upserted[0].vector is not None
    assert len(recording_qdrant.upserted[0].vector) == 768

    async with session_factory() as session:
        count_stmt = select(func.count()).select_from(QuantizedVectorModel).where(
            QuantizedVectorModel.collection_id == collection_id
        )
        assert (await session.execute(count_stmt)).scalar_one() == 1

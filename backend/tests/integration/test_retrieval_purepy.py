"""Integration test: STANDARD retrieval uses candidate index IP (SA-6 / H-3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.application.orchestrators.retrieval_orchestrator import RetrievalOrchestrator
from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.models.tables import QuantizationProfileModel
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.infrastructure.indexes.quantized_code_store import QuantizedCodeStore
from atenex_nova.infrastructure.indexes.turboquant_candidate_index import string_to_uint64
from atenex_nova.infrastructure.vector_quantization.turboquant_adapter import TurboQuantAdapter
from atenex_nova.shared.config.settings import EmbeddingProfile, Settings


@dataclass
class _TrackingQdrant:
    """Records Qdrant search calls to assert dense vs sparse usage."""

    search_calls: list[dict[str, object]] = field(default_factory=list)
    _available: bool = True

    async def search(
        self,
        collection_name: str,
        query_vector: list[float] | None = None,
        limit: int = 40,
        query_sparse_indices: list[int] | None = None,
        query_sparse_values: list[float] | None = None,
    ) -> list[dict[str, object]]:
        self.search_calls.append(
            {
                "collection": collection_name,
                "query_vector": query_vector,
                "sparse": query_sparse_indices is not None,
            }
        )
        return []

    @property
    def is_available(self) -> bool:
        return self._available


def _patch_standard_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(embedding_profile=EmbeddingProfile.STANDARD, candidate_backend="purepy")

    def _getter() -> Settings:
        return settings

    for target in (
        "atenex_nova.shared.config.settings.get_settings",
        "atenex_nova.application.orchestrators.retrieval_orchestrator.get_settings",
        "atenex_nova.infrastructure.indexes.candidate_index_factory.get_settings",
    ):
        monkeypatch.setattr(target, _getter)
    return settings


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
    db_path = tmp_path / "retrieval-purepy.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_collection_with_quantized_chunk(
    factory,
    *,
    chunk_text: str = "quantized dense canonical store turbo ip estimation",
) -> tuple[str, str, str]:
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
    vector = [0.5] * 384

    async with factory() as session:
        collection_repo = SqlCollectionRepository(session)
        document_repo = SqlDocumentRepository(session)
        chunk_repo = SqlChunkRepository(session)
        store = QuantizedCodeStore(session)
        adapter = TurboQuantAdapter()

        collection = Collection(id=new_id(), name="Retrieval PurePy", description="SA-6")
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
        document.mark_embedded()
        document.mark_indexed()
        document.mark_ready()
        await document_repo.create(document)

        chunk = Chunk(
            id=new_id(),
            document_id=document.id,
            text=chunk_text,
            summary=chunk_text[:280],
            node_ids=["n1"],
            token_count=8,
            embedding_ref=chunk_text,
        )
        await chunk_repo.create_many([chunk])

        await store.save_profile(profile)
        code = adapter.quantize(vector, profile)
        await store.save_vector(
            node_id=chunk.id,
            uint64_id=string_to_uint64(chunk.id),
            collection_id=collection.id,
            memory_layer="chunk",
            profile_id=profile.id,
            idx_blob=code["idx_blob"],
            qjl_blob=code["qjl_blob"],
            residual_norm=code["residual_norm"],
            vector_norm=code["vector_norm"],
        )
        await session.commit()
        return collection.id, document.id, chunk.id


@pytest.mark.asyncio
async def test_standard_query_uses_candidate_index_not_qdrant_dense(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_standard_settings(monkeypatch)
    tracking_qdrant = _TrackingQdrant()

    collection_id, _document_id, chunk_id = await _seed_collection_with_quantized_chunk(session_factory)

    async with session_factory() as session:
        orchestrator = RetrievalOrchestrator(session, qdrant_adapter=tracking_qdrant)
        result = await orchestrator.search(collection_id, "quantized dense turbo ip")

    dense_qdrant_calls = [
        call for call in tracking_qdrant.search_calls if call.get("query_vector") is not None
    ]
    assert dense_qdrant_calls == []

    chunk_hits = [hit for hit in result.hits if hit.source_type == "chunk"]
    assert chunk_hits, "expected at least one chunk hit from candidate index"
    assert any(hit.source_id == chunk_id for hit in chunk_hits)
    assert all(
        (hit.metadata or {}).get("retrieval_stage") == "dense_turbo_ip"
        for hit in chunk_hits
        if hit.source_id == chunk_id
    )

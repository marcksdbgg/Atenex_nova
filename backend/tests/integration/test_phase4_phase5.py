"""Integration coverage for phase 4 enrichment and phase 5 search."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.application.services.query_service import QueryService
from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.value_objects.identifiers import JobType, new_id
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import SqlPropositionRepository
from atenex_nova.infrastructure.db.repositories.sql_relation_repo import SqlRelationRepository
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository
from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.workers.jobs.memory_enrichment_job import (
    BuildGraphJobHandler,
    EmbedPropositionsJobHandler,
    EmbedSummariesJobHandler,
    ExtractPropositionsJobHandler,
    GenerateSummariesJobHandler,
)


@pytest.fixture(autouse=True)
def _mock_llm_and_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fast_init(self, model_name: str = "embeddinggemma", dim: int = 384, required: bool | None = None) -> None:
        self._model_name = model_name or "embeddinggemma"
        self._dim = dim
        self._required = False if required is None else required
        self.model = object()
        self._fallback_only = False

    monkeypatch.setattr(EmbeddingGemmaAdapter, "__init__", _fast_init)


@pytest.fixture()
async def session_factory(tmp_path: Path):
    db_path = tmp_path / "phase45.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_corpus(factory) -> tuple[str, str]:
    async with factory() as session:
        collection_repo = SqlCollectionRepository(session)
        document_repo = SqlDocumentRepository(session)
        chunk_repo = SqlChunkRepository(session)

        collection = Collection(id=new_id(), name="Phase 4/5 Collection", description="Test corpus")
        await collection_repo.create(collection)

        document = Document(
            id=new_id(),
            collection_id=collection.id,
            title="EmbeddingGemma Notes",
            source_path="/tmp/embeddinggemma.md",
            mime_type="text/markdown",
            checksum="abc123",
        )
        document.mark_parsed()
        document.mark_normalized()
        document.mark_segmented()
        document.mark_embedded()
        document.mark_indexed()
        document.mark_ready()
        await document_repo.create(document)

        chunks = [
            Chunk(
                id=new_id(),
                document_id=document.id,
                text="EmbeddingGemma supports 384d embeddings for the standard profile.",
                summary="EmbeddingGemma standard profile.",
                node_ids=["n1"],
                token_count=9,
            ),
            Chunk(
                id=new_id(),
                document_id=document.id,
                text="The collection summary should mention local retrieval and proposition graphs.",
                summary="Local retrieval and graph support.",
                node_ids=["n2"],
                token_count=10,
            ),
        ]
        await chunk_repo.create_many(chunks)
        await session.commit()
        return collection.id, document.id


@pytest.mark.asyncio
async def test_phase4_enrichment_and_phase5_search(session_factory) -> None:
    collection_id, document_id = await _seed_corpus(session_factory)

    await ExtractPropositionsJobHandler(session_factory).execute(
        Job(id=new_id(), job_type=JobType.EXTRACT_PROPOSITIONS, target_id=document_id)
    )
    await GenerateSummariesJobHandler(session_factory).execute(
        Job(id=new_id(), job_type=JobType.GENERATE_SUMMARIES, target_id=document_id)
    )
    await EmbedPropositionsJobHandler(session_factory).execute(
        Job(id=new_id(), job_type=JobType.EMBED_PROPOSITIONS, target_id=document_id)
    )
    await EmbedSummariesJobHandler(session_factory).execute(
        Job(id=new_id(), job_type=JobType.EMBED_SUMMARIES, target_id=document_id)
    )
    await BuildGraphJobHandler(session_factory).execute(
        Job(id=new_id(), job_type=JobType.BUILD_GRAPH, target_id=document_id)
    )

    async with session_factory() as session:
        proposition_repo = SqlPropositionRepository(session)
        summary_repo = SqlSummaryRepository(session)
        relation_repo = SqlRelationRepository(session)

        propositions = await proposition_repo.list_by_document(document_id)
        summaries = await summary_repo.list_by_document(document_id)
        relations = await relation_repo.list_by_source_ids([prop.id for prop in propositions[:1]])

        assert propositions, "Phase 4 should extract propositions"
        assert summaries, "Phase 4 should generate summaries"
        assert relations, "Phase 4 should build graph edges"

        query_service = QueryService(session)
        result = await query_service.search_only(
            collection_id=collection_id,
            query="What does EmbeddingGemma support?",
            mode="auto",
        )

        assert result.hits, "Phase 5 should return ranked hits"
        assert result.query.collection_id == collection_id
        assert result.evidence_pack.items, "Phase 5 should build an evidence pack"
        assert result.query.route_mode in {"factual_local", "multi_hop", "exact"}
        assert any("EmbeddingGemma" in hit.snippet for hit in result.hits)

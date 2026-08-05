"""Publication safety tests for retrieval over mutable external indexes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

from atenex_nova.application.orchestrators.retrieval_orchestrator import (
    RetrievalOrchestrator,
    SearchHit,
)
from atenex_nova.application.policies.collection_publication_policy import (
    CollectionPublicationPolicy,
)
from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.entities.proposition import Proposition
from atenex_nova.domain.entities.relation_edge import RelationEdge
from atenex_nova.domain.entities.summary_node import SummaryNode
from atenex_nova.domain.value_objects.identifiers import (
    DocumentStatus,
    JobType,
    new_id,
)
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.models.tables import PipelineAuditModel, QueryModel
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import (
    SqlCollectionRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_document_repo import (
    SqlDocumentRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import (
    SqlPropositionRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_relation_repo import (
    SqlRelationRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import (
    SqlSummaryRepository,
)
from atenex_nova.shared.config.settings import EmbeddingProfile, Settings
from atenex_nova.shared.exceptions.base import CollectionPublicationError


@dataclass
class _StaticEmbedder:
    calls: list[str] = field(default_factory=list)

    async def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.1] * 256


@dataclass
class _NoopVisualRetriever:
    async def search(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []


@dataclass
class _NoopReranker:
    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [0.0] * len(pairs)


@dataclass
class _StaleQdrant:
    collection_id: str
    document_id: str
    current_chunk_id: str
    stale_chunk_id: str
    embedding_contract: str
    search_calls: int = 0

    @property
    def is_available(self) -> bool:
        return True

    async def search(
        self,
        collection_name: str,
        query_vector: list[float] | None = None,
        limit: int = 40,
        **_kwargs: object,
    ) -> list[dict[str, object]]:
        self.search_calls += 1
        if collection_name != f"collection_{self.collection_id}":
            return []
        return [
            {
                "id": self.stale_chunk_id,
                "score": 0.99,
                "payload": {
                    "collection_id": self.collection_id,
                    "document_id": self.document_id,
                    "chunk_id": self.stale_chunk_id,
                    "title": "Stale remote title",
                    "text": "A stale Qdrant point must never become cited evidence.",
                    "embedding_contract": "emb-v1-old-contract",
                },
            },
            {
                "id": self.current_chunk_id,
                "score": 0.8,
                "payload": {
                    "collection_id": self.collection_id,
                    "document_id": self.document_id,
                    "chunk_id": self.current_chunk_id,
                    "title": "Tampered remote title",
                    "text": "Tampered remote text must be replaced from SQL.",
                    "embedding_contract": self.embedding_contract,
                },
            },
        ][:limit]


@dataclass
class _UnavailableQdrant:
    search_calls: int = 0

    @property
    def is_available(self) -> bool:
        return False

    async def search(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
        self.search_calls += 1
        return []


@pytest.fixture()
async def session_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'publication.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def retrieval_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(
        embedding_profile=EmbeddingProfile.LITE,
        qdrant_dense_enabled=True,
        strict_mode=False,
        enable_reranker=False,
        candidate_backend="purepy",
    )
    monkeypatch.setattr(
        "atenex_nova.application.orchestrators.retrieval_orchestrator.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.candidate_index_factory.get_settings",
        lambda: settings,
    )
    return settings


async def _seed_ready_document(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[str, str, str, str]:
    collection = Collection(id=new_id(), name="Published corpus")
    document = Document(
        id=new_id(),
        collection_id=collection.id,
        title="Canonical SQL title",
        source_path="/tmp/source.txt",
        mime_type="text/plain",
        checksum="a" * 64,
        status=DocumentStatus.READY,
    )
    canonical_text = (
        "Canonical SQL evidence explains why stale external vector payloads "
        "cannot be trusted as documentary authority."
    )
    chunk = Chunk(
        id=new_id(),
        document_id=document.id,
        text=canonical_text,
        summary=canonical_text,
        token_count=16,
        embedding_ref="indexed",
        metadata={"page_numbers": [7], "heading_path": ["Safety"]},
    )
    async with factory() as session:
        await SqlCollectionRepository(session).create(collection)
        await SqlDocumentRepository(session).create(document)
        await SqlChunkRepository(session).create_many([chunk])
        await session.commit()
    return collection.id, document.id, chunk.id, canonical_text


@pytest.mark.asyncio
async def test_stale_qdrant_hit_is_dropped_and_current_text_is_rehydrated(
    session_factory: async_sessionmaker[AsyncSession],
    retrieval_settings: Settings,
) -> None:
    collection_id, document_id, chunk_id, canonical_text = await _seed_ready_document(
        session_factory
    )
    qdrant = _StaleQdrant(
        collection_id=collection_id,
        document_id=document_id,
        current_chunk_id=chunk_id,
        stale_chunk_id=new_id(),
        embedding_contract=retrieval_settings.embedding_contract_fingerprint,
    )

    async with session_factory() as session:
        orchestrator = RetrievalOrchestrator(
            session,
            qdrant_adapter=qdrant,
            embedder=_StaticEmbedder(),
            visual_adapter=_NoopVisualRetriever(),
            reranker=_NoopReranker(),
        )
        result = await orchestrator.search(
            collection_id,
            "external vector payload authority",
            mode="factual_local",
        )

        assert qdrant.search_calls >= 2  # dense and sparse
        assert [hit.source_id for hit in result.hits] == [chunk_id]
        assert result.hits[0].title == "Canonical SQL title"
        assert canonical_text in str(result.hits[0].metadata["source_text"])
        assert "Tampered remote text" not in result.hits[0].snippet
        assert result.hits[0].page_number == 7

        audit_result = await session.execute(
            select(PipelineAuditModel).where(
                PipelineAuditModel.run_id == result.query.id,
                PipelineAuditModel.stage == "search",
            )
        )
        audit = audit_result.scalar_one()
        assert '"incompatible_embedding_contract": 1' in audit.metrics_json


@pytest.mark.asyncio
async def test_partial_rebuild_blocks_before_query_or_embedding(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    collection_id, _document_id, _chunk_id, _text = await _seed_ready_document(
        session_factory
    )
    embedder = _StaticEmbedder()
    qdrant = _UnavailableQdrant()

    async with session_factory() as session:
        document_repo = SqlDocumentRepository(session)
        transitional = Document(
            id=new_id(),
            collection_id=collection_id,
            title="Rebuilding document",
            source_path="/tmp/rebuilding.txt",
            mime_type="text/plain",
            checksum="b" * 64,
            status=DocumentStatus.REGISTERED,
        )
        await document_repo.create(transitional)
        await session.commit()

        orchestrator = RetrievalOrchestrator(
            session,
            qdrant_adapter=qdrant,
            embedder=embedder,
            visual_adapter=_NoopVisualRetriever(),
            reranker=_NoopReranker(),
        )
        with pytest.raises(CollectionPublicationError) as error:
            await orchestrator.search(collection_id, "query during rebuild")

        assert error.value.code == "COLLECTION_INDEXING"
        assert error.value.document_statuses == {"ready": 1, "registered": 1}
        assert embedder.calls == []
        assert qdrant.search_calls == 0
        persisted_queries = await session.execute(select(QueryModel))
        assert list(persisted_queries.scalars()) == []


@pytest.mark.asyncio
async def test_active_rebuild_job_blocks_even_if_documents_still_look_ready(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    collection_id, _document_id, _chunk_id, _text = await _seed_ready_document(
        session_factory
    )
    async with session_factory() as session:
        await SqlJobRepository(session).create(
            Job(
                id=new_id(),
                job_type=JobType.REBUILD_COLLECTION,
                target_id=collection_id,
            )
        )
        await session.commit()
        orchestrator = RetrievalOrchestrator(
            session,
            qdrant_adapter=_UnavailableQdrant(),
            embedder=_StaticEmbedder(),
            visual_adapter=_NoopVisualRetriever(),
            reranker=_NoopReranker(),
        )

        with pytest.raises(CollectionPublicationError) as error:
            await orchestrator.search(collection_id, "query before status reset")
        assert error.value.code == "COLLECTION_REBUILD_ACTIVE"


@pytest.mark.asyncio
async def test_failed_documents_are_excluded_and_reported_without_blocking(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    collection_id, _document_id, _chunk_id, _text = await _seed_ready_document(
        session_factory
    )
    async with session_factory() as session:
        failed = Document(
            id=new_id(),
            collection_id=collection_id,
            title="Failed source",
            source_path="/tmp/failed.txt",
            mime_type="text/plain",
            checksum="f" * 64,
            status=DocumentStatus.FAILED,
            error_message="parse failure",
        )
        await SqlDocumentRepository(session).create(failed)
        await session.commit()

        orchestrator = RetrievalOrchestrator(
            session,
            qdrant_adapter=_UnavailableQdrant(),
            embedder=_StaticEmbedder(),
            visual_adapter=_NoopVisualRetriever(),
            reranker=_NoopReranker(),
        )
        result = await orchestrator.search(
            collection_id,
            "canonical SQL evidence",
            mode="factual_local",
        )

        assert "Corpus gap: 1 failed document(s) were excluded." in result.route_reason
        assert result.hits
        publication = result.hits[0].metadata["collection_publication"]
        assert isinstance(publication, dict)
        assert publication["failed_documents"] == 1


@pytest.mark.asyncio
async def test_all_failed_collection_blocks_before_query_or_embedding(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    collection = Collection(id=new_id(), name="Only failed documents")
    failed = Document(
        id=new_id(),
        collection_id=collection.id,
        title="Failed source",
        source_path="/tmp/failed-only.txt",
        mime_type="text/plain",
        checksum="f" * 64,
        status=DocumentStatus.FAILED,
        error_message="parse failure",
    )
    embedder = _StaticEmbedder()
    qdrant = _UnavailableQdrant()
    async with session_factory() as session:
        await SqlCollectionRepository(session).create(collection)
        await SqlDocumentRepository(session).create(failed)
        await session.commit()
        orchestrator = RetrievalOrchestrator(
            session,
            qdrant_adapter=qdrant,
            embedder=embedder,
            visual_adapter=_NoopVisualRetriever(),
            reranker=_NoopReranker(),
        )

        with pytest.raises(CollectionPublicationError) as error:
            await orchestrator.search(collection.id, "anything")

        assert error.value.code == "COLLECTION_NO_READY_DOCUMENTS"
        assert error.value.document_statuses == {"failed": 1}
        assert embedder.calls == []
        assert qdrant.search_calls == 0
        persisted_queries = await session.execute(select(QueryModel))
        assert list(persisted_queries.scalars()) == []


@pytest.mark.asyncio
async def test_every_evidence_type_is_rehydrated_or_rejected_by_ready_sql_ownership(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    collection_id, ready_document_id, ready_chunk_id, _text = (
        await _seed_ready_document(session_factory)
    )
    failed_document = Document(
        id=new_id(),
        collection_id=collection_id,
        title="Unpublished document",
        source_path="/tmp/unpublished.txt",
        mime_type="text/plain",
        checksum="f" * 64,
        status=DocumentStatus.FAILED,
        error_message="controlled failure",
    )
    failed_chunk = Chunk(
        id=new_id(),
        document_id=failed_document.id,
        text="Unpublished chunk text.",
        token_count=4,
    )
    ready_proposition = Proposition(
        id=new_id(),
        document_id=ready_document_id,
        source_chunk_id=ready_chunk_id,
        text="Canonical ready proposition.",
    )
    failed_proposition = Proposition(
        id=new_id(),
        document_id=failed_document.id,
        source_chunk_id=failed_chunk.id,
        text="Unpublished proposition.",
    )
    ready_document_summary = SummaryNode(
        id=new_id(),
        scope_type="document",
        scope_id=ready_document_id,
        text="Canonical document summary.",
    )
    ready_section_summary = SummaryNode(
        id=new_id(),
        scope_type="section",
        scope_id=ready_chunk_id,
        text="Canonical section summary.",
    )
    ready_collection_summary = SummaryNode(
        id=new_id(),
        scope_type="collection",
        scope_id=collection_id,
        text="Canonical collection summary.",
    )
    failed_document_summary = SummaryNode(
        id=new_id(),
        scope_type="document",
        scope_id=failed_document.id,
        text="Unpublished document summary.",
    )
    ready_edge = RelationEdge(
        id=new_id(),
        source_type="proposition",
        source_id=ready_proposition.id,
        target_type="concept",
        target_id="published-concept",
        relation="supports",
    )
    failed_edge = RelationEdge(
        id=new_id(),
        source_type="proposition",
        source_id=failed_proposition.id,
        target_type="concept",
        target_id="unpublished-concept",
        relation="supports",
    )

    async with session_factory() as session:
        await SqlDocumentRepository(session).create(failed_document)
        await SqlChunkRepository(session).create_many([failed_chunk])
        await SqlPropositionRepository(session).create_many(
            [ready_proposition, failed_proposition]
        )
        await SqlSummaryRepository(session).create_many(
            [
                ready_document_summary,
                ready_section_summary,
                ready_collection_summary,
                failed_document_summary,
            ]
        )
        await SqlRelationRepository(session).create_many([ready_edge, failed_edge])
        await session.commit()

        documents = await SqlDocumentRepository(session).list_by_collection(
            collection_id,
            limit=10,
        )
        publication = CollectionPublicationPolicy().evaluate(
            collection_id=collection_id,
            documents=documents,
            rebuild_active=False,
        )
        orchestrator = RetrievalOrchestrator(
            session,
            qdrant_adapter=_UnavailableQdrant(),
            embedder=_StaticEmbedder(),
            visual_adapter=_NoopVisualRetriever(),
            reranker=_NoopReranker(),
        )

        def hit(
            source_type: str,
            source_id: str,
            document_id: str | None = None,
        ) -> SearchHit:
            return SearchHit(
                id=new_id(),
                source_type=source_type,
                source_id=source_id,
                document_id=document_id,
                title="Untrusted title",
                snippet="Untrusted text",
                score=0.8,
                rank=0,
                metadata={"retrieval_stage": "local_sparse"},
            )

        candidates = [
            hit("chunk", ready_chunk_id, ready_document_id),
            hit("chunk", failed_chunk.id, failed_document.id),
            hit("proposition", ready_proposition.id, ready_document_id),
            hit("proposition", failed_proposition.id, failed_document.id),
            hit("summary", ready_document_summary.id, ready_document_id),
            hit("summary", ready_section_summary.id, ready_document_id),
            hit("summary", ready_collection_summary.id),
            hit("summary", failed_document_summary.id, failed_document.id),
            hit("visual_page", "ready-page", ready_document_id),
            hit("visual_page", "failed-page", failed_document.id),
            hit("graph_edge", ready_edge.id, ready_document_id),
            hit("graph_edge", failed_edge.id, failed_document.id),
        ]
        validated, discarded = await orchestrator._validate_published_hits(
            collection_id=collection_id,
            hits=candidates,
            publication=publication,
            document_titles={ready_document_id: "Canonical SQL title"},
            query_text="canonical",
        )

        assert {item.source_id for item in validated} == {
            ready_chunk_id,
            ready_proposition.id,
            ready_document_summary.id,
            ready_section_summary.id,
            ready_collection_summary.id,
            "ready-page",
            ready_edge.id,
        }
        assert discarded == {
            "chunk_not_published": 1,
            "graph_edge_not_published": 1,
            "proposition_not_published": 1,
            "summary_document_not_published": 1,
            "visual_document_not_published": 1,
        }
        canonical_proposition = next(
            item for item in validated if item.source_id == ready_proposition.id
        )
        assert canonical_proposition.snippet == ready_proposition.text
        assert canonical_proposition.title == "Canonical SQL title"


@pytest.mark.asyncio
async def test_empty_collection_has_specific_publication_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    collection = Collection(id=new_id(), name="Empty")
    async with session_factory() as session:
        await SqlCollectionRepository(session).create(collection)
        await session.commit()
        orchestrator = RetrievalOrchestrator(
            session,
            qdrant_adapter=_UnavailableQdrant(),
            embedder=_StaticEmbedder(),
            visual_adapter=_NoopVisualRetriever(),
            reranker=_NoopReranker(),
        )

        with pytest.raises(CollectionPublicationError) as error:
            await orchestrator.search(collection.id, "anything")
        assert error.value.code == "COLLECTION_EMPTY"
        assert error.value.document_statuses == {}

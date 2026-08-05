"""Integration coverage for bounded multi-query execution and RRF fusion."""

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
from atenex_nova.domain.entities.proposition import Proposition
from atenex_nova.domain.value_objects.identifiers import DocumentStatus, new_id
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_pipeline_audit_repo import (
    SqlPipelineAuditRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import (
    SqlPropositionRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_query_repo import SqlQueryRepository
from atenex_nova.shared.config.settings import EmbeddingProfile, Settings


@dataclass
class _FacetEmbedder:
    queries: list[str] = field(default_factory=list)

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        normalized = text.casefold()
        has_liberty = "libertad moral" in normalized
        has_vulnerability = "vulnerabilidad social" in normalized
        if has_liberty and not has_vulnerability:
            return [1.0, 0.0]
        if has_vulnerability and not has_liberty:
            return [0.0, 1.0]
        return [0.5, 0.5]


@dataclass
class _FacetQdrant:
    collection_id: str
    liberty_document_id: str
    vulnerability_document_id: str
    embedding_contract: str
    calls: list[dict[str, object]] = field(default_factory=list)

    @property
    def is_available(self) -> bool:
        return True

    async def search(
        self,
        collection_name: str,
        query_vector: list[float] | None = None,
        limit: int = 40,
        query_sparse_indices: list[int] | None = None,
        query_sparse_values: list[float] | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "collection": collection_name,
                "query_vector": query_vector,
                "sparse": query_sparse_indices is not None,
                "limit": limit,
            }
        )
        if (
            collection_name == f"collection_{self.collection_id}_propositions"
            and query_vector is not None
        ):
            return [
                {
                    "id": "point-proposition",
                    "score": 0.91,
                    "payload": {
                        "source_type": "proposition",
                        "proposition_id": "prop-seed",
                        "document_id": self.liberty_document_id,
                        "title": "Libertad moral en Cervantes",
                        "text": "La libertad moral implica responsabilidad personal.",
                        "embedding_contract": self.embedding_contract,
                    },
                }
            ]
        if collection_name != f"collection_{self.collection_id}" or query_vector is None:
            return []
        if query_vector[1] > query_vector[0]:
            return [
                {
                    "id": "point-vulnerability",
                    "score": 0.96,
                    "payload": {
                        "source_type": "chunk",
                        "chunk_id": "chunk-vulnerability",
                        "document_id": self.vulnerability_document_id,
                        "title": "Vulnerabilidad y eutanasia",
                        "text": (
                            "La vulnerabilidad social condiciona el debate sobre "
                            "la eutanasia."
                        ),
                        "embedding_contract": self.embedding_contract,
                    },
                }
            ]
        return [
            {
                "id": "point-liberty",
                "score": 0.94,
                "payload": {
                    "source_type": "chunk",
                    "chunk_id": "chunk-liberty",
                    "document_id": self.liberty_document_id,
                    "title": "Libertad moral en Cervantes",
                    "text": "Cervantes examina la libertad moral mediante sus personajes.",
                    "embedding_contract": self.embedding_contract,
                },
            }
        ]


@dataclass
class _UnavailableQdrant:
    @property
    def is_available(self) -> bool:
        return False


@dataclass
class _TrackingCandidateIndex:
    layers: list[str] = field(default_factory=list)

    async def search(
        self,
        collection_id: str,
        memory_layers: list[str],
        query_vector: list[float],
        top_n: int = 200,
    ) -> list[dict[str, object]]:
        del collection_id, query_vector, top_n
        self.layers.extend(memory_layers)
        return []


@dataclass
class _NoopVisualRetriever:
    async def search(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []


@dataclass
class _HeuristicOnlyReranker:
    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [0.0] * len(pairs)


@pytest.fixture()
async def session_factory(tmp_path: Path):
    db_path = tmp_path / "multi-query.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_documents(factory) -> tuple[str, str, str]:
    collection = Collection(id=new_id(), name="Distributed facets")
    liberty = Document(
        id=new_id(),
        collection_id=collection.id,
        title="Libertad moral en Cervantes",
        source_path="/tmp/liberty.txt",
        mime_type="text/plain",
        checksum="a" * 64,
        status=DocumentStatus.READY,
    )
    vulnerability = Document(
        id=new_id(),
        collection_id=collection.id,
        title="Vulnerabilidad y eutanasia",
        source_path="/tmp/vulnerability.txt",
        mime_type="text/plain",
        checksum="b" * 64,
        status=DocumentStatus.READY,
    )
    async with factory() as session:
        await SqlCollectionRepository(session).create(collection)
        repository = SqlDocumentRepository(session)
        await repository.create(liberty)
        await repository.create(vulnerability)
        await SqlChunkRepository(session).create_many(
            [
                Chunk(
                    id="chunk-liberty",
                    document_id=liberty.id,
                    text="Cervantes examina la libertad moral mediante sus personajes.",
                    token_count=9,
                ),
                Chunk(
                    id="chunk-vulnerability",
                    document_id=vulnerability.id,
                    text=(
                        "La vulnerabilidad social condiciona el debate sobre "
                        "la eutanasia."
                    ),
                    token_count=10,
                ),
            ]
        )
        await SqlPropositionRepository(session).create_many(
            [
                Proposition(
                    id="prop-seed",
                    document_id=liberty.id,
                    source_chunk_id="chunk-liberty",
                    text="La libertad moral implica responsabilidad personal.",
                )
            ]
        )
        await session.commit()
    return collection.id, liberty.id, vulnerability.id


@pytest.mark.asyncio
async def test_multi_query_recovers_distributed_facets_without_contaminating_simple_query(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        embedding_profile=EmbeddingProfile.LITE,
        qdrant_dense_enabled=True,
        strict_mode=False,
        enable_reranker=False,
    )
    monkeypatch.setattr(
        "atenex_nova.application.orchestrators.retrieval_orchestrator.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.candidate_index_factory.get_settings",
        lambda: settings,
    )
    collection_id, liberty_id, vulnerability_id = await _seed_documents(session_factory)
    qdrant = _FacetQdrant(
        collection_id,
        liberty_id,
        vulnerability_id,
        settings.embedding_contract_fingerprint,
    )
    embedder = _FacetEmbedder()

    async with session_factory() as session:
        orchestrator = RetrievalOrchestrator(
            session,
            qdrant_adapter=qdrant,
            embedder=embedder,
            visual_adapter=_NoopVisualRetriever(),
            reranker=_HeuristicOnlyReranker(),
        )
        multi_query = (
            "Analiza la libertad moral en Cervantes; "
            "explica la vulnerabilidad social ante la eutanasia"
        )
        result = await orchestrator.search(collection_id, multi_query, mode="multi_hop")

        assert result.query.text == multi_query
        assert result.query.route_mode == "multi_hop"
        assert {hit.document_id for hit in result.hits} >= {liberty_id, vulnerability_id}
        vulnerability_hit = next(
            hit for hit in result.hits if hit.document_id == vulnerability_id
        )
        assert (vulnerability_hit.metadata or {}).get("retrieval_query_expanded") is True
        variant_indices = (vulnerability_hit.metadata or {}).get(
            "retrieval_query_variant_indices"
        )
        assert isinstance(variant_indices, list)
        assert any(index > 0 for index in variant_indices)
        assert "retrieval_query_rrf_score" in (vulnerability_hit.metadata or {})
        contributions = (vulnerability_hit.metadata or {}).get(
            "retrieval_query_contributions"
        )
        assert isinstance(contributions, list)
        assert all("latency_ms" in contribution for contribution in contributions)

        base_calls = [
            call
            for call in qdrant.calls
            if call["collection"] == f"collection_{collection_id}"
        ]
        assert len([call for call in base_calls if call["query_vector"] is not None]) == 3
        assert len([call for call in base_calls if call["sparse"]]) == 3

        stored_queries = await SqlQueryRepository(session).list_by_collection(
            collection_id,
            limit=20,
        )
        assert len(stored_queries) == 1
        audit_events = await SqlPipelineAuditRepository(session).list_by_run(result.query.id)
        search_audit = next(event for event in audit_events if event["stage"] == "search")
        assert search_audit["metrics"]["multi_query_executed_count"] == 3
        assert len(search_audit["metrics"]["multi_query_embedding_variants"]) == 3
        chunk_audit = next(
            event for event in audit_events if event["stage"] == "score_chunks"
        )
        assert len(chunk_audit["metrics"]["variant_runs"]) == 3
        assert len(
            [event for event in audit_events if event["stage"] == "expand_graph"]
        ) == 1

        qdrant.calls.clear()
        embedder.queries.clear()
        simple = await orchestrator.search(
            collection_id,
            "Explica la libertad moral en Cervantes",
        )

        assert simple.query.route_mode == "factual_local"
        assert embedder.queries == ["explica la libertad moral en cervantes"]
        simple_base_calls = [
            call
            for call in qdrant.calls
            if call["collection"] == f"collection_{collection_id}"
        ]
        assert len([call for call in simple_base_calls if call["query_vector"] is not None]) == 1
        assert len([call for call in simple_base_calls if call["sparse"]]) == 1
        assert all(
            (hit.metadata or {}).get("retrieval_query_expanded") is False
            for hit in simple.hits
            if hit.source_type == "chunk"
        )
        stored_queries = await SqlQueryRepository(session).list_by_collection(
            collection_id,
            limit=20,
        )
        assert len(stored_queries) == 2


@pytest.mark.asyncio
async def test_qdrant_unavailable_runs_one_local_scan_for_expanded_route(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        embedding_profile=EmbeddingProfile.LITE,
        qdrant_dense_enabled=True,
        strict_mode=False,
        enable_reranker=False,
    )
    monkeypatch.setattr(
        "atenex_nova.application.orchestrators.retrieval_orchestrator.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.candidate_index_factory.get_settings",
        lambda: settings,
    )
    collection_id, liberty_id, vulnerability_id = await _seed_documents(session_factory)
    async with session_factory() as seed_session:
        await SqlChunkRepository(seed_session).create_many(
            [
                Chunk(
                    id=new_id(),
                    document_id=liberty_id,
                    text="Cervantes presenta la libertad moral como responsabilidad.",
                    token_count=8,
                ),
                Chunk(
                    id=new_id(),
                    document_id=vulnerability_id,
                    text="La vulnerabilidad social atraviesa el debate de la eutanasia.",
                    token_count=9,
                ),
            ]
        )

    original_list = SqlChunkRepository.list_by_collection
    chunk_list_calls = 0

    async def _tracking_list(
        repository: SqlChunkRepository,
        tracked_collection_id: str,
    ) -> list[Chunk]:
        nonlocal chunk_list_calls
        chunk_list_calls += 1
        return await original_list(repository, tracked_collection_id)

    monkeypatch.setattr(SqlChunkRepository, "list_by_collection", _tracking_list)
    embedder = _FacetEmbedder()
    candidate_index = _TrackingCandidateIndex()
    multi_query = (
        "Analiza la libertad moral en Cervantes; "
        "explica la vulnerabilidad social ante la eutanasia"
    )

    async with session_factory() as session:
        orchestrator = RetrievalOrchestrator(
            session,
            qdrant_adapter=_UnavailableQdrant(),
            embedder=embedder,
            visual_adapter=_NoopVisualRetriever(),
            reranker=_HeuristicOnlyReranker(),
        )
        orchestrator._candidate_index = candidate_index
        result = await orchestrator.search(collection_id, multi_query, mode="multi_hop")

        assert result.query.route_mode == "multi_hop"
        assert embedder.queries == [multi_query.casefold()]
        assert chunk_list_calls == 1
        assert candidate_index.layers.count("chunk") == 1
        assert candidate_index.layers.count("proposition") == 1
        assert candidate_index.layers.count("summary") == 1
        assert result.hits
        plan_metadata = (result.hits[0].metadata or {}).get("retrieval_query_plan")
        assert isinstance(plan_metadata, dict)
        assert plan_metadata["planned_count"] == 3
        assert plan_metadata["executed_count"] == 1
        assert plan_metadata["fallback_reason"] == "qdrant_unavailable_single_local_query"

        audit_events = await SqlPipelineAuditRepository(session).list_by_run(result.query.id)
        search_audit = next(event for event in audit_events if event["stage"] == "search")
        assert search_audit["metrics"]["multi_query_planned_count"] == 3
        assert search_audit["metrics"]["multi_query_executed_count"] == 1
        assert (
            search_audit["metrics"]["multi_query_fallback_reason"]
            == "qdrant_unavailable_single_local_query"
        )

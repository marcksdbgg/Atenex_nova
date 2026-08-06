"""Focused regression tests for bounded ingestion persistence and enrichment."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.application.orchestrators.ingestion_orchestrator import (
    IngestionOrchestrator,
)
from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.entities.proposition import Proposition
from atenex_nova.domain.entities.summary_node import SummaryNode
from atenex_nova.domain.value_objects.identifiers import JobType, RelationType, new_id
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.models.tables import QuantizedVectorModel
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import (
    SqlCollectionRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_document_repo import (
    SqlDocumentRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import (
    SqlPropositionRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_relation_repo import (
    SqlRelationRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import (
    SqlSummaryRepository,
)
from atenex_nova.infrastructure.indexes.quantized_code_store import (
    QuantizedCodeStore,
    QuantizedVectorWrite,
)
from atenex_nova.shared.config.settings import Settings
from atenex_nova.shared.exceptions.base import ServiceUnavailableError
from atenex_nova.workers.jobs.memory_enrichment_job import (
    GRAPH_STOPWORDS,
    BuildGraphJobHandler,
    EmbedPropositionsJobHandler,
    EmbedSummariesJobHandler,
    GenerateSummariesJobHandler,
    _build_cross_reference_edges,
    _order_propositions_for_graph,
)


@pytest.fixture()
async def isolated_database(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bulk.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory, engine
    finally:
        await engine.dispose()


def _vector_write(node_id: str, value: int) -> QuantizedVectorWrite:
    return QuantizedVectorWrite(
        node_id=node_id,
        uint64_id=value,
        collection_id="collection",
        memory_layer="proposition",
        profile_id="profile",
        idx_blob=bytes([value]),
        qjl_blob=bytes([value + 1]),
        residual_norm=float(value),
        vector_norm=float(value + 1),
    )


@pytest.mark.asyncio
async def test_quantized_bulk_write_uses_one_lookup_and_is_idempotent(
    isolated_database,
) -> None:
    factory, engine = isolated_database
    lookup_statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _record_lookup(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().startswith("SELECT") and "FROM quantized_vectors" in statement:
            lookup_statements.append(statement)

    node_ids = [new_id(), new_id(), new_id()]
    async with factory() as session:
        store = QuantizedCodeStore(session)
        await store.save_vectors(
            [_vector_write(node_id, index + 1) for index, node_id in enumerate(node_ids)]
        )
        await session.commit()
        original_ids = {
            model.node_id: model.id
            for model in (
                await session.execute(select(QuantizedVectorModel))
            ).scalars()
        }

        lookup_statements.clear()
        await store.save_vectors(
            [_vector_write(node_id, index + 4) for index, node_id in enumerate(node_ids)]
        )
        await session.commit()

        assert len(lookup_statements) == 1
        rows = list((await session.execute(select(QuantizedVectorModel))).scalars())
        assert len(rows) == len(node_ids)
        assert {row.node_id: row.id for row in rows} == original_ids
        assert {row.uint64_id for row in rows} == {4, 5, 6}


@pytest.mark.asyncio
async def test_quantized_bulk_write_rejects_duplicate_ids_before_writing(
    isolated_database,
) -> None:
    factory, _engine = isolated_database
    node_id = new_id()
    async with factory() as session:
        with pytest.raises(ValueError, match="duplicate node_ids"):
            await QuantizedCodeStore(session).save_vectors(
                [_vector_write(node_id, 1), _vector_write(node_id, 2)]
            )
        count = (
            await session.execute(select(func.count()).select_from(QuantizedVectorModel))
        ).scalar_one()
        assert count == 0


@pytest.mark.asyncio
async def test_ingestion_orchestrator_rejects_vector_cardinality_mismatch() -> None:
    orchestrator = object.__new__(IngestionOrchestrator)
    with pytest.raises(ValueError, match="same length"):
        await orchestrator.index_nodes(
            collection_id="collection",
            memory_layer="chunk",
            node_ids=[new_id()],
            vectors=[],
            embedding_model="embeddinggemma",
            dimension=384,
        )


@pytest.mark.asyncio
async def test_summary_bulk_upsert_preserves_ids_embeddings_and_input_order(
    isolated_database,
) -> None:
    factory, engine = isolated_database
    lookup_statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _record_lookup(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().startswith("SELECT") and "FROM summary_nodes" in statement:
            lookup_statements.append(statement)

    summaries = [
        SummaryNode(
            id=new_id(),
            scope_type="section",
            scope_id=new_id(),
            text=f"Summary {index}",
            provenance={"index": index},
            embedding_ref="quantized_vectors",
        )
        for index in range(3)
    ]
    async with factory() as session:
        repository = SqlSummaryRepository(session)
        created = await repository.upsert_scopes(summaries)
        await session.commit()
        assert [result.summary.id for result in created] == [item.id for item in summaries]

        lookup_statements.clear()
        unchanged = await repository.upsert_scopes(
            [
                SummaryNode(
                    id=item.id,
                    scope_type=item.scope_type,
                    scope_id=item.scope_id,
                    text=item.text,
                    provenance=item.provenance,
                )
                for item in summaries
            ]
        )
        assert len(lookup_statements) == 1
        assert not any(result.content_changed for result in unchanged)
        assert all(result.summary.embedding_ref == "quantized_vectors" for result in unchanged)

        changed_input = [
            *summaries[:2],
            SummaryNode(
                id=summaries[2].id,
                scope_type="section",
                scope_id=summaries[2].scope_id,
                text="Changed summary",
                provenance=summaries[2].provenance,
            ),
        ]
        changed = await repository.upsert_scopes(changed_input)
        await session.commit()
        assert [result.summary.id for result in changed] == [item.id for item in summaries]
        assert [result.content_changed for result in changed] == [False, False, True]
        assert changed[2].summary.embedding_ref is None


@pytest.mark.asyncio
async def test_summary_bulk_upsert_preserves_legacy_canonical_and_removes_duplicates(
    isolated_database,
) -> None:
    factory, _engine = isolated_database
    scope_id = new_id()
    legacy_ids = [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ]
    provenance = {"source": "legacy"}
    async with factory() as session:
        repository = SqlSummaryRepository(session)
        await repository.create_many(
            [
                SummaryNode(
                    id=summary_id,
                    scope_type="section",
                    scope_id=scope_id,
                    text="Stable summary",
                    provenance=provenance,
                    embedding_ref="quantized_vectors",
                )
                for summary_id in legacy_ids
            ]
        )
        await session.commit()

        result = (
            await repository.upsert_scopes(
                [
                    SummaryNode(
                        id=new_id(),
                        scope_type="section",
                        scope_id=scope_id,
                        text="Stable summary",
                        provenance=provenance,
                    )
                ]
            )
        )[0]
        await session.commit()

        assert result.summary.id == legacy_ids[0]
        assert result.summary.embedding_ref == "quantized_vectors"
        assert result.content_changed is False
        assert result.removed_ids == (legacy_ids[1],)
        remaining = await repository.list_by_scope("section", scope_id)
        assert [summary.id for summary in remaining] == [legacy_ids[0]]


@pytest.mark.asyncio
async def test_generate_summaries_bulk_upserts_sections_before_document(
    isolated_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, _engine = isolated_database
    collection_id = new_id()
    document_id = new_id()
    chunks = [
        Chunk(
            id=new_id(),
            document_id=document_id,
            text=f"Section {index} contains enough grounded text for a summary.",
            metadata={"chunk_index": index},
        )
        for index in range(3)
    ]
    async with factory() as session:
        await SqlCollectionRepository(session).create(
            Collection(id=collection_id, name="Corpus")
        )
        await SqlDocumentRepository(session).create(
            Document(
                id=document_id,
                collection_id=collection_id,
                title="Document",
                source_path="/tmp/document.txt",
                mime_type="text/plain",
                checksum="checksum",
            )
        )
        await SqlChunkRepository(session).create_many(chunks)
        await session.commit()

    original = SqlSummaryRepository.upsert_scopes
    batch_sizes: list[int] = []

    async def _record_bulk_upsert(
        self: SqlSummaryRepository,
        summaries: list[SummaryNode],
        *,
        canonical_identifier: bool = False,
        force_reembed: bool = False,
    ) -> Any:
        batch_sizes.append(len(summaries))
        return await original(
            self,
            summaries,
            canonical_identifier=canonical_identifier,
            force_reembed=force_reembed,
        )

    monkeypatch.setattr(SqlSummaryRepository, "upsert_scopes", _record_bulk_upsert)
    await GenerateSummariesJobHandler(factory).execute(
        Job(
            id=new_id(),
            job_type=JobType.GENERATE_SUMMARIES,
            target_id=document_id,
        )
    )

    assert batch_sizes == [len(chunks), 1]


def _proposition(
    proposition_id: str,
    chunk_id: str,
    text: str,
) -> Proposition:
    return Proposition(
        id=proposition_id,
        document_id="document",
        source_chunk_id=chunk_id,
        text=text,
    )


def test_graph_order_follows_chunk_and_sentence_positions() -> None:
    first_chunk = Chunk(
        id="chunk-first",
        document_id="document",
        text=(
            "Primera afirmación suficientemente extensa para conservarse. "
            "Segunda afirmación suficientemente extensa para conservarse."
        ),
        metadata={"chunk_index": 0},
    )
    second_chunk = Chunk(
        id="chunk-second",
        document_id="document",
        text="Tercera afirmación suficientemente extensa para conservarse.",
        metadata={"chunk_index": 1},
    )
    propositions = [
        _proposition("p3", second_chunk.id, second_chunk.text),
        _proposition(
            "p2",
            first_chunk.id,
            "Segunda afirmación suficientemente extensa para conservarse.",
        ),
        _proposition(
            "p1",
            first_chunk.id,
            "Primera afirmación suficientemente extensa para conservarse.",
        ),
    ]

    ordered = _order_propositions_for_graph(
        propositions,
        [second_chunk, first_chunk],
    )

    assert [proposition.id for proposition in ordered] == ["p1", "p2", "p3"]


@pytest.mark.asyncio
async def test_build_graph_handler_uses_reconstructed_source_order(
    isolated_database,
) -> None:
    factory, _engine = isolated_database
    collection_id = new_id()
    document_id = new_id()
    first_chunk = Chunk(
        id=new_id(),
        document_id=document_id,
        text=(
            "Primera afirmación suficientemente extensa para conservarse. "
            "Segunda afirmación suficientemente extensa para conservarse."
        ),
        metadata={"chunk_index": 0},
    )
    second_chunk = Chunk(
        id=new_id(),
        document_id=document_id,
        text="Tercera afirmación suficientemente extensa para conservarse.",
        metadata={"chunk_index": 1},
    )
    propositions = [
        _proposition("p3", second_chunk.id, second_chunk.text),
        _proposition(
            "p2",
            first_chunk.id,
            "Segunda afirmación suficientemente extensa para conservarse.",
        ),
        _proposition(
            "p1",
            first_chunk.id,
            "Primera afirmación suficientemente extensa para conservarse.",
        ),
    ]
    for proposition in propositions:
        proposition.document_id = document_id

    async with factory() as session:
        await SqlCollectionRepository(session).create(
            Collection(id=collection_id, name="Corpus")
        )
        await SqlDocumentRepository(session).create(
            Document(
                id=document_id,
                collection_id=collection_id,
                title="Document",
                source_path="/tmp/document.txt",
                mime_type="text/plain",
                checksum="checksum",
            )
        )
        await SqlChunkRepository(session).create_many([second_chunk, first_chunk])
        await SqlPropositionRepository(session).create_many(propositions)
        await session.commit()

    await BuildGraphJobHandler(factory).execute(
        Job(id=new_id(), job_type=JobType.BUILD_GRAPH, target_id=document_id)
    )

    async with factory() as session:
        edges = await SqlRelationRepository(session).list_by_source_ids(
            [proposition.id for proposition in propositions]
        )
    adjacency = [
        (edge.source_id, edge.target_id)
        for edge in edges
        if edge.relation == RelationType.ELABORATES.value
    ]
    assert set(adjacency) == {("p1", "p2"), ("p2", "p3")}


def _legacy_cross_reference_pairs(
    propositions: list[Proposition],
) -> list[tuple[str, str]]:
    def extract_keywords(text: str) -> set[str]:
        return {
            word_lower
            for word in re.sub(r"[^\w\s]", " ", text).split()
            if len(word_lower := word.lower()) >= 5
            and word_lower not in GRAPH_STOPWORDS
        }

    keywords = [extract_keywords(proposition.text) for proposition in propositions]
    counts = Counter(keyword for item in keywords for keyword in item)
    threshold = max(2, len(propositions) * 0.25)
    filtered = [
        {keyword for keyword in item if counts[keyword] <= threshold}
        for item in keywords
    ]
    links: list[tuple[str, str]] = []
    degree = {proposition.id: 0 for proposition in propositions}
    for index, source in enumerate(propositions):
        if not filtered[index]:
            continue
        for target_index in range(index + 2, len(propositions)):
            target = propositions[target_index]
            if degree[source.id] >= 5 or degree[target.id] >= 5:
                continue
            if filtered[index].intersection(filtered[target_index]):
                links.append((source.id, target.id))
                degree[source.id] += 1
                degree[target.id] += 1
    return links


def test_graph_early_exit_is_equivalent_to_legacy_scan() -> None:
    propositions = [
        _proposition(
            f"p{index:02d}",
            "chunk",
            f"Concepto{index // 8:02d} aparece en una afirmación suficientemente larga.",
        )
        for index in range(48)
    ]

    optimized = [
        (edge.source_id, edge.target_id)
        for edge in _build_cross_reference_edges(propositions)
        if edge.relation == RelationType.MENTIONS.value
    ]

    assert optimized == _legacy_cross_reference_pairs(propositions)


class _FakeEmbedder:
    embedding_dim = 384
    uses_fallback = False

    def __init__(self, **_kwargs: object) -> None:
        pass

    def ensure_indexable(self) -> None:
        pass

    async def embed_documents(
        self,
        texts: list[str],
        *,
        titles: list[str | None] | None = None,
    ) -> list[list[float]]:
        del titles
        return [[0.1] * self.embedding_dim for _text in texts]


class _FakeSparseEncoder:
    encoder_name = "test"
    uses_fallback = True

    def encode_document(self, _text: str) -> tuple[list[int], list[float]]:
        return [1], [1.0]

    def encode_documents(
        self,
        texts: list[str],
    ) -> list[tuple[list[int], list[float]]]:
        return [self.encode_document(text) for text in texts]


class _NoOpIngestionOrchestrator:
    def __init__(self, _session: AsyncSession) -> None:
        pass

    async def index_nodes(self, **_kwargs: object) -> None:
        pass


class _FailingQdrant:
    def __init__(self, **_kwargs: object) -> None:
        pass

    async def init_collection(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("qdrant unavailable")


class _PartiallyFailingQdrant(_FailingQdrant):
    async def init_collection(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def upsert(self, *_args: object, **_kwargs: object) -> None:
        raise ServiceUnavailableError(
            "qdrant",
            "partial batch persisted; retry idempotently",
        )


async def _seed_enrichment_target(factory, layer: str) -> tuple[str, str]:
    collection_id = new_id()
    document_id = new_id()
    async with factory() as session:
        await SqlCollectionRepository(session).create(
            Collection(id=collection_id, name="Corpus")
        )
        await SqlDocumentRepository(session).create(
            Document(
                id=document_id,
                collection_id=collection_id,
                title="Document",
                source_path="/tmp/document.txt",
                mime_type="text/plain",
                checksum="checksum",
            )
        )
        if layer == "proposition":
            entity_id = new_id()
            await SqlPropositionRepository(session).create_many(
                [
                    Proposition(
                        id=entity_id,
                        document_id=document_id,
                        source_chunk_id=new_id(),
                        text="A proposition long enough for the test.",
                    )
                ]
            )
        else:
            entity_id = new_id()
            await SqlSummaryRepository(session).create_many(
                [
                    SummaryNode(
                        id=entity_id,
                        scope_type="document",
                        scope_id=document_id,
                        text="A summary long enough for the test.",
                    )
                ]
            )
        await session.commit()
    return document_id, entity_id


@pytest.mark.asyncio
@pytest.mark.parametrize("layer", ["proposition", "summary"])
@pytest.mark.parametrize("qdrant_required", [True, False])
async def test_enrichment_handlers_honor_qdrant_required_independently_of_strict_mode(
    isolated_database,
    monkeypatch: pytest.MonkeyPatch,
    layer: str,
    qdrant_required: bool,
) -> None:
    factory, _engine = isolated_database
    settings = Settings(
        profile="dev",
        require_qdrant=qdrant_required,
        require_embeddings=True,
        candidate_backend="purepy",
    )
    assert settings.strict_mode_enabled is False

    monkeypatch.setattr(
        "atenex_nova.workers.jobs.memory_enrichment_job.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "atenex_nova.workers.jobs.memory_enrichment_job.EmbeddingGemmaAdapter",
        _FakeEmbedder,
    )
    monkeypatch.setattr(
        "atenex_nova.workers.jobs.memory_enrichment_job.StableSparseEncoder",
        _FakeSparseEncoder,
    )
    monkeypatch.setattr(
        "atenex_nova.workers.jobs.memory_enrichment_job.QdrantAdapter",
        _FailingQdrant,
    )
    monkeypatch.setattr(
        "atenex_nova.application.orchestrators.ingestion_orchestrator.IngestionOrchestrator",
        _NoOpIngestionOrchestrator,
    )

    document_id, entity_id = await _seed_enrichment_target(factory, layer)
    if layer == "proposition":
        handler: Any = EmbedPropositionsJobHandler(factory)
        job_type = JobType.EMBED_PROPOSITIONS
        payload: dict[str, object] = {}
    else:
        handler = EmbedSummariesJobHandler(factory)
        job_type = JobType.EMBED_SUMMARIES
        payload = {"summary_ids": [entity_id]}
    job = Job(
        id=new_id(),
        job_type=job_type,
        target_id=document_id,
        payload=payload,
    )

    if qdrant_required:
        with pytest.raises(RuntimeError, match="qdrant unavailable"):
            await handler.execute(job)
    else:
        result = await handler.execute(job)
        assert result is not None
        assert result["qdrant"] == "unavailable"

    async with factory() as session:
        if layer == "proposition":
            stored = await SqlPropositionRepository(session).list_by_document(document_id)
        else:
            stored = await SqlSummaryRepository(session).get_by_ids([entity_id])
        assert len(stored) == 1
        assert (stored[0].embedding_ref is not None) is (not qdrant_required)


@pytest.mark.asyncio
@pytest.mark.parametrize("layer", ["proposition", "summary"])
async def test_enrichment_handlers_retry_partial_optional_qdrant_writes(
    isolated_database,
    monkeypatch: pytest.MonkeyPatch,
    layer: str,
) -> None:
    factory, _engine = isolated_database
    settings = Settings(
        profile="dev",
        require_qdrant=False,
        require_embeddings=True,
        candidate_backend="purepy",
    )
    monkeypatch.setattr(
        "atenex_nova.workers.jobs.memory_enrichment_job.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "atenex_nova.workers.jobs.memory_enrichment_job.EmbeddingGemmaAdapter",
        _FakeEmbedder,
    )
    monkeypatch.setattr(
        "atenex_nova.workers.jobs.memory_enrichment_job.StableSparseEncoder",
        _FakeSparseEncoder,
    )
    monkeypatch.setattr(
        "atenex_nova.workers.jobs.memory_enrichment_job.QdrantAdapter",
        _PartiallyFailingQdrant,
    )
    monkeypatch.setattr(
        "atenex_nova.application.orchestrators.ingestion_orchestrator.IngestionOrchestrator",
        _NoOpIngestionOrchestrator,
    )

    document_id, entity_id = await _seed_enrichment_target(factory, layer)
    if layer == "proposition":
        handler: Any = EmbedPropositionsJobHandler(factory)
        job_type = JobType.EMBED_PROPOSITIONS
        payload: dict[str, object] = {}
    else:
        handler = EmbedSummariesJobHandler(factory)
        job_type = JobType.EMBED_SUMMARIES
        payload = {"summary_ids": [entity_id]}

    with pytest.raises(ServiceUnavailableError, match="partial batch persisted"):
        await handler.execute(
            Job(
                id=new_id(),
                job_type=job_type,
                target_id=document_id,
                payload=payload,
            )
        )

    async with factory() as session:
        if layer == "proposition":
            stored = await SqlPropositionRepository(session).list_by_document(document_id)
        else:
            stored = await SqlSummaryRepository(session).get_by_ids([entity_id])
        assert len(stored) == 1
        assert stored[0].embedding_ref is None

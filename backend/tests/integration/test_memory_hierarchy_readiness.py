"""Regression coverage for hierarchical memory and the READY barrier."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.application.services.document_readiness_service import (
    DocumentReadinessService,
)
from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.entities.proposition import Proposition
from atenex_nova.domain.entities.summary_node import SummaryNode
from atenex_nova.domain.value_objects.identifiers import (
    DocumentStatus,
    JobStatus,
    JobType,
    new_id,
)
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
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
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository
from atenex_nova.workers.jobs.memory_enrichment_job import (
    BuildCollectionMemoryJobHandler,
    GenerateSummariesJobHandler,
    extractive_summary,
)


@pytest.fixture()
async def session_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


def _text_settings() -> SimpleNamespace:
    return SimpleNamespace(
        visual_indexing_enabled=True,
        visual_index_text_documents=False,
    )


def test_extractive_fallback_restores_source_order() -> None:
    result = extractive_summary(
        [
            "Primero se presenta la tesis común. Luego aparece evidencia singular.",
            "Después la tesis común se contrasta. Finalmente llega la conclusión.",
        ],
        max_sentences=3,
    )

    evidence_order = [
        (item.source_index, item.sentence_index) for item in result.evidence
    ]
    assert evidence_order == sorted(evidence_order)
    assert result.text


@pytest.mark.asyncio
async def test_document_summaries_are_idempotent_grounded_and_not_collection_scoped(
    session_factory,
) -> None:
    collection_id = new_id()
    document_id = new_id()
    chunks = [
        Chunk(
            id=new_id(),
            document_id=document_id,
            text="La libertad presupone una vida capaz de ejercerla. La muerte la extingue.",
            summary="",
            token_count=14,
            node_ids=["n1"],
            metadata={"chunk_index": 0},
        ),
        Chunk(
            id=new_id(),
            document_id=document_id,
            text="Una sociedad debe asistir al vulnerable. El abandono no es autonomía.",
            summary="",
            token_count=13,
            node_ids=["n2"],
            metadata={"chunk_index": 1},
        ),
    ]
    async with session_factory() as session:
        await SqlCollectionRepository(session).create(
            Collection(id=collection_id, name="Corpus", description="")
        )
        document = Document(
            id=document_id,
            collection_id=collection_id,
            title="Ensayo",
            source_path="/tmp/ensayo.md",
            mime_type="text/markdown",
            checksum="checksum",
            status=DocumentStatus.INDEXED,
        )
        await SqlDocumentRepository(session).create(document)
        await SqlChunkRepository(session).create_many(chunks)
        await SqlPropositionRepository(session).create_many(
            [
                Proposition(
                    id=new_id(),
                    document_id=document_id,
                    source_chunk_id=chunks[0].id,
                    text="La libertad presupone una vida capaz de ejercerla.",
                )
            ]
        )
        await session.commit()

    handler = GenerateSummariesJobHandler(session_factory)
    await handler.execute(
        Job(
            id=new_id(),
            job_type=JobType.GENERATE_SUMMARIES,
            target_id=document_id,
        )
    )
    async with session_factory() as session:
        first_ids = {
            summary.id
            for summary in [
                *(await SqlSummaryRepository(session).list_sections_by_document(document_id)),
                *(await SqlSummaryRepository(session).list_by_document(document_id)),
            ]
        }
    await handler.execute(
        Job(
            id=new_id(),
            job_type=JobType.GENERATE_SUMMARIES,
            target_id=document_id,
        )
    )

    async with session_factory() as session:
        repo = SqlSummaryRepository(session)
        sections = await repo.list_sections_by_document(document_id)
        documents = await repo.list_by_document(document_id)
        collections = await repo.list_by_collection(collection_id)
        jobs = await SqlJobRepository(session).list_by_target(document_id)

        assert len(sections) == len(chunks)
        assert len(documents) == 1
        assert {summary.id for summary in [*sections, *documents]} == first_ids
        assert collections == []
        assert all(summary.provenance["source_scope_type"] == "chunk" for summary in sections)
        assert documents[0].provenance["source_scope_type"] == "section_summary"
        assert len(
            [job for job in jobs if job.job_type == JobType.EMBED_SUMMARIES]
        ) == 1


@pytest.mark.asyncio
async def test_collection_memory_is_one_bounded_hierarchical_representation(
    session_factory,
) -> None:
    collection_id = new_id()
    legacy_collection_summary_ids = [new_id(), new_id()]
    async with session_factory() as session:
        await SqlCollectionRepository(session).create(
            Collection(id=collection_id, name="Corpus completo", description="")
        )
        summary_repo = SqlSummaryRepository(session)
        await summary_repo.create_many(
            [
                SummaryNode(
                    id=summary_id,
                    scope_type="collection",
                    scope_id=collection_id,
                    text="Falso resumen por documento.",
                    embedding_ref="legacy_vectors",
                )
                for summary_id in legacy_collection_summary_ids
            ]
        )
        for index in range(7):
            document_id = new_id()
            await SqlDocumentRepository(session).create(
                Document(
                    id=document_id,
                    collection_id=collection_id,
                    title=f"Documento {index}",
                    source_path=f"/tmp/{index}.md",
                    mime_type="text/markdown",
                    checksum=f"checksum-{index}",
                    status=DocumentStatus.READY,
                )
            )
            await summary_repo.create_many(
                [
                    SummaryNode(
                        id=new_id(),
                        scope_type="document",
                        scope_id=document_id,
                        text=f"El documento {index} aporta una tesis y evidencia verificable.",
                    )
                ]
            )
        await session.commit()

    handler = BuildCollectionMemoryJobHandler(session_factory)
    for _ in range(2):
        await handler.execute(
            Job(
                id=new_id(),
                job_type=JobType.BUILD_COLLECTION_MEMORY,
                target_id=collection_id,
                payload={"batch_size": 3},
            )
        )

    async with session_factory() as session:
        summaries = await SqlSummaryRepository(session).list_by_collection(collection_id)
        jobs = await SqlJobRepository(session).list_by_target(collection_id)
        assert len(summaries) == 1
        provenance = summaries[0].provenance
        assert provenance["source_summary_count"] == 7
        assert provenance["leaf_batch_count"] == 3
        assert provenance["hierarchy_levels"] >= 2
        embed_jobs = [
            job for job in jobs if job.job_type == JobType.EMBED_COLLECTION_MEMORY
        ]
        assert len(embed_jobs) == 1
        assert set(embed_jobs[0].payload["obsolete_summary_ids"]) == set(
            legacy_collection_summary_ids
        )


async def _seed_complete_layers(
    session: AsyncSession,
    *,
    collection_id: str,
    document: Document,
    document_summary_embedded: bool = True,
) -> None:
    chunk = Chunk(
        id=new_id(),
        document_id=document.id,
        text="Una afirmación suficientemente extensa para ser memoria.",
        summary="Una afirmación.",
        token_count=9,
        node_ids=["n1"],
        embedding_ref="quantized_vectors",
    )
    await SqlDocumentRepository(session).create(document)
    await SqlChunkRepository(session).create_many([chunk])
    await SqlPropositionRepository(session).create_many(
        [
            Proposition(
                id=new_id(),
                document_id=document.id,
                source_chunk_id=chunk.id,
                text="Una afirmación suficientemente extensa.",
                embedding_ref="quantized_vectors",
            )
        ]
    )
    await SqlSummaryRepository(session).create_many(
        [
            SummaryNode(
                id=new_id(),
                scope_type="section",
                scope_id=chunk.id,
                text="Resumen de sección.",
                embedding_ref="quantized_vectors",
            ),
            SummaryNode(
                id=new_id(),
                scope_type="document",
                scope_id=document.id,
                text="Resumen de documento.",
                embedding_ref=(
                    "quantized_vectors" if document_summary_embedded else None
                ),
            ),
        ]
    )
    job_repo = SqlJobRepository(session)
    for job_type in (
        JobType.EMBED_DOCUMENT,
        JobType.EXTRACT_PROPOSITIONS,
        JobType.EMBED_PROPOSITIONS,
        JobType.GENERATE_SUMMARIES,
        JobType.EMBED_SUMMARIES,
        JobType.BUILD_GRAPH,
    ):
        succeeded = Job(id=new_id(), job_type=job_type, target_id=document.id)
        succeeded.status = JobStatus.SUCCEEDED
        await job_repo.create(succeeded)


@pytest.mark.asyncio
async def test_ready_barrier_publishes_complete_and_demotes_incomplete_documents(
    session_factory,
) -> None:
    collection_id = new_id()
    complete = Document(
        id=new_id(),
        collection_id=collection_id,
        title="Completo",
        source_path="/tmp/completo.md",
        mime_type="text/markdown",
        checksum="complete",
        status=DocumentStatus.INDEXED,
    )
    incomplete = Document(
        id=new_id(),
        collection_id=collection_id,
        title="Incompleto",
        source_path="/tmp/incompleto.md",
        mime_type="text/markdown",
        checksum="incomplete",
        status=DocumentStatus.READY,
    )
    async with session_factory() as session:
        await SqlCollectionRepository(session).create(
            Collection(id=collection_id, name="Readiness", description="")
        )
        await _seed_complete_layers(
            session,
            collection_id=collection_id,
            document=complete,
        )
        await _seed_complete_layers(
            session,
            collection_id=collection_id,
            document=incomplete,
            document_summary_embedded=False,
        )
        await session.commit()

    async with session_factory() as session:
        doc_repo = SqlDocumentRepository(session)
        complete_doc = await doc_repo.get_by_id(complete.id)
        incomplete_doc = await doc_repo.get_by_id(incomplete.id)
        assert complete_doc is not None and incomplete_doc is not None
        service = DocumentReadinessService(session, _text_settings())
        complete_report = await service.apply_barrier(complete_doc)
        incomplete_report = await service.apply_barrier(incomplete_doc)
        await session.commit()

        assert complete_report.ready is True
        assert incomplete_report.ready is False
        assert "summary_embeddings_missing" in incomplete_report.missing

    async with session_factory() as session:
        doc_repo = SqlDocumentRepository(session)
        assert (await doc_repo.get_by_id(complete.id)).status == DocumentStatus.READY
        assert (await doc_repo.get_by_id(incomplete.id)).status == DocumentStatus.INDEXED

        incomplete_doc = await doc_repo.get_by_id(incomplete.id)
        assert incomplete_doc is not None
        repair = await DocumentReadinessService(
            session,
            _text_settings(),
        ).enqueue_repairs(incomplete_doc)
        await session.commit()
        assert repair.job_types == (JobType.EMBED_SUMMARIES,)


@pytest.mark.asyncio
async def test_ready_barrier_requires_visual_job_for_pdf(session_factory) -> None:
    collection_id = new_id()
    document = Document(
        id=new_id(),
        collection_id=collection_id,
        title="Documento visual",
        source_path="/tmp/visual.pdf",
        mime_type="application/pdf",
        checksum="visual",
        status=DocumentStatus.INDEXED,
    )
    async with session_factory() as session:
        await SqlCollectionRepository(session).create(
            Collection(id=collection_id, name="Visual", description="")
        )
        await _seed_complete_layers(
            session,
            collection_id=collection_id,
            document=document,
        )
        await session.commit()

    async with session_factory() as session:
        persisted = await SqlDocumentRepository(session).get_by_id(document.id)
        assert persisted is not None
        report = await DocumentReadinessService(
            session,
            _text_settings(),
        ).apply_barrier(persisted)
        assert report.ready is False
        assert report.visual_required is True
        assert "visual_job_incomplete" in report.missing

        visual_job = Job(
            id=new_id(),
            job_type=JobType.INDEX_VISUAL_PAGES,
            target_id=document.id,
            status=JobStatus.SUCCEEDED,
        )
        await SqlJobRepository(session).create(visual_job)
        report = await DocumentReadinessService(
            session,
            _text_settings(),
        ).apply_barrier(persisted)
        await session.commit()
        assert report.ready is True

    async with session_factory() as session:
        persisted = await SqlDocumentRepository(session).get_by_id(document.id)
        assert persisted is not None
        assert persisted.status == DocumentStatus.READY


@pytest.mark.asyncio
async def test_ready_barrier_rejects_successes_from_an_older_generation(
    session_factory,
) -> None:
    collection_id = new_id()
    document = Document(
        id=new_id(),
        collection_id=collection_id,
        title="Regenerado",
        source_path="/tmp/regenerado.md",
        mime_type="text/markdown",
        checksum="regenerated",
        status=DocumentStatus.READY,
    )
    async with session_factory() as session:
        await SqlCollectionRepository(session).create(
            Collection(id=collection_id, name="Generaciones", description="")
        )
        await _seed_complete_layers(
            session,
            collection_id=collection_id,
            document=document,
        )
        newer_index_job = Job(
            id=new_id(),
            job_type=JobType.EMBED_DOCUMENT,
            target_id=document.id,
            status=JobStatus.SUCCEEDED,
        )
        await SqlJobRepository(session).create(newer_index_job)
        await session.commit()

    async with session_factory() as session:
        persisted = await SqlDocumentRepository(session).get_by_id(document.id)
        assert persisted is not None
        report = await DocumentReadinessService(
            session,
            _text_settings(),
        ).apply_barrier(persisted)
        await session.commit()

        assert report.ready is False
        assert "graph_job_incomplete" in report.missing
        assert "summary_embedding_job_incomplete" in report.missing
        assert persisted.status == DocumentStatus.INDEXED

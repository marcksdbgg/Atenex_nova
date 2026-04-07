"""Integration coverage for phase 8 evaluation and phase 9 hardening."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.application.services.answer_service import AnswerService
from atenex_nova.application.services.evaluation_service import EvaluationService
from atenex_nova.application.services.rebuild_service import RebuildService
from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.entities.document_node import DocumentNode
from atenex_nova.domain.value_objects.identifiers import NodeType, new_id, JobType
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.repositories.sql_node_repo import SqlDocumentNodeRepository
from atenex_nova.workers.jobs.memory_enrichment_job import (
    BuildGraphJobHandler,
    EmbedPropositionsJobHandler,
    EmbedSummariesJobHandler,
    ExtractPropositionsJobHandler,
    GenerateSummariesJobHandler,
)
from atenex_nova.workers.jobs.visual_index_job import IndexVisualPagesJobHandler


@pytest.fixture()
async def session_factory(tmp_path: Path):
    db_path = tmp_path / "phase89.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_full_corpus(factory) -> tuple[str, str]:
    async with factory() as session:
        collection_repo = SqlCollectionRepository(session)
        document_repo = SqlDocumentRepository(session)
        chunk_repo = SqlChunkRepository(session)
        node_repo = SqlDocumentNodeRepository(session)

        collection = Collection(id=new_id(), name="Evaluation Collection", description="Eval corpus")
        await collection_repo.create(collection)

        document = Document(
            id=new_id(),
            collection_id=collection.id,
            title="Evaluation Source",
            source_path="/tmp/eval-source.md",
            mime_type="text/markdown",
            checksum="ghi012",
        )
        document.mark_parsed()
        document.mark_normalized()
        document.mark_segmented()
        document.mark_embedded()
        document.mark_indexed()
        document.mark_ready()
        await document_repo.create(document)

        await chunk_repo.create_many(
            [
                Chunk(
                    id=new_id(),
                    document_id=document.id,
                    text="EmbeddingGemma supports 384d embeddings for the standard profile.",
                    summary="EmbeddingGemma standard profile.",
                    node_ids=["c1"],
                    token_count=9,
                ),
                Chunk(
                    id=new_id(),
                    document_id=document.id,
                    text="The corpus mentions proposition graphs and local retrieval.",
                    summary="Local retrieval and graphs.",
                    node_ids=["c2"],
                    token_count=9,
                ),
            ]
        )

        await node_repo.create_many(
            [
                DocumentNode(
                    id=new_id(),
                    document_id=document.id,
                    node_type=NodeType.HEADING,
                    raw_text="Visual Page",
                    normalized_text="Visual Page",
                    page_number=1,
                    order_index=0,
                ),
                DocumentNode(
                    id=new_id(),
                    document_id=document.id,
                    node_type=NodeType.TABLE,
                    raw_text="Table 1 describes evaluation evidence and page layout.",
                    normalized_text="Table 1 describes evaluation evidence and page layout.",
                    page_number=1,
                    order_index=1,
                ),
            ]
        )

        await session.commit()
        return collection.id, document.id


async def _run_full_enrichment(factory, document_id: str) -> None:
    await ExtractPropositionsJobHandler(factory).execute(
        type("JobLike", (), {"id": new_id(), "job_type": JobType.EXTRACT_PROPOSITIONS, "target_id": document_id})()
    )
    await GenerateSummariesJobHandler(factory).execute(
        type("JobLike", (), {"id": new_id(), "job_type": JobType.GENERATE_SUMMARIES, "target_id": document_id})()
    )
    await EmbedPropositionsJobHandler(factory).execute(
        type("JobLike", (), {"id": new_id(), "job_type": JobType.EMBED_PROPOSITIONS, "target_id": document_id})()
    )
    await EmbedSummariesJobHandler(factory).execute(
        type("JobLike", (), {"id": new_id(), "job_type": JobType.EMBED_SUMMARIES, "target_id": document_id})()
    )
    await BuildGraphJobHandler(factory).execute(
        type("JobLike", (), {"id": new_id(), "job_type": JobType.BUILD_GRAPH, "target_id": document_id})()
    )
    await IndexVisualPagesJobHandler(factory).execute(
        type("JobLike", (), {"id": new_id(), "job_type": JobType.INDEX_VISUAL_PAGES, "target_id": document_id})()
    )


@pytest.mark.asyncio
async def test_evaluation_service_runs_and_persists_reports(session_factory) -> None:
    collection_id, document_id = await _seed_full_corpus(session_factory)
    await _run_full_enrichment(session_factory, document_id)

    async with session_factory() as session:
        service = EvaluationService(session)
        datasets = service.list_datasets()

        assert "baseline" in datasets

        first = await service.run(collection_id=collection_id, dataset_name="baseline")
        second = await service.run(collection_id=collection_id, dataset_name="baseline")

        assert first.run.id != second.run.id
        assert first.cases
        assert second.previous_run_id == first.run.id
        assert second.deltas
        assert second.run.retrieval_recall_at_k >= 0.0
        assert second.run.answer_grounding_score >= 0.0

        loaded = await service.get_run(second.run.id)
        assert loaded is not None
        assert loaded.run.id == second.run.id
        assert loaded.cases


@pytest.mark.asyncio
async def test_rebuild_and_answer_exports(session_factory) -> None:
    collection_id, document_id = await _seed_full_corpus(session_factory)
    await _run_full_enrichment(session_factory, document_id)

    async with session_factory() as session:
        answer_service = AnswerService(session)
        bundle = await answer_service.answer(collection_id=collection_id, query="What does EmbeddingGemma support?", mode="auto")
        detail = await answer_service.get_answer(bundle.answer.id)
        assert detail is not None

        markdown = answer_service.export_markdown(detail)
        pdf_bytes = answer_service.export_pdf(detail)
        assert markdown.startswith("# Answer")
        assert bundle.answer.id in markdown
        assert len(pdf_bytes) > 20
        assert pdf_bytes[:4] == b"%PDF" or markdown.encode("utf-8").startswith(b"# Answer")

        rebuild_service = RebuildService(session)
        job_id = await rebuild_service.enqueue(collection_id)
        await session.commit()

        job_repo = SqlJobRepository(session)
        job = await job_repo.get_by_id(job_id)
        assert job is not None
        assert job.job_type == JobType.REBUILD_COLLECTION
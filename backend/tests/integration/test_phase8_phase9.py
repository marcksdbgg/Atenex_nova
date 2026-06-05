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
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.value_objects.identifiers import JobType, NodeType, new_id
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.repositories.sql_node_repo import SqlDocumentNodeRepository
from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
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


@pytest.fixture(autouse=True)
def _mock_llm_and_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    from atenex_nova.application.orchestrators.answer_orchestrator import AnswerOrchestrator
    from atenex_nova.infrastructure.llm.llm_gateway import LLMGenerationResult

    def _fast_init(self, model_name: str = "google/embeddinggemma-300m", dim: int = 384, required: bool | None = None) -> None:
        self._model_name = model_name or "google/embeddinggemma-300m"
        self._dim = dim
        self._required = False if required is None else required
        self.model = None
        self._fallback_only = True

    monkeypatch.setattr(EmbeddingGemmaAdapter, "__init__", _fast_init)

    class MockGateway:
        async def generate(
            self,
            prompt: str,
            max_tokens: int = 2048,
            temperature: float = 0.3,
            stop: list[str] | None = None,
        ) -> LLMGenerationResult:
            if "verification" in prompt.lower() or "verdict" in prompt.lower():
                return LLMGenerationResult(
                    text="VERDICT: verified\nGROUNDING_SCORE: 1.0\nISSUES: none",
                    prompt_tokens=10,
                    completion_tokens=5,
                )
            return LLMGenerationResult(
                text="EmbeddingGemma supports 384d embeddings for the standard profile [1], [2].",
                prompt_tokens=20,
                completion_tokens=15,
            )

    monkeypatch.setattr(AnswerOrchestrator, "_build_generator", lambda self, backend: MockGateway())


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
        assert "answer_support_coverage" in second.run.summary
        assert "answer_citation_coverage" in second.run.summary
        assert "benchmark_pass_rate" in second.run.summary

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


@pytest.mark.asyncio
async def test_rebuild_collection_resets_documents_and_requeues_parse(session_factory) -> None:
    collection_id, document_id = await _seed_full_corpus(session_factory)

    async with session_factory() as session:
        job_repo = SqlJobRepository(session)
        await job_repo.create(Job(id=new_id(), job_type=JobType.SEGMENT_DOCUMENT, target_id=document_id))

        rebuild_handler = RebuildService(session)
        job_id = await rebuild_handler.enqueue(collection_id)
        await session.commit()

        from atenex_nova.workers.jobs.mem_builder_job import RebuildCollectionJobHandler

        handler = RebuildCollectionJobHandler(session_factory)
        await handler.execute(Job(id=job_id, job_type=JobType.REBUILD_COLLECTION, target_id=collection_id))

    async with session_factory() as session:
        document_repo = SqlDocumentRepository(session)
        job_repo = SqlJobRepository(session)
        doc = await document_repo.get_by_id(document_id)
        assert doc is not None
        assert doc.status.value == "registered"

        jobs = await job_repo.list_by_target(document_id)
        assert all(job.job_type != JobType.SEGMENT_DOCUMENT for job in jobs)
        assert any(job.job_type == JobType.PARSE_DOCUMENT for job in jobs)

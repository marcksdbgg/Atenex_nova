"""Integration coverage for phase 6 answers and phase 7 visual retrieval."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.application.orchestrators.retrieval_orchestrator import RetrievalOrchestrator
from atenex_nova.application.services.answer_service import AnswerService
from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.entities.document_node import DocumentNode
from atenex_nova.domain.value_objects.identifiers import JobType, NodeType, new_id
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
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


async def _require_qdrant_or_skip() -> None:
    client = AsyncQdrantClient(host="localhost", port=6333)
    try:
        await client.get_collections()
    except Exception as exc:
        pytest.skip(f"Qdrant unavailable for integration test: {exc}")
    finally:
        await client.close()


async def _require_llm_or_skip() -> None:
    pass


async def _require_embeddings_or_skip() -> None:
    pass


@pytest.fixture(autouse=True)
def _mock_llm_and_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
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


@pytest.fixture()
async def session_factory(tmp_path: Path):
    db_path = tmp_path / "phase67.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_text_corpus(factory) -> tuple[str, str]:
    async with factory() as session:
        collection_repo = SqlCollectionRepository(session)
        document_repo = SqlDocumentRepository(session)
        chunk_repo = SqlChunkRepository(session)

        collection = Collection(id=new_id(), name="Phase 6 Collection", description="Answer corpus")
        await collection_repo.create(collection)

        document = Document(
            id=new_id(),
            collection_id=collection.id,
            title="Answer Source",
            source_path="/tmp/answer-source.md",
            mime_type="text/markdown",
            checksum="abc456",
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
                text="The system uses local retrieval and proposition graphs for query answering.",
                summary="Local retrieval and graphs.",
                node_ids=["n2"],
                token_count=10,
            ),
        ]
        await chunk_repo.create_many(chunks)
        await session.commit()
        return collection.id, document.id


async def _run_enrichment(factory, document_id: str) -> None:
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


@pytest.mark.asyncio
async def test_phase6_answer_generation_and_persistence(session_factory) -> None:
    await _require_llm_or_skip()
    await _require_embeddings_or_skip()
    await _require_qdrant_or_skip()

    collection_id, document_id = await _seed_text_corpus(session_factory)
    await _run_enrichment(session_factory, document_id)

    async with session_factory() as session:
        service = AnswerService(session)
        bundle = await service.answer(
            collection_id=collection_id,
            query="What does EmbeddingGemma support?",
            mode="auto",
            generation_profile="standard",
        )

        assert bundle.answer.text
        assert bundle.draft_text.strip()
        assert not bundle.draft_text.startswith((
            "I could not find grounded evidence",
            "Corpus-level synthesis:",
            "Hierarchical synthesis:",
            "Visual grounding:",
        ))
        assert bundle.citations
        assert bundle.verification.grounding_score >= 0.0

        detail = await service.get_answer(bundle.answer.id)
        assert detail is not None
        assert detail.answer.id == bundle.answer.id
        assert detail.citations
        assert detail.evidence_items


async def _seed_visual_corpus(factory) -> tuple[str, str]:
    async with factory() as session:
        collection_repo = SqlCollectionRepository(session)
        document_repo = SqlDocumentRepository(session)
        node_repo = SqlDocumentNodeRepository(session)

        collection = Collection(id=new_id(), name="Phase 7 Collection", description="Visual corpus")
        await collection_repo.create(collection)

        document = Document(
            id=new_id(),
            collection_id=collection.id,
            title="Visual Source",
            source_path="/tmp/visual-source.pdf",
            mime_type="application/pdf",
            checksum="def789",
        )
        document.mark_parsed()
        document.mark_normalized()
        document.mark_segmented()
        document.mark_embedded()
        document.mark_indexed()
        document.mark_ready()
        await document_repo.create(document)

        nodes = [
            DocumentNode(
                id=new_id(),
                document_id=document.id,
                node_type=NodeType.HEADING,
                raw_text="Visual Tables",
                normalized_text="Visual Tables",
                page_number=1,
                order_index=0,
            ),
            DocumentNode(
                id=new_id(),
                document_id=document.id,
                node_type=NodeType.TABLE,
                raw_text="Table 1 shows local retrieval performance and page counts.",
                normalized_text="Table 1 shows local retrieval performance and page counts.",
                page_number=1,
                order_index=1,
            ),
            DocumentNode(
                id=new_id(),
                document_id=document.id,
                node_type=NodeType.PARAGRAPH,
                raw_text="The second page contains a figure about visual grounding.",
                normalized_text="The second page contains a figure about visual grounding.",
                page_number=2,
                order_index=2,
            ),
        ]
        await node_repo.create_many(nodes)
        await session.commit()
        return collection.id, document.id


@pytest.mark.asyncio
async def test_phase7_visual_index_and_visual_retrieval(session_factory) -> None:
    await _require_qdrant_or_skip()
    await _require_embeddings_or_skip()

    collection_id, document_id = await _seed_visual_corpus(session_factory)

    await IndexVisualPagesJobHandler(session_factory).execute(
        type("JobLike", (), {"id": new_id(), "job_type": JobType.INDEX_VISUAL_PAGES, "target_id": document_id})()
    )

    async with session_factory() as session:
        orchestrator = RetrievalOrchestrator(session)
        result = await orchestrator.search(collection_id=collection_id, query_text="table on page 1", mode="visual")

        assert result.hits
        assert any(hit.source_type == "visual_page" for hit in result.hits)
        assert result.query.route_mode == "visual"
        assert result.evidence_pack.items

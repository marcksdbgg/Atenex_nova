"""End-to-end coverage for document ingestion and query readiness."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.dependencies import get_blob_store
from atenex_nova.domain.entities.document_node import DocumentNode
from atenex_nova.domain.value_objects.identifiers import JobType, NodeType, new_id
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.repositories.sql_node_repo import SqlDocumentNodeRepository
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import SqlPropositionRepository
from atenex_nova.infrastructure.db.repositories.sql_relation_repo import SqlRelationRepository
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository
from atenex_nova.infrastructure.db.session import get_session
from atenex_nova.infrastructure.files.blob_store import BlobStore
from atenex_nova.infrastructure.parsing.docling_adapter import DoclingParserAdapter
from atenex_nova.main import app
from atenex_nova.workers.jobs.ingestion_job import NormalizeDocumentJobHandler, ParseDocumentJobHandler
from atenex_nova.workers.jobs.mem_builder_job import EmbedDocumentJobHandler, SegmentDocumentJobHandler
from atenex_nova.workers.jobs.memory_enrichment_job import (
    BuildGraphJobHandler,
    EmbedPropositionsJobHandler,
    EmbedSummariesJobHandler,
    ExtractPropositionsJobHandler,
    GenerateSummariesJobHandler,
)
from atenex_nova.workers.jobs.visual_index_job import IndexVisualPagesJobHandler


@pytest.fixture()
async def e2e_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "e2e.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    blob_root = tmp_path / "uploads"
    visual_root = tmp_path / "visual_pages"
    blob_store = BlobStore(blob_root)

    async def override_get_session():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setattr(
        "atenex_nova.infrastructure.visual.colpali_adapter.get_settings",
        lambda: SimpleNamespace(visual_pages_path=visual_root),
    )

    def fake_embedding_init(self, model_name: str = "google/embeddinggemma-300m", dim: int = 384) -> None:
        self._model_name = model_name or "google/embeddinggemma-300m"
        self._dim = dim
        self.model = None
        self._fallback_only = True

    monkeypatch.setattr(
        "atenex_nova.infrastructure.embeddings.embedding_adapter.EmbeddingGemmaAdapter.__init__",
        fake_embedding_init,
        raising=True,
    )

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_blob_store] = lambda: blob_store

    try:
        yield {
            "session_factory": session_factory,
            "blob_root": blob_root,
            "visual_root": visual_root,
        }
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def _run_jobs_to_completion(session_factory) -> None:
    handlers = {
        JobType.PARSE_DOCUMENT.value: ParseDocumentJobHandler(session_factory),
        JobType.NORMALIZE_DOCUMENT.value: NormalizeDocumentJobHandler(session_factory),
        JobType.SEGMENT_DOCUMENT.value: SegmentDocumentJobHandler(session_factory),
        JobType.EMBED_DOCUMENT.value: EmbedDocumentJobHandler(session_factory),
        JobType.EMBED_CHUNKS.value: EmbedDocumentJobHandler(session_factory),
        JobType.EXTRACT_PROPOSITIONS.value: ExtractPropositionsJobHandler(session_factory),
        JobType.GENERATE_SUMMARIES.value: GenerateSummariesJobHandler(session_factory),
        JobType.EMBED_PROPOSITIONS.value: EmbedPropositionsJobHandler(session_factory),
        JobType.EMBED_SUMMARIES.value: EmbedSummariesJobHandler(session_factory),
        JobType.BUILD_GRAPH.value: BuildGraphJobHandler(session_factory),
        JobType.INDEX_VISUAL_PAGES.value: IndexVisualPagesJobHandler(session_factory),
    }

    while True:
        async with session_factory() as session:
            job_repo = SqlJobRepository(session)
            job = await job_repo.get_next_pending()
            if job is None:
                await session.commit()
                return

            handler = handlers.get(job.job_type.value)
            if handler is None:
                raise AssertionError(f"No handler registered for {job.job_type.value}")

            job.start()
            await job_repo.update(job)
            await session.commit()

        try:
            result = await handler.execute(job)
        except Exception as exc:  # pragma: no cover - surfaced to the test
            async with session_factory() as session:
                job_repo = SqlJobRepository(session)
                persisted = await job_repo.get_by_id(job.id)
                assert persisted is not None
                persisted.fail(str(exc))
                await job_repo.update(persisted)
                await session.commit()
            raise

        async with session_factory() as session:
            job_repo = SqlJobRepository(session)
            persisted = await job_repo.get_by_id(job.id)
            assert persisted is not None
            persisted.succeed(result)
            await job_repo.update(persisted)
            await session.commit()


async def _create_collection(client: AsyncClient, name: str) -> str:
    response = await client.post(
        "/collections",
        json={"name": name, "description": f"{name} corpus", "language_profile": "auto"},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _search(client: AsyncClient, collection_id: str, query: str) -> dict:
    response = await client.post(
        "/queries/search",
        json={"collection_id": collection_id, "query": query, "mode": "auto"},
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_end_to_end_upload_ingestion_reaches_queryable_state(e2e_env, tmp_path: Path) -> None:
    session_factory = e2e_env["session_factory"]
    blob_root = e2e_env["blob_root"]

    source_file = tmp_path / "upload-source.txt"
    source_file.write_text(
        "EmbeddingGemma supports 384d embeddings for the standard profile.\n"
        "The local pipeline stores chunks, propositions, and summaries for retrieval.",
        encoding="utf-8",
    )

    async def fake_parse(self, file_path: str, document_id: str) -> list[DocumentNode]:
        text = Path(file_path).read_text(encoding="utf-8").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()] or [text]
        return [
            DocumentNode(
                id=new_id(),
                document_id=document_id,
                node_type=NodeType.HEADING if index == 0 else NodeType.PARAGRAPH,
                raw_text=line,
                normalized_text="",
                page_number=index + 1,
                order_index=index,
            )
            for index, line in enumerate(lines)
        ]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(DoclingParserAdapter, "parse", fake_parse, raising=True)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            collection_id = await _create_collection(client, "Upload E2E")
            with source_file.open("rb") as handle:
                response = await client.post(
                    f"/collections/{collection_id}/documents",
                    files={"file": (source_file.name, handle, "text/plain")},
                )

            assert response.status_code == 201
            document = response.json()
            assert document["source_path"] != str(source_file.resolve())
            assert str(blob_root) in document["source_path"]
            assert blob_root.exists()
            assert any(blob_root.rglob(source_file.name))

            await _run_jobs_to_completion(session_factory)

            audit_response = await client.get(
                "/observability/audit",
                params={"entity_type": "document", "entity_id": document["id"]},
            )
            assert audit_response.status_code == 200
            audit_events = audit_response.json()
            stages = {event["stage"] for event in audit_events}
            assert {"parse", "normalize", "segment", "embed_index", "index_visual_pages"}.issubset(stages)
            assert all("duration_ms" in event for event in audit_events)

            query_result = await _search(client, collection_id, "What does EmbeddingGemma support?")
            assert query_result["total_hits"] > 0
            assert any("EmbeddingGemma" in hit["snippet"] for hit in query_result["hits"])

            query_audit = await client.get(
                "/observability/audit",
                params={"entity_type": "query", "entity_id": query_result["query_id"]},
            )
            assert query_audit.status_code == 200
            query_events = query_audit.json()
            assert any(event["stage"] == "search" for event in query_events)
            assert any(event["stage"] == "score_chunks" for event in query_events)

    async with session_factory() as session:
        document_repo = SqlDocumentRepository(session)
        chunk_repo = SqlChunkRepository(session)
        proposition_repo = SqlPropositionRepository(session)
        summary_repo = SqlSummaryRepository(session)
        relation_repo = SqlRelationRepository(session)

        docs = await document_repo.list_by_collection(collection_id)
        assert docs and docs[0].status.value == "ready"
        assert await chunk_repo.list_by_collection(collection_id)
        assert await proposition_repo.list_by_collection(collection_id)
        assert await summary_repo.list_by_collection(collection_id)
        assert await relation_repo.list_by_source_ids([prop.id for prop in await proposition_repo.list_by_collection(collection_id)])


@pytest.mark.asyncio
async def test_end_to_end_local_path_import_keeps_original_file_reference(e2e_env, tmp_path: Path) -> None:
    session_factory = e2e_env["session_factory"]
    blob_root = e2e_env["blob_root"]

    source_file = tmp_path / "local-source.txt"
    source_file.write_text(
        "EmbeddingGemma supports 384d embeddings for the standard profile.\n"
        "Local imports should reuse the original file path without duplicating bytes.",
        encoding="utf-8",
    )

    async def fake_parse(self, file_path: str, document_id: str) -> list[DocumentNode]:
        text = Path(file_path).read_text(encoding="utf-8").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()] or [text]
        return [
            DocumentNode(
                id=new_id(),
                document_id=document_id,
                node_type=NodeType.HEADING if index == 0 else NodeType.PARAGRAPH,
                raw_text=line,
                normalized_text="",
                page_number=index + 1,
                order_index=index,
            )
            for index, line in enumerate(lines)
        ]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(DoclingParserAdapter, "parse", fake_parse, raising=True)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            collection_id = await _create_collection(client, "Local Import E2E")
            response = await client.post(
                f"/collections/{collection_id}/documents/import",
                json={"source_path": str(source_file), "title": "Local Source"},
            )

            assert response.status_code == 201
            document = response.json()
            assert document["source_path"] == str(source_file.resolve())
            assert not blob_root.exists() or not any(blob_root.iterdir())

            await _run_jobs_to_completion(session_factory)

            audit_response = await client.get(
                "/observability/audit",
                params={"entity_type": "document", "entity_id": document["id"]},
            )
            assert audit_response.status_code == 200
            audit_events = audit_response.json()
            assert {"parse", "normalize", "segment", "embed_index", "index_visual_pages"}.issubset(
                {event["stage"] for event in audit_events}
            )

            query_result = await _search(client, collection_id, "What does EmbeddingGemma support?")
            assert query_result["total_hits"] > 0
            assert any("EmbeddingGemma" in hit["snippet"] for hit in query_result["hits"])

            query_audit = await client.get(
                "/observability/audit",
                params={"entity_type": "query", "entity_id": query_result["query_id"]},
            )
            assert query_audit.status_code == 200
            query_events = query_audit.json()
            assert any(event["stage"] == "search" for event in query_events)

    async with session_factory() as session:
        document_repo = SqlDocumentRepository(session)
        docs = await document_repo.list_by_collection(collection_id)
        assert docs and docs[0].source_path == str(source_file.resolve())
        assert docs[0].status.value == "ready"


@pytest.mark.asyncio
async def test_end_to_end_parse_failure_surfaces_error_message_and_failed_audit(e2e_env, tmp_path: Path) -> None:
    session_factory = e2e_env["session_factory"]

    source_file = tmp_path / "broken-source.txt"
    source_file.write_text("This document will fail during parsing.", encoding="utf-8")

    async def failing_parse(self, file_path: str, document_id: str) -> list[DocumentNode]:
        raise RuntimeError("docling exploded")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(DoclingParserAdapter, "parse", failing_parse, raising=True)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            collection_id = await _create_collection(client, "Failure E2E")
            with source_file.open("rb") as handle:
                response = await client.post(
                    f"/collections/{collection_id}/documents",
                    files={"file": (source_file.name, handle, "text/plain")},
                )

            assert response.status_code == 201
            document = response.json()

            with pytest.raises(RuntimeError, match="docling exploded"):
                await _run_jobs_to_completion(session_factory)

            document_response = await client.get(f"/documents/{document['id']}")
            assert document_response.status_code == 200
            persisted_document = document_response.json()
            assert persisted_document["status"] == "failed"
            assert "docling exploded" in (persisted_document["error_message"] or "")

            audit_response = await client.get(
                "/observability/audit",
                params={"entity_type": "document", "entity_id": document["id"]},
            )
            assert audit_response.status_code == 200
            audit_events = audit_response.json()
            parse_event = next(event for event in audit_events if event["stage"] == "parse")
            assert parse_event["status"] == "failed"
            assert "docling exploded" in parse_event["metrics"]["error"]

            evidence_response = await client.get(f"/observability/documents/{document['id']}/evidence")
            assert evidence_response.status_code == 200
            evidence = evidence_response.json()
            assert evidence["document"]["error_message"] == "docling exploded"
            assert evidence["jobs"]
            assert any(job["error"] and "docling exploded" in job["error"] for job in evidence["jobs"])
            assert any(event["status"] == "failed" for event in evidence["audit_events"])
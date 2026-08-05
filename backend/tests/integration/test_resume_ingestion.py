"""Integration tests for resuming ingestion and clean-slate reprocessing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.application.services.collection_service import CollectionService
from atenex_nova.application.services.document_service import DocumentService
from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.entities.proposition import Proposition
from atenex_nova.domain.entities.relation_edge import RelationEdge
from atenex_nova.domain.entities.summary_node import SummaryNode
from atenex_nova.domain.value_objects.identifiers import DocumentStatus, JobStatus, JobType, new_id
from atenex_nova.infrastructure.db.models.tables import (
    QuantizationProfileModel,
    QuantizedVectorModel,
)
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.repositories.sql_node_repo import SqlDocumentNodeRepository
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import SqlPropositionRepository
from atenex_nova.infrastructure.db.repositories.sql_relation_repo import SqlRelationRepository
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository
from atenex_nova.presentation.api.routers.collections import resume_collection_ingestion
from atenex_nova.shared.config.settings import Settings
from atenex_nova.workers.jobs.ingestion_job import ParseDocumentJobHandler


@pytest.fixture()
async def session_factory(tmp_path: Path):
    db_path = tmp_path / "resume_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture()
def mock_candidate_index(monkeypatch: pytest.MonkeyPatch):
    mock_idx = MagicMock()
    mock_idx.remove_vectors = AsyncMock()
    monkeypatch.setattr(
        "atenex_nova.workers.jobs.ingestion_job.build_candidate_index",
        lambda session: mock_idx,
    )
    return mock_idx


@pytest.fixture()
def mock_qdrant(monkeypatch: pytest.MonkeyPatch):
    mock_qd = MagicMock()
    mock_qd.delete_points = AsyncMock()
    mock_qd.delete_by_filter = AsyncMock()
    mock_qd.is_available = True
    monkeypatch.setattr(
        "atenex_nova.workers.jobs.ingestion_job.QdrantAdapter",
        lambda **kwargs: mock_qd,
    )
    return mock_qd


@pytest.fixture()
def mock_parser(monkeypatch: pytest.MonkeyPatch):
    mock_p = MagicMock()
    mock_p.parse = AsyncMock(return_value=[])  # Empty list of nodes to keep it simple or raise
    monkeypatch.setattr(
        "atenex_nova.workers.jobs.ingestion_job.DoclingParserAdapter",
        lambda: mock_p,
    )
    return mock_p


@pytest.fixture()
def mock_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    settings = Settings(
        visual_pages_path=tmp_path / "visual_pages",
        embedding_profile="standard",
        candidate_backend="purepy",
    )
    settings.visual_pages_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("atenex_nova.shared.config.settings.get_settings", lambda: settings)
    monkeypatch.setattr("atenex_nova.workers.jobs.ingestion_job.get_settings", lambda: settings)
    return settings


@pytest.mark.asyncio
async def test_re_register_failed_document_requeues_job(session_factory) -> None:
    async with session_factory() as session:
        doc_repo = SqlDocumentRepository(session)
        job_repo = SqlJobRepository(session)
        doc_service = DocumentService(doc_repo=doc_repo, job_repo=job_repo)

        # 1. Create a failed document
        doc = Document(
            id=new_id(),
            collection_id="col1",
            title="Failed Doc",
            source_path="failed.txt",
            checksum="chk123",
            mime_type="text/plain",
        )
        doc.status = DocumentStatus.FAILED
        doc.error_message = "Some error"
        await doc_repo.create(doc)

        # Also create a pending/stale job for it
        stale_job = Job(id=new_id(), job_type=JobType.PARSE_DOCUMENT, target_id=doc.id)
        stale_job.status = JobStatus.PENDING
        await job_repo.create(stale_job)
        await session.commit()

        # 2. Re-register via register method (representing user retry)
        # Create a temp file to pass resolve check
        tmp_file = Path("failed.txt")
        tmp_file.write_text("dummy", encoding="utf-8")

        # Mock resolve path to find this temp file
        doc_service._resolve_source_path = lambda path: Path(path)

        await doc_service.register(
            collection_id="col1",
            title="Failed Doc",
            source_path="failed.txt",
            checksum="chk123",
            mime_type="text/plain",
        )

        await session.commit()

        # Check document state
        updated_doc = await doc_repo.get_by_id(doc.id)
        assert updated_doc is not None
        assert updated_doc.status == DocumentStatus.REGISTERED
        assert updated_doc.error_message is None

        # Check job queue
        jobs = await job_repo.list_by_target(doc.id)
        assert len(jobs) == 1
        assert jobs[0].job_type == JobType.PARSE_DOCUMENT
        assert jobs[0].status == JobStatus.PENDING
        assert jobs[0].id != stale_job.id  # New job created

        # Clean up temp file
        if tmp_file.exists():
            tmp_file.unlink()


@pytest.mark.asyncio
async def test_clean_slate_reprocessing_deletes_old_records(
    session_factory, mock_candidate_index, mock_qdrant, mock_parser, mock_settings
) -> None:
    async with session_factory() as session:
        doc_repo = SqlDocumentRepository(session)
        chunk_repo = SqlChunkRepository(session)
        proposition_repo = SqlPropositionRepository(session)
        summary_repo = SqlSummaryRepository(session)
        relation_repo = SqlRelationRepository(session)
        SqlDocumentNodeRepository(session)

        # 1. Seed collection, doc, chunks, propositions, summaries, etc.
        doc = Document(
            id=new_id(),
            collection_id="col1",
            title="Reprocess Doc",
            source_path="reprocess.txt",
            checksum="chk321",
            mime_type="text/plain",
        )
        doc.status = DocumentStatus.FAILED
        await doc_repo.create(doc)

        chunk = Chunk(
            id=new_id(),
            document_id=doc.id,
            text="Old chunk text",
            summary="Old summary",
            node_ids=["n1"],
            token_count=3,
        )
        await chunk_repo.create_many([chunk])

        prop = Proposition(
            id=new_id(),
            document_id=doc.id,
            source_chunk_id=chunk.id,
            text="Old prop",
        )
        await proposition_repo.create_many([prop])

        document_summary = SummaryNode(
            id=new_id(),
            scope_type="document",
            scope_id=doc.id,
            text="Old doc summary",
        )
        section_summary = SummaryNode(
            id=new_id(),
            scope_type="section",
            scope_id=chunk.id,
            text="Old section summary",
        )
        collection_summary = SummaryNode(
            id=new_id(),
            scope_type="collection",
            scope_id=doc.collection_id,
            text="Old collection summary",
        )
        await summary_repo.create_many(
            [document_summary, section_summary, collection_summary]
        )

        rel = RelationEdge(
            id=new_id(),
            source_type="proposition",
            source_id=prop.id,
            target_type="proposition",
            target_id="other_prop",
            relation="mentions",
        )
        await relation_repo.create_many([rel])

        inbound_rel = RelationEdge(
            id=new_id(),
            source_type="proposition",
            source_id="other_prop",
            target_type="proposition",
            target_id=prop.id,
            relation="supports",
        )
        await relation_repo.create_many([inbound_rel])

        visual_id = new_id()
        other_visual_id = new_id()
        visual_cache = mock_settings.visual_pages_path / "col1.json"
        visual_cache.write_text(
            "["
            f'{{"id":"{visual_id}","document_id":"{doc.id}"}},'
            f'{{"id":"{other_visual_id}","document_id":"other-doc"}}'
            "]",
            encoding="utf-8",
        )
        visual_asset_dir = mock_settings.visual_pages_path / doc.id
        visual_asset_dir.mkdir()
        (visual_asset_dir / "page-1.png").write_bytes(b"generated")

        profile_id = new_id()
        session.add(
            QuantizationProfileModel(
                id=profile_id,
                embedding_model="test-embedding",
                dimension=4,
            )
        )
        indexed_ids = [
            (chunk.id, "chunk"),
            (prop.id, "proposition"),
            (document_summary.id, "summary"),
            (section_summary.id, "summary"),
            (collection_summary.id, "summary"),
            (visual_id, "visual"),
        ]
        for position, (node_id, memory_layer) in enumerate(indexed_ids, start=1):
            session.add(
                QuantizedVectorModel(
                    id=new_id(),
                    node_id=node_id,
                    uint64_id=position,
                    collection_id=doc.collection_id,
                    memory_layer=memory_layer,
                    profile_id=profile_id,
                    idx_blob=b"idx",
                    qjl_blob=b"qjl",
                )
            )

        await session.commit()

        # Let's verify they exist
        assert len(await chunk_repo.get_by_document(doc.id)) == 1
        assert len(await proposition_repo.list_by_document(doc.id)) == 1

        # 2. Run the handler (ParseDocumentJobHandler)
        # Mock parser to raise ValueError so it fails AFTER cleanup, so we can verify the clean slate worked
        mock_parser.parse = AsyncMock(side_effect=ValueError("Force fail after cleanup"))

        handler = ParseDocumentJobHandler(session_factory)
        job = Job(id=new_id(), job_type=JobType.PARSE_DOCUMENT, target_id=doc.id)

        with pytest.raises(ValueError, match="Force fail after cleanup"):
            await handler.execute(job)

        # 3. Verify clean slate deletes everything in DB
        async with session_factory() as session_check:
            c_repo = SqlChunkRepository(session_check)
            p_repo = SqlPropositionRepository(session_check)
            s_repo = SqlSummaryRepository(session_check)
            r_repo = SqlRelationRepository(session_check)

            assert len(await c_repo.get_by_document(doc.id)) == 0
            assert len(await p_repo.list_by_document(doc.id)) == 0
            # Also check summaries and relations
            doc_sum = await s_repo.list_by_scope("document", doc.id)
            assert len(doc_sum) == 0
            assert await s_repo.list_by_scope("section", chunk.id) == []
            assert await s_repo.list_by_scope("collection", doc.collection_id) == []
            relations = await r_repo.list_by_source_ids([prop.id])
            assert len(relations) == 0
            assert await r_repo.list_by_source_ids(["other_prop"]) == []
            quantized_count = (
                await session_check.execute(
                    select(func.count())
                    .select_from(QuantizedVectorModel)
                    .where(QuantizedVectorModel.collection_id == doc.collection_id)
                )
            ).scalar_one()
            assert quantized_count == 0

            # Every vector namespace is cleaned by stable ID plus legacy filters.
            mock_qdrant.delete_points.assert_any_call(
                "collection_col1", (chunk.id,)
            )
            mock_qdrant.delete_points.assert_any_call(
                "collection_col1_propositions", (prop.id,)
            )
            summary_ids = {document_summary.id, section_summary.id, collection_summary.id}
            summary_point_call = next(
                call
                for call in mock_qdrant.delete_points.await_args_list
                if call.args[0] == "collection_col1_summaries"
            )
            assert set(summary_point_call.args[1]) == summary_ids
            mock_qdrant.delete_points.assert_any_call("pages_visual", (visual_id,))
            mock_qdrant.delete_by_filter.assert_any_call("collection_col1", {"document_id": doc.id})
            mock_qdrant.delete_by_filter.assert_any_call(
                "collection_col1_propositions", {"document_id": doc.id}
            )
            mock_qdrant.delete_by_filter.assert_any_call("pages_visual", {"document_id": doc.id})

            # Candidate cleanup spans chunk/proposition/summary/visual layers.
            candidate_call = mock_candidate_index.remove_vectors.await_args
            assert candidate_call is not None
            assert candidate_call.args[0] == "col1"
            assert set(candidate_call.args[1]) == {
                chunk.id,
                prop.id,
                *summary_ids,
                visual_id,
            }

            remaining_visual = visual_cache.read_text(encoding="utf-8")
            assert visual_id not in remaining_visual
            assert other_visual_id in remaining_visual
            assert not visual_asset_dir.exists()


@pytest.mark.asyncio
async def test_resume_endpoint_requeues_failed_documents(session_factory) -> None:
    async with session_factory() as session:
        from atenex_nova.infrastructure.db.repositories.sql_collection_repo import (
            SqlCollectionRepository,
        )
        coll_repo = SqlCollectionRepository(session)
        coll = Collection(id="col1", name="Test Collection", description="test")
        await coll_repo.create(coll)

        doc_repo = SqlDocumentRepository(session)
        job_repo = SqlJobRepository(session)
        doc_service = DocumentService(doc_repo=doc_repo, job_repo=job_repo)
        collection_service = CollectionService(repo=None)
        collection_service.get = AsyncMock(return_value=coll)

        # Document 1: FAILED, no active jobs -> should be requeued
        doc1 = Document(
            id=new_id(),
            collection_id="col1",
            title="Failed doc",
            source_path="failed.txt",
            checksum="chk1",
            mime_type="text/plain",
        )
        doc1.status = DocumentStatus.FAILED
        doc1.error_message = "error info"
        await doc_repo.create(doc1)

        # Document 2: legacy READY without persisted layers -> must be repaired
        doc2 = Document(
            id=new_id(),
            collection_id="col1",
            title="Ready doc",
            source_path="ready.txt",
            checksum="chk2",
            mime_type="text/plain",
        )
        doc2.status = DocumentStatus.READY
        await doc_repo.create(doc2)

        # Document 3: REGISTERED but has an active job -> should not be touched
        doc3 = Document(
            id=new_id(),
            collection_id="col1",
            title="Active doc",
            source_path="active.txt",
            checksum="chk3",
            mime_type="text/plain",
        )
        doc3.status = DocumentStatus.REGISTERED
        await doc_repo.create(doc3)

        active_job = Job(id=new_id(), job_type=JobType.PARSE_DOCUMENT, target_id=doc3.id)
        active_job.status = JobStatus.RUNNING
        await job_repo.create(active_job)

        await session.commit()

        # Call the endpoint handler function directly
        result = await resume_collection_ingestion(
            collection_id="col1",
            session=session,
            collection_service=collection_service,
            doc_service=doc_service,
        )

        assert result == {"requeued_count": 2}

        # Check Document 1 status in database
        updated_doc1 = await doc_repo.get_by_id(doc1.id)
        assert updated_doc1 is not None
        assert updated_doc1.status == DocumentStatus.REGISTERED
        assert updated_doc1.error_message is None

        # Check job queue for Document 1
        jobs = await job_repo.list_by_target(doc1.id)
        assert len(jobs) == 1
        assert jobs[0].job_type == JobType.PARSE_DOCUMENT
        assert jobs[0].status == JobStatus.PENDING

        updated_doc2 = await doc_repo.get_by_id(doc2.id)
        assert updated_doc2 is not None
        assert updated_doc2.status == DocumentStatus.REGISTERED
        ready_repair_jobs = await job_repo.list_by_target(doc2.id)
        assert len(ready_repair_jobs) == 1
        assert ready_repair_jobs[0].job_type == JobType.PARSE_DOCUMENT

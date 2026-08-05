"""Symmetric vector/index cleanup for a collection rebuild."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.entities.document_node import DocumentNode
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.entities.proposition import Proposition
from atenex_nova.domain.entities.relation_edge import RelationEdge
from atenex_nova.domain.entities.summary_node import SummaryNode
from atenex_nova.domain.value_objects.identifiers import (
    DocumentStatus,
    JobType,
    NodeType,
    new_id,
)
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import (
    SqlCollectionRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_document_repo import (
    SqlDocumentRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.repositories.sql_node_repo import (
    SqlDocumentNodeRepository,
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
from atenex_nova.shared.config.settings import Settings
from atenex_nova.workers.jobs.mem_builder_job import RebuildCollectionJobHandler


@pytest.fixture()
async def session_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rebuild-cleanup.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed(factory, visual_root: Path) -> tuple[str, str, str]:
    async with factory() as session:
        collection_id = new_id()
        document_id = new_id()
        chunk_id = new_id()
        proposition_id = new_id()

        await SqlCollectionRepository(session).create(
            Collection(id=collection_id, name="Rebuild", description="cleanup")
        )
        document = Document(
            id=document_id,
            collection_id=collection_id,
            title="Source",
            source_path="/tmp/source.md",
            mime_type="text/markdown",
            checksum="source-checksum",
            status=DocumentStatus.READY,
        )
        await SqlDocumentRepository(session).create(document)
        await SqlDocumentNodeRepository(session).create_many(
            [
                DocumentNode(
                    id=new_id(),
                    document_id=document_id,
                    node_type=NodeType.PARAGRAPH,
                    raw_text="old node",
                    normalized_text="old node",
                )
            ]
        )
        await SqlChunkRepository(session).create_many(
            [
                Chunk(
                    id=chunk_id,
                    document_id=document_id,
                    text="old chunk",
                    summary="old",
                    token_count=2,
                    node_ids=[],
                )
            ]
        )
        await SqlPropositionRepository(session).create_many(
            [
                Proposition(
                    id=proposition_id,
                    document_id=document_id,
                    source_chunk_id=chunk_id,
                    text="old proposition",
                )
            ]
        )
        await SqlSummaryRepository(session).create_many(
            [
                SummaryNode(
                    id=new_id(),
                    scope_type="section",
                    scope_id=chunk_id,
                    text="section",
                ),
                SummaryNode(
                    id=new_id(),
                    scope_type="document",
                    scope_id=document_id,
                    text="document",
                ),
                SummaryNode(
                    id=new_id(),
                    scope_type="collection",
                    scope_id=collection_id,
                    text="collection",
                ),
            ]
        )
        await SqlRelationRepository(session).create_many(
            [
                RelationEdge(
                    id=new_id(),
                    source_type="proposition",
                    source_id="external",
                    target_type="proposition",
                    target_id=proposition_id,
                    relation="supports",
                )
            ]
        )
        await session.commit()

    visual_root.mkdir(parents=True, exist_ok=True)
    visual_id = new_id()
    (visual_root / f"{collection_id}.json").write_text(
        json.dumps(
            [
                {
                    "id": visual_id,
                    "collection_id": collection_id,
                    "document_id": document_id,
                }
            ]
        ),
        encoding="utf-8",
    )
    asset_dir = visual_root / document_id
    asset_dir.mkdir()
    (asset_dir / "page-1.png").write_bytes(b"generated")
    return collection_id, document_id, visual_id


@pytest.mark.asyncio
async def test_rebuild_cleans_every_namespace_before_requeue_and_is_idempotent(
    session_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visual_root = tmp_path / "visual"
    settings = Settings(
        visual_pages_path=visual_root,
        candidate_backend="purepy",
        require_qdrant=False,
    )
    collection_id, document_id, visual_id = await _seed(session_factory, visual_root)

    candidate = MagicMock()
    candidate.delete_collection_indexes = AsyncMock()
    qdrant = MagicMock()
    qdrant.delete_collection = AsyncMock()
    qdrant.delete_points = AsyncMock()
    qdrant.delete_by_filter = AsyncMock()
    qdrant.is_available = True
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.candidate_index_factory.build_candidate_index",
        lambda session: candidate,
    )
    monkeypatch.setattr(
        "atenex_nova.workers.jobs.ingestion_job._build_qdrant_adapter",
        lambda: qdrant,
    )
    monkeypatch.setattr(
        "atenex_nova.workers.jobs.mem_builder_job.get_settings",
        lambda: settings,
    )

    rebuild_job = Job(
        id=new_id(),
        job_type=JobType.REBUILD_COLLECTION,
        target_id=collection_id,
    )
    handler = RebuildCollectionJobHandler(session_factory)
    first = await handler.execute(rebuild_job)
    second = await handler.execute(rebuild_job)

    assert first == {
        "documents_requeued": 1,
        "qdrant_cleanup_complete": True,
    }
    assert second == first
    expected_namespaces = {
        f"collection_{collection_id}",
        f"collection_{collection_id}_propositions",
        f"collection_{collection_id}_summaries",
    }
    assert {
        call.args[0] for call in qdrant.delete_collection.await_args_list
    } == expected_namespaces
    qdrant.delete_points.assert_any_call("pages_visual", [visual_id])
    qdrant.delete_by_filter.assert_any_call(
        "pages_visual",
        {"collection_id": collection_id},
    )
    assert candidate.delete_collection_indexes.await_count == 2

    async with session_factory() as session:
        document = await SqlDocumentRepository(session).get_by_id(document_id)
        assert document is not None
        assert document.status == DocumentStatus.REGISTERED
        assert await SqlChunkRepository(session).get_by_document(document_id) == []
        assert await SqlPropositionRepository(session).list_by_document(document_id) == []
        assert await SqlSummaryRepository(session).list_ids_for_collection_cleanup(
            collection_id
        ) == []
        assert await SqlRelationRepository(session).list_by_source_ids(["external"]) == []
        jobs = await SqlJobRepository(session).list_by_target(document_id)
        parse_jobs = [item for item in jobs if item.job_type == JobType.PARSE_DOCUMENT]
        assert len(parse_jobs) == 1

    assert not (visual_root / f"{collection_id}.json").exists()
    assert not (visual_root / document_id).exists()

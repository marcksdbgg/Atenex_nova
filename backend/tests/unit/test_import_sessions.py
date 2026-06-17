"""Unit tests for durable import sessions (SA-5)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.application.services.document_service import DocumentService
from atenex_nova.application.services.import_session_service import ImportSessionService
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository


@pytest.fixture
async def session_factory(tmp_path):
    db_path = tmp_path / "import_sessions.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_import_local_folder_tracks_deduplicated_and_created(session_factory, tmp_path) -> None:
    folder = tmp_path / "corpus"
    folder.mkdir()
    (folder / "a.txt").write_text("alpha", encoding="utf-8")
    (folder / "b.txt").write_text("beta", encoding="utf-8")
    (folder / "dup.txt").write_text("alpha", encoding="utf-8")

    async with session_factory() as session:
        collection_repo = SqlCollectionRepository(session)
        collection_id = new_id()
        await collection_repo.create(Collection(id=collection_id, name="Test"))

        doc_service = DocumentService(SqlDocumentRepository(session), SqlJobRepository(session))
        import_service = ImportSessionService(session, doc_service)

        import_session, documents = await import_service.import_local_folder(
            collection_id=collection_id,
            source_folder=str(folder),
        )
        await session.commit()

        assert import_session.discovered_count == 3
        assert import_session.attempted_count == 3
        assert import_session.created_count == 2
        assert import_session.deduplicated_count == 1
        assert import_session.failed_count == 0
        assert import_session.status == "completed"
        assert len(documents) == 2

        items = await import_service.list_items(import_session.id, limit=10)
        assert len(items) == 3
        assert sum(1 for item in items if item.status == "created") == 2
        assert sum(1 for item in items if item.status == "deduplicated") == 1


@pytest.mark.asyncio
async def test_upload_batch_session_auto_finalizes(session_factory) -> None:
    async with session_factory() as session:
        collection_repo = SqlCollectionRepository(session)
        collection_id = new_id()
        await collection_repo.create(Collection(id=collection_id, name="Upload batch"))

        doc_service = DocumentService(SqlDocumentRepository(session), SqlJobRepository(session))
        import_service = ImportSessionService(session, doc_service)
        import_session = await import_service.start_session(
            collection_id=collection_id,
            source_kind="upload_batch",
            discovered_count=2,
        )

        doc_one = await doc_service.register(
            collection_id=collection_id,
            title="one.txt",
            source_path="/tmp/one.txt",
            mime_type="text/plain",
            checksum="abc123",
        )
        await import_service.record_upload_item(
            import_session.id,
            relative_path="one.txt",
            source_path="/tmp/one.txt",
            checksum="abc123",
            mime_type="text/plain",
            document=doc_one,
            deduplicated=False,
        )

        doc_two = await doc_service.register(
            collection_id=collection_id,
            title="one.txt",
            source_path="/tmp/one.txt",
            mime_type="text/plain",
            checksum="abc123",
        )
        await import_service.record_upload_item(
            import_session.id,
            relative_path="one.txt",
            source_path="/tmp/one.txt",
            checksum="abc123",
            mime_type="text/plain",
            document=doc_two,
            deduplicated=True,
        )
        await session.commit()

        finalized = await import_service.get_session(import_session.id)
        assert finalized is not None
        assert finalized.status == "completed"
        assert finalized.attempted_count == 2
        assert finalized.created_count == 1
        assert finalized.deduplicated_count == 1

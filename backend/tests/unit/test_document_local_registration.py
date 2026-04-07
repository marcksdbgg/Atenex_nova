"""Unit tests for local document registration."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.application.services.document_service import DocumentService
from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository


@pytest.fixture()
async def session_factory(tmp_path: Path):
    db_path = tmp_path / "document-service.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_register_local_document_references_existing_file(session_factory, tmp_path: Path) -> None:
    source = tmp_path / "reference.txt"
    source.write_text("local reference", encoding="utf-8")

    async with session_factory() as session:
        service = DocumentService(SqlDocumentRepository(session), SqlJobRepository(session))
        document = await service.register_local(collection_id=new_id(), source_path=str(source))
        await session.commit()

        assert document.source_path == str(source.resolve())
        assert document.title == source.name
        assert document.mime_type == "text/plain"
        assert document.checksum == hashlib.sha256(source.read_bytes()).hexdigest()

        jobs = await SqlJobRepository(session).list_all()
        assert len(jobs) == 1
        assert jobs[0].target_id == document.id


@pytest.mark.asyncio
async def test_register_local_document_rejects_missing_file(session_factory, tmp_path: Path) -> None:
    missing = tmp_path / "missing.txt"

    async with session_factory() as session:
        service = DocumentService(SqlDocumentRepository(session), SqlJobRepository(session))

        with pytest.raises(ValueError, match="Source file not found"):
            await service.register_local(collection_id=new_id(), source_path=str(missing))


@pytest.mark.asyncio
async def test_register_local_document_deduplicates_by_checksum(session_factory, tmp_path: Path) -> None:
    source_a = tmp_path / "a.txt"
    source_b = tmp_path / "folder" / "b.txt"
    source_b.parent.mkdir(parents=True, exist_ok=True)

    payload = "same-content"
    source_a.write_text(payload, encoding="utf-8")
    source_b.write_text(payload, encoding="utf-8")

    collection_id = new_id()

    async with session_factory() as session:
        service = DocumentService(SqlDocumentRepository(session), SqlJobRepository(session))
        first = await service.register_local(collection_id=collection_id, source_path=str(source_a))
        second = await service.register_local(collection_id=collection_id, source_path=str(source_b))
        await session.commit()

        assert second.id == first.id

        docs = await SqlDocumentRepository(session).list_by_collection(collection_id)
        assert len(docs) == 1

        jobs = await SqlJobRepository(session).list_all()
        assert len(jobs) == 1


@pytest.mark.asyncio
async def test_register_local_folder_registers_nested_files(session_factory, tmp_path: Path) -> None:
    source_folder = tmp_path / "source-folder"
    (source_folder / "uno").mkdir(parents=True, exist_ok=True)
    (source_folder / "dos").mkdir(parents=True, exist_ok=True)
    file_a = source_folder / "uno" / "a.txt"
    file_b = source_folder / "dos" / "b.md"
    file_a.write_text("contenido a", encoding="utf-8")
    file_b.write_text("contenido b", encoding="utf-8")

    async with session_factory() as session:
        service = DocumentService(SqlDocumentRepository(session), SqlJobRepository(session))
        documents = await service.register_local_folder(
            collection_id=new_id(),
            source_folder=str(source_folder),
            collection_path="carpeta-base",
            recursive=True,
        )
        await session.commit()

        assert len(documents) == 2
        collection_paths = {document.collection_path for document in documents}
        assert "carpeta-base/uno/a.txt" in collection_paths
        assert "carpeta-base/dos/b.md" in collection_paths

        jobs = await SqlJobRepository(session).list_all()
        assert len(jobs) == 2

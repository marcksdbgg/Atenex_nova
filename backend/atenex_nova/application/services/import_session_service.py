"""Application service: durable import sessions."""

from __future__ import annotations

import mimetypes

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.application.services.document_service import DocumentService
from atenex_nova.domain.entities.document import Document
from atenex_nova.infrastructure.db.repositories.sql_import_session_repo import (
    ImportSessionItemRecord,
    ImportSessionRecord,
    SqlImportSessionRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository


class ImportSessionService:
    def __init__(
        self,
        session: AsyncSession,
        doc_service: DocumentService,
    ) -> None:
        self._session = session
        self._doc_service = doc_service
        self._repo = SqlImportSessionRepository(session)
        self._job_repo = SqlJobRepository(session)

    async def start_session(
        self,
        collection_id: str,
        source_kind: str,
        *,
        source_root: str = "",
        collection_path: str = "",
        discovered_count: int = 0,
    ) -> ImportSessionRecord:
        return await self._repo.create_session(
            collection_id=collection_id,
            source_kind=source_kind,
            source_root=source_root,
            collection_path=collection_path,
            discovered_count=discovered_count,
        )

    async def get_session(self, session_id: str) -> ImportSessionRecord | None:
        return await self._repo.get_session(session_id)

    async def list_by_collection(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 20,
    ) -> list[ImportSessionRecord]:
        return await self._repo.list_by_collection(collection_id, offset=offset, limit=limit)

    async def list_items(
        self,
        session_id: str,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> list[ImportSessionItemRecord]:
        return await self._repo.list_items(session_id, offset=offset, limit=limit, status=status)

    async def record_upload_item(
        self,
        session_id: str,
        *,
        relative_path: str,
        source_path: str,
        checksum: str,
        mime_type: str,
        document: Document | None,
        deduplicated: bool,
        error: str | None = None,
    ) -> ImportSessionItemRecord:
        if error:
            status = "failed"
            counters = {"attempted": 1, "failed": 1}
        elif deduplicated:
            status = "deduplicated"
            counters = {"attempted": 1, "deduplicated": 1}
        else:
            status = "created"
            counters = {"attempted": 1, "created": 1, "queued_jobs": 1 if document else 0}

        item = await self._repo.add_item(
            session_id,
            relative_path=relative_path,
            source_path=source_path,
            checksum=checksum,
            mime_type=mime_type,
            status=status,
            document_id=document.id if document else None,
            error=error,
        )
        await self._repo.increment_counters(session_id, **counters)
        await self._maybe_auto_finalize(session_id)
        return item

    async def import_local_folder(
        self,
        collection_id: str,
        source_folder: str,
        collection_path: str = "",
        recursive: bool = True,
    ) -> tuple[ImportSessionRecord, list[Document]]:
        resolved_folder = DocumentService._resolve_source_path(source_folder)
        if not resolved_folder.exists() or not resolved_folder.is_dir():
            raise ValueError(f"Source folder not found: {source_folder}")

        iterator = resolved_folder.rglob("*") if recursive else resolved_folder.glob("*")
        files = sorted(path for path in iterator if path.is_file())
        if not files:
            raise ValueError(f"Source folder has no files: {source_folder}")

        base_collection_path = DocumentService._normalize_collection_path(collection_path)
        import_session = await self._repo.create_session(
            collection_id=collection_id,
            source_kind="local_folder",
            source_root=str(resolved_folder),
            collection_path=base_collection_path,
            discovered_count=len(files),
        )

        documents: list[Document] = []
        for file_path in files:
            relative_file_path = file_path.relative_to(resolved_folder).as_posix()
            target_collection_path = DocumentService._join_collection_paths(
                base_collection_path,
                relative_file_path,
            )
            mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            checksum = DocumentService._checksum_file(file_path)
            try:
                existing = await self._doc_service.find_by_collection_checksum(collection_id, checksum)
                if existing is not None:
                    doc = existing
                    await self._repo.add_item(
                        import_session.id,
                        relative_path=relative_file_path,
                        source_path=str(file_path),
                        checksum=checksum,
                        mime_type=mime_type,
                        status="deduplicated",
                        document_id=doc.id,
                    )
                    await self._repo.increment_counters(
                        import_session.id,
                        attempted=1,
                        deduplicated=1,
                    )
                else:
                    doc = await self._doc_service.register_local(
                        collection_id=collection_id,
                        source_path=str(file_path),
                        title=target_collection_path or file_path.name,
                        collection_path=target_collection_path,
                    )
                    jobs = await self._job_repo.list_by_target(doc.id, limit=1)
                    await self._repo.add_item(
                        import_session.id,
                        relative_path=relative_file_path,
                        source_path=str(file_path),
                        checksum=checksum,
                        mime_type=mime_type,
                        status="created",
                        document_id=doc.id,
                        job_id=jobs[0].id if jobs else None,
                    )
                    await self._repo.increment_counters(
                        import_session.id,
                        attempted=1,
                        created=1,
                        queued_jobs=1,
                    )
                    documents.append(doc)
            except Exception as exc:
                await self._repo.add_item(
                    import_session.id,
                    relative_path=relative_file_path,
                    source_path=str(file_path),
                    checksum=checksum,
                    mime_type=mime_type,
                    status="failed",
                    error=str(exc),
                )
                await self._repo.increment_counters(
                    import_session.id,
                    attempted=1,
                    failed=1,
                )

        finalized = await self._repo.finalize_session(import_session.id)
        assert finalized is not None
        return finalized, documents

    async def finalize_session(self, session_id: str) -> ImportSessionRecord | None:
        return await self._repo.finalize_session(session_id)

    async def _maybe_auto_finalize(self, session_id: str) -> None:
        session = await self._repo.get_session(session_id)
        if session is None or session.status != "running":
            return
        if session.discovered_count > 0 and session.attempted_count >= session.discovered_count:
            await self._repo.finalize_session(session_id)

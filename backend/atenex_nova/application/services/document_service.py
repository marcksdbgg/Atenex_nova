"""Application service: Document management."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.value_objects.identifiers import DocumentStatus, JobType, new_id
from atenex_nova.shared.config.settings import PROJECT_ROOT
from atenex_nova.shared.exceptions.base import EntityNotFoundError


class DocumentService:
    def __init__(self, doc_repo, job_repo) -> None:
        self._doc_repo = doc_repo
        self._job_repo = job_repo

    async def register(
        self,
        collection_id: str,
        title: str,
        source_path: str,
        mime_type: str,
        checksum: str,
        doc_id: str | None = None,
    ) -> Document:
        doc = Document(
            id=doc_id or new_id(),
            collection_id=collection_id,
            title=title,
            source_path=source_path,
            mime_type=mime_type,
            checksum=checksum,
        )
        await self._doc_repo.create(doc)
        job = Job(id=new_id(), job_type=JobType.PARSE_DOCUMENT, target_id=doc.id)
        await self._job_repo.create(job)
        return doc

    async def register_local(
        self,
        collection_id: str,
        source_path: str,
        title: str | None = None,
        mime_type: str | None = None,
        doc_id: str | None = None,
    ) -> Document:
        resolved_path = self._resolve_source_path(source_path)
        if not resolved_path.exists() or not resolved_path.is_file():
            raise ValueError(f"Source file not found: {source_path}")

        checksum = self._checksum_file(resolved_path)
        resolved_title = title or resolved_path.name
        resolved_mime = mime_type or mimetypes.guess_type(resolved_path.name)[0] or "application/octet-stream"
        return await self.register(
            collection_id=collection_id,
            title=resolved_title,
            source_path=str(resolved_path),
            mime_type=resolved_mime,
            checksum=checksum,
            doc_id=doc_id,
        )

    async def get(self, document_id: str) -> Document:
        doc = await self._doc_repo.get_by_id(document_id)
        if not doc:
            raise EntityNotFoundError("Document", document_id)
        return doc

    async def list_by_collection(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 50,
        status: DocumentStatus | None = None,
    ) -> list[Document]:
        return await self._doc_repo.list_by_collection(collection_id, offset, limit, status)

    async def delete(self, document_id: str) -> bool:
        return await self._doc_repo.delete(document_id)

    @staticmethod
    def _resolve_source_path(source_path: str) -> Path:
        candidate = Path(source_path).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()
        return (PROJECT_ROOT / candidate).resolve()

    @staticmethod
    def _checksum_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

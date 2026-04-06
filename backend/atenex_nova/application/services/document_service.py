"""Application service: Document management."""
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.value_objects.identifiers import DocumentStatus, JobType, new_id
from atenex_nova.shared.exceptions.base import EntityNotFoundError


class DocumentService:
    def __init__(self, doc_repo, job_repo) -> None:
        self._doc_repo = doc_repo
        self._job_repo = job_repo

    async def register(self, collection_id: str, title: str, source_path: str,
                       mime_type: str, checksum: str) -> Document:
        doc = Document(
            id=new_id(), collection_id=collection_id, title=title,
            source_path=source_path, mime_type=mime_type, checksum=checksum,
        )
        await self._doc_repo.create(doc)
        job = Job(id=new_id(), job_type=JobType.PARSE_DOCUMENT, target_id=doc.id)
        await self._job_repo.create(job)
        return doc

    async def get(self, document_id: str) -> Document:
        doc = await self._doc_repo.get_by_id(document_id)
        if not doc:
            raise EntityNotFoundError("Document", document_id)
        return doc

    async def list_by_collection(self, collection_id: str, offset: int = 0,
                                  limit: int = 50, status: DocumentStatus | None = None) -> list[Document]:
        return await self._doc_repo.list_by_collection(collection_id, offset, limit, status)

    async def delete(self, document_id: str) -> bool:
        return await self._doc_repo.delete(document_id)

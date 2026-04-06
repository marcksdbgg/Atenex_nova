"""SQL repository: Document."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.value_objects.identifiers import DocumentStatus
from atenex_nova.infrastructure.db.models.tables import DocumentModel


class SqlDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, doc: Document) -> Document:
        m = DocumentModel(
            id=doc.id,
            collection_id=doc.collection_id,
            title=doc.title,
            source_path=doc.source_path,
            mime_type=doc.mime_type,
            checksum=doc.checksum,
            status=doc.status.value,
            language=doc.language,
            version=doc.version,
            error_message=doc.error_message,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )
        self._session.add(m)
        await self._session.flush()
        return doc

    async def get_by_id(self, document_id: str) -> Document | None:
        r = await self._session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
        model = r.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_by_collection(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 50,
        status: DocumentStatus | None = None,
    ) -> list[Document]:
        stmt = select(DocumentModel).where(DocumentModel.collection_id == collection_id)
        if status:
            stmt = stmt.where(DocumentModel.status == status.value)
        stmt = stmt.offset(offset).limit(limit)
        r = await self._session.execute(stmt)
        return [self._to_entity(m) for m in r.scalars().all()]

    async def update(self, doc: Document) -> Document:
        r = await self._session.execute(select(DocumentModel).where(DocumentModel.id == doc.id))
        model = r.scalar_one_or_none()
        if model:
            model.status = doc.status.value
            model.language = doc.language
            model.error_message = doc.error_message
            model.updated_at = doc.updated_at
            await self._session.flush()
        return doc

    async def delete(self, document_id: str) -> bool:
        r = await self._session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
        model = r.scalar_one_or_none()
        if not model:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True

    async def count_by_collection(self, cid: str) -> int:
        r = await self._session.execute(
            select(func.count())
            .select_from(DocumentModel)
            .where(DocumentModel.collection_id == cid)
        )
        return r.scalar_one()

    @staticmethod
    def _to_entity(m: DocumentModel) -> Document:
        return Document(
            id=m.id,
            collection_id=m.collection_id,
            title=m.title,
            source_path=m.source_path,
            mime_type=m.mime_type,
            checksum=m.checksum,
            status=DocumentStatus(m.status),
            language=m.language,
            version=m.version,
            error_message=m.error_message,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

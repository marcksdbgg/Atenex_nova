"""SQL implementation of Chunk repository."""
import json

from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.infrastructure.db.models.tables import ChunkModel, DocumentModel


class SqlChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _to_entity(self, model: ChunkModel) -> Chunk:
        return Chunk(
            id=model.id,
            document_id=model.document_id,
            text=model.text,
            summary=model.summary,
            token_count=model.token_count,
            node_ids=json.loads(model.node_ids_json),
            embedding_ref=model.embedding_ref,
            sparse_ref=model.sparse_ref,
            metadata=json.loads(model.metadata_json) if model.metadata_json else {},
        )

    async def create(self, chunk: Chunk) -> None:
        model = ChunkModel(**chunk.to_dict())
        self.session.add(model)
        await self.session.commit()

    async def create_many(self, chunks: list[Chunk]) -> None:
        models = [ChunkModel(**c.to_dict()) for c in chunks]
        self.session.add_all(models)
        await self.session.commit()

    async def update(self, chunk: Chunk) -> None:
        stmt = select(ChunkModel).where(ChunkModel.id == chunk.id)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if model:
            d = chunk.to_dict()
            for k, v in d.items():
                setattr(model, k, v)
        await self.session.commit()

    async def get_by_document(self, document_id: str) -> list[Chunk]:
        stmt = select(ChunkModel).where(ChunkModel.document_id == document_id)
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_by_collection(self, collection_id: str) -> list[Chunk]:
        stmt = (
            select(ChunkModel)
            .join(DocumentModel, DocumentModel.id == ChunkModel.document_id)
            .where(DocumentModel.collection_id == collection_id)
        )
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def delete_by_document(self, document_id: str) -> bool:
        stmt = delete(ChunkModel).where(ChunkModel.document_id == document_id)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

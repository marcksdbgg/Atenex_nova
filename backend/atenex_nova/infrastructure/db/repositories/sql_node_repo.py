"""SQL implementation of DocumentNode repository."""
import json

from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from atenex_nova.domain.entities.document_node import DocumentNode
from atenex_nova.domain.value_objects.identifiers import NodeType
from atenex_nova.infrastructure.db.models.tables import DocumentNodeModel


class SqlDocumentNodeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _to_entity(self, model: DocumentNodeModel) -> DocumentNode:
        return DocumentNode(
            id=model.id,
            document_id=model.document_id,
            node_type=NodeType(model.node_type),
            raw_text=model.raw_text,
            normalized_text=model.normalized_text,
            parent_id=model.parent_id,
            page_number=model.page_number,
            order_index=model.order_index,
            bbox=json.loads(model.bbox_json) if model.bbox_json else None,
            metadata=json.loads(model.metadata_json) if model.metadata_json else {},
        )

    async def create(self, node: DocumentNode) -> None:
        model = DocumentNodeModel(**node.to_dict())
        self.session.add(model)
        await self.session.commit()

    async def create_many(self, nodes: list[DocumentNode]) -> None:
        models = [DocumentNodeModel(**n.to_dict()) for n in nodes]
        self.session.add_all(models)
        await self.session.commit()

    async def get_by_document(self, document_id: str) -> list[DocumentNode]:
        stmt = select(DocumentNodeModel).where(DocumentNodeModel.document_id == document_id).order_by(DocumentNodeModel.order_index)
        result = await self.session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def delete_by_document(self, document_id: str) -> bool:
        stmt = delete(DocumentNodeModel).where(DocumentNodeModel.document_id == document_id)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

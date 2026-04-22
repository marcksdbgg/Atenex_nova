"""SQL repository: SummaryNode."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.entities.summary_node import SummaryNode
from atenex_nova.infrastructure.db.models.tables import SummaryNodeModel


class SqlSummaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(self, summaries: list[SummaryNode]) -> list[SummaryNode]:
        models = [
            SummaryNodeModel(
                id=item.id,
                scope_type=item.scope_type,
                scope_id=item.scope_id,
                text=item.text,
                embedding_ref=item.embedding_ref,
            )
            for item in summaries
        ]
        self._session.add_all(models)
        await self._session.flush()
        return summaries

    async def list_by_scope(self, scope_type: str, scope_id: str) -> list[SummaryNode]:
        result = await self._session.execute(
            select(SummaryNodeModel).where(
                SummaryNodeModel.scope_type == scope_type,
                SummaryNodeModel.scope_id == scope_id,
            )
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_collection(self, collection_id: str) -> list[SummaryNode]:
        result = await self._session.execute(
            select(SummaryNodeModel).where(
                SummaryNodeModel.scope_type == "collection",
                SummaryNodeModel.scope_id == collection_id,
            )
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_document(self, document_id: str) -> list[SummaryNode]:
        result = await self._session.execute(
            select(SummaryNodeModel).where(
                SummaryNodeModel.scope_type.in_(["document", "section"]),
                SummaryNodeModel.scope_id == document_id,
            )
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def delete_by_scope(self, scope_type: str, scope_id: str) -> bool:
        result = await self._session.execute(
            delete(SummaryNodeModel).where(
                SummaryNodeModel.scope_type == scope_type,
                SummaryNodeModel.scope_id == scope_id,
            )
        )
        await self._session.flush()
        return result.rowcount > 0

    @staticmethod
    def _to_entity(model: SummaryNodeModel) -> SummaryNode:
        return SummaryNode(
            id=model.id,
            scope_type=model.scope_type,
            scope_id=model.scope_id,
            text=model.text,
            embedding_ref=model.embedding_ref,
        )

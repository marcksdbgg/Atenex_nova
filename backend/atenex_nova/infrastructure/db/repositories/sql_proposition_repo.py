"""SQL repository: Proposition."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.entities.proposition import Proposition
from atenex_nova.infrastructure.db.models.tables import DocumentModel, PropositionModel


class SqlPropositionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(self, propositions: list[Proposition]) -> list[Proposition]:
        models = [
            PropositionModel(
                id=prop.id,
                document_id=prop.document_id,
                source_chunk_id=prop.source_chunk_id,
                text=prop.text,
                kind=prop.kind,
                embedding_ref=prop.embedding_ref,
            )
            for prop in propositions
        ]
        self._session.add_all(models)
        await self._session.flush()
        return propositions

    async def list_by_document(self, document_id: str) -> list[Proposition]:
        result = await self._session.execute(
            select(PropositionModel).where(PropositionModel.document_id == document_id)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_collection(self, collection_id: str) -> list[Proposition]:
        result = await self._session.execute(
            select(PropositionModel)
            .join(DocumentModel, DocumentModel.id == PropositionModel.document_id)
            .where(DocumentModel.collection_id == collection_id)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def delete_by_document(self, document_id: str) -> bool:
        result = await self._session.execute(
            delete(PropositionModel).where(PropositionModel.document_id == document_id)
        )
        await self._session.flush()
        return result.rowcount > 0

    @staticmethod
    def _to_entity(model: PropositionModel) -> Proposition:
        return Proposition(
            id=model.id,
            document_id=model.document_id,
            source_chunk_id=model.source_chunk_id,
            text=model.text,
            kind=model.kind,
            embedding_ref=model.embedding_ref,
        )

"""SQL repository: Citation."""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.entities.citation import Citation
from atenex_nova.infrastructure.db.models.tables import CitationModel


class SqlCitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(self, citations: list[Citation]) -> list[Citation]:
        models = [
            CitationModel(
                id=citation.id,
                answer_id=citation.answer_id,
                document_id=citation.document_id,
                page_number=citation.page_number,
                node_id=citation.node_id,
                char_start=citation.char_start,
                char_end=citation.char_end,
                snippet=citation.snippet,
                bbox_json=json.dumps(citation.bbox) if citation.bbox else None,
                heading_path_json=json.dumps(citation.heading_path),
                page_asset_path=citation.page_asset_path,
            )
            for citation in citations
        ]
        self._session.add_all(models)
        await self._session.flush()
        return citations

    async def list_by_answer(self, answer_id: str) -> list[Citation]:
        result = await self._session.execute(
            select(CitationModel).where(CitationModel.answer_id == answer_id)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: CitationModel) -> Citation:
        return Citation(
            id=model.id,
            answer_id=model.answer_id,
            document_id=model.document_id,
            page_number=model.page_number,
            node_id=model.node_id,
            char_start=model.char_start,
            char_end=model.char_end,
            snippet=model.snippet,
            bbox=json.loads(model.bbox_json) if model.bbox_json else None,
            heading_path=json.loads(model.heading_path_json) if model.heading_path_json else [],
            page_asset_path=model.page_asset_path,
        )

"""SQL repository: Query."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.entities.query import Query
from atenex_nova.infrastructure.db.models.tables import QueryModel


class SqlQueryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, query: Query) -> Query:
        model = QueryModel(
            id=query.id,
            collection_id=query.collection_id,
            original_text=query.text,
            normalized_text=query.normalized_text,
            language=query.language,
            intent=query.intent,
            route_mode=query.route_mode,
            created_at=query.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return query

    async def get_by_id(self, query_id: str) -> Query | None:
        result = await self._session.execute(select(QueryModel).where(QueryModel.id == query_id))
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_all(self, offset: int = 0, limit: int = 50) -> list[Query]:
        result = await self._session.execute(
            select(QueryModel).offset(offset).limit(limit).order_by(QueryModel.created_at.desc())
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_collection(self, collection_id: str, offset: int = 0, limit: int = 50) -> list[Query]:
        result = await self._session.execute(
            select(QueryModel)
            .where(QueryModel.collection_id == collection_id)
            .order_by(QueryModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: QueryModel) -> Query:
        return Query(
            id=model.id,
            collection_id=model.collection_id,
            text=model.original_text,
            normalized_text=model.normalized_text,
            language=model.language,
            intent=model.intent or "factual",
            route_mode=model.route_mode or "factual_local",
            created_at=model.created_at,
        )

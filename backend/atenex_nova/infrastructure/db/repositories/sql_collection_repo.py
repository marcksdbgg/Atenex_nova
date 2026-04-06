"""SQL repository: Collection."""
import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.infrastructure.db.models.tables import CollectionModel


class SqlCollectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, collection: Collection) -> Collection:
        model = CollectionModel(
            id=collection.id, name=collection.name, description=collection.description,
            language_profile=collection.language_profile,
            default_generation_profile=collection.default_generation_profile,
            default_retrieval_profile=collection.default_retrieval_profile,
            created_at=collection.created_at, updated_at=collection.updated_at,
        )
        self._session.add(model)
        await self._session.flush()
        return collection

    async def get_by_id(self, collection_id: str) -> Collection | None:
        stmt = select(CollectionModel).where(CollectionModel.id == collection_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_all(self, offset: int = 0, limit: int = 50) -> list[Collection]:
        stmt = select(CollectionModel).offset(offset).limit(limit).order_by(CollectionModel.created_at.desc())
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def update(self, collection: Collection) -> Collection:
        stmt = select(CollectionModel).where(CollectionModel.id == collection.id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model:
            model.name = collection.name
            model.description = collection.description
            model.language_profile = collection.language_profile
            model.default_generation_profile = collection.default_generation_profile
            model.default_retrieval_profile = collection.default_retrieval_profile
            model.updated_at = collection.updated_at
            await self._session.flush()
        return collection

    async def delete(self, collection_id: str) -> bool:
        stmt = select(CollectionModel).where(CollectionModel.id == collection_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True

    @staticmethod
    def _to_entity(model: CollectionModel) -> Collection:
        return Collection(
            id=model.id, name=model.name, description=model.description,
            language_profile=model.language_profile,
            default_generation_profile=model.default_generation_profile,
            default_retrieval_profile=model.default_retrieval_profile,
            created_at=model.created_at, updated_at=model.updated_at,
        )

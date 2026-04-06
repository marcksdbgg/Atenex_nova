"""Application service: Collection management."""
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.shared.exceptions.base import EntityNotFoundError


class CollectionService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def create(self, name: str, description: str = "", language_profile: str = "auto") -> Collection:
        entity = Collection(id=new_id(), name=name, description=description, language_profile=language_profile)
        await self._repo.create(entity)
        return entity

    async def get(self, collection_id: str) -> Collection:
        entity = await self._repo.get_by_id(collection_id)
        if not entity:
            raise EntityNotFoundError("Collection", collection_id)
        return entity

    async def list_all(self, offset: int = 0, limit: int = 50) -> list[Collection]:
        return await self._repo.list_all(offset=offset, limit=limit)

    async def update(self, collection_id: str, name: str | None = None,
                     description: str | None = None, generation_profile: str | None = None,
                     retrieval_profile: str | None = None) -> Collection:
        entity = await self.get(collection_id)
        if name is not None:
            entity.rename(name)
        if description is not None:
            entity.description = description
        entity.update_profiles(generation_profile, retrieval_profile)
        await self._repo.update(entity)
        return entity

    async def delete(self, collection_id: str) -> bool:
        return await self._repo.delete(collection_id)

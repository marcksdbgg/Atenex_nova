"""Atenex Nova — Domain repository interface: CollectionRepository."""

from typing import Protocol

from atenex_nova.domain.entities.collection import Collection


class CollectionRepository(Protocol):
    """Interface for collection persistence operations."""

    async def create(self, collection: Collection) -> Collection:
        """Persist a new collection."""
        ...

    async def get_by_id(self, collection_id: str) -> Collection | None:
        """Get a collection by its ID. Returns None if not found."""
        ...

    async def list_all(self, offset: int = 0, limit: int = 50) -> list[Collection]:
        """List all collections with pagination."""
        ...

    async def update(self, collection: Collection) -> Collection:
        """Update an existing collection."""
        ...

    async def delete(self, collection_id: str) -> bool:
        """Delete a collection. Returns True if deleted, False if not found."""
        ...

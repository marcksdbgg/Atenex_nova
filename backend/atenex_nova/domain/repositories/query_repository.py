"""Query repository protocol."""

from typing import Protocol

from atenex_nova.domain.entities.query import Query


class QueryRepository(Protocol):
    async def create(self, query: Query) -> Query: ...
    async def get_by_id(self, query_id: str) -> Query | None: ...
    async def list_all(self, offset: int = 0, limit: int = 50) -> list[Query]: ...
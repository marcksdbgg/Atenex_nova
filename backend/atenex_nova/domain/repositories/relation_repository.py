"""Relation repository protocol."""

from typing import Protocol

from atenex_nova.domain.entities.relation_edge import RelationEdge


class RelationRepository(Protocol):
    async def create_many(self, edges: list[RelationEdge]) -> list[RelationEdge]: ...
    async def expand(self, seed_ids: list[str], depth: int = 2) -> list[RelationEdge]: ...
    async def list_by_source_ids(self, source_ids: list[str]) -> list[RelationEdge]: ...
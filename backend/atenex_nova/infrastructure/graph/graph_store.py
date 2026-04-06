"""SQL-backed graph store used for proposition relations."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.entities.relation_edge import RelationEdge
from atenex_nova.domain.value_objects.identifiers import RelationType, new_id
from atenex_nova.infrastructure.db.repositories.sql_relation_repo import SqlRelationRepository

logger = logging.getLogger(__name__)


class GraphStore:
    """SQL-backed graph store for proposition relations."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = SqlRelationRepository(session)

    async def add_edge(
        self, source_id: str, target_id: str, relation: str, weight: float = 1.0
    ) -> None:
        edge = RelationEdge(
            id=new_id(),
            source_type="proposition",
            source_id=source_id,
            target_type="concept",
            target_id=target_id,
            relation=relation,
            weight=weight,
        )
        await self._repo.create_many([edge])

    async def upsert_edges(self, edges: list[RelationEdge]) -> list[RelationEdge]:
        return await self._repo.create_many(edges)

    async def expand(self, seed_ids: list[str], depth: int = 2) -> list[RelationEdge]:
        return await self._repo.expand(seed_ids, depth=depth)

    async def build_document_graph(
        self, proposition_ids: list[str], document_id: str
    ) -> list[RelationEdge]:
        edges: list[RelationEdge] = []
        for proposition_id in proposition_ids:
            edges.append(
                RelationEdge(
                    id=new_id(),
                    source_type="proposition",
                    source_id=proposition_id,
                    target_type="document",
                    target_id=document_id,
                    relation=RelationType.APPEARS_IN.value,
                    weight=1.0,
                )
            )
        return await self._repo.create_many(edges)

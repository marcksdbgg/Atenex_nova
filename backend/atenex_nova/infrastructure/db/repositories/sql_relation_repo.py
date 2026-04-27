"""SQL repository: RelationEdge."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.entities.relation_edge import RelationEdge
from atenex_nova.infrastructure.db.models.tables import RelationEdgeModel


class SqlRelationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(self, edges: list[RelationEdge]) -> list[RelationEdge]:
        models = [
            RelationEdgeModel(
                id=edge.id,
                source_type=edge.source_type,
                source_id=edge.source_id,
                target_type=edge.target_type,
                target_id=edge.target_id,
                relation=edge.relation,
                weight=edge.weight,
            )
            for edge in edges
        ]
        self._session.add_all(models)
        await self._session.flush()
        return edges

    async def list_by_source_ids(self, source_ids: list[str]) -> list[RelationEdge]:
        result = await self._session.execute(
            select(RelationEdgeModel).where(RelationEdgeModel.source_id.in_(source_ids))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def expand(
        self,
        seed_ids: list[str],
        depth: int = 2,
        allowed_relations: list[str] | None = None
    ) -> list[RelationEdge]:
        frontier = list(seed_ids)
        seen: set[str] = set(seed_ids)
        expanded: list[RelationEdge] = []

        for _ in range(max(1, depth)):
            if not frontier:
                break
            query = select(RelationEdgeModel).where(RelationEdgeModel.source_id.in_(frontier))
            if allowed_relations:
                query = query.where(RelationEdgeModel.relation.in_(allowed_relations))
                
            result = await self._session.execute(query)
            edges = [self._to_entity(model) for model in result.scalars().all()]
            expanded.extend(edges)
            frontier = []
            for edge in edges:
                if edge.target_id not in seen:
                    seen.add(edge.target_id)
                    frontier.append(edge.target_id)

        return expanded

    async def delete_by_source_ids(self, source_ids: list[str]) -> bool:
        result = await self._session.execute(
            delete(RelationEdgeModel).where(RelationEdgeModel.source_id.in_(source_ids))
        )
        await self._session.flush()
        return result.rowcount > 0

    @staticmethod
    def _to_entity(model: RelationEdgeModel) -> RelationEdge:
        return RelationEdge(
            id=model.id,
            source_type=model.source_type,
            source_id=model.source_id,
            target_type=model.target_type,
            target_id=model.target_id,
            relation=model.relation,
            weight=model.weight,
        )

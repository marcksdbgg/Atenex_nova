"""Stub: Graph store (SQL-based). Implemented in Fase 4."""
import logging
logger = logging.getLogger(__name__)


class GraphStore:
    """Stub graph store for proposition relations."""
    def __init__(self) -> None:
        logger.info("GraphStore initialized (stub)")

    async def add_edge(self, source_id: str, target_id: str, relation: str, weight: float = 1.0) -> None:
        logger.info("Stub: add_edge %s → %s (%s)", source_id[:8], target_id[:8], relation)

    async def expand(self, seed_ids: list[str], depth: int = 2) -> list[dict]:
        logger.info("Stub: expand from %d seeds (depth=%d)", len(seed_ids), depth)
        return []

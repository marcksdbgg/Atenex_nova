"""Application service: query intelligence and search."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.application.orchestrators.retrieval_orchestrator import RetrievalOrchestrator, SearchResult
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService


class QueryService:
    """High-level service for search-only query execution."""

    def __init__(self, session: AsyncSession, qdrant_adapter=None) -> None:
        self._audit = PipelineAuditService(session=session)
        self._orchestrator = RetrievalOrchestrator(session=session, qdrant_adapter=qdrant_adapter, audit=self._audit)

    async def search_only(self, collection_id: str, query: str, mode: str = "auto") -> SearchResult:
        return await self._orchestrator.search(collection_id=collection_id, query_text=query, mode=mode)
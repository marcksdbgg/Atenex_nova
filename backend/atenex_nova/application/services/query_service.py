"""Application service: query intelligence and search."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.application.orchestrators.retrieval_orchestrator import (
    RetrievalOrchestrator,
    SearchResult,
)
from atenex_nova.application.policies.conversation_retrieval_policy import (
    ConversationRetrievalPolicy,
)
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService


class QueryService:
    """High-level service for search-only query execution."""

    def __init__(self, session: AsyncSession, qdrant_adapter=None) -> None:
        self._audit = PipelineAuditService(session=session)
        self._orchestrator = RetrievalOrchestrator(session=session, qdrant_adapter=qdrant_adapter, audit=self._audit)
        self._conversation_policy = ConversationRetrievalPolicy()

    async def search_only(
        self,
        collection_id: str,
        query: str,
        mode: str = "auto",
        conversation_history: Sequence[object] | None = None,
    ) -> SearchResult:
        retrieval_query = self._conversation_policy.build(query, conversation_history)
        return await self._orchestrator.search(
            collection_id=collection_id,
            query_text=retrieval_query.original_text,
            mode=mode,
            retrieval_query_text=(
                retrieval_query.retrieval_text if retrieval_query.contextualized else None
            ),
            retrieval_context_messages=retrieval_query.history_messages_used,
        )

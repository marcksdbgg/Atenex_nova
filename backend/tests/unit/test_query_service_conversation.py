"""Unit coverage for conversation context wiring in QueryService."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from atenex_nova.application.policies.conversation_retrieval_policy import (
    ConversationRetrievalPolicy,
)
from atenex_nova.application.services.query_service import QueryService


@dataclass
class _CapturingOrchestrator:
    calls: list[dict[str, object]] = field(default_factory=list)
    result: object = field(default_factory=object)

    async def search(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.result


@pytest.mark.asyncio
async def test_query_service_keeps_original_query_and_passes_context_only_for_follow_up() -> None:
    orchestrator = _CapturingOrchestrator()
    service = QueryService.__new__(QueryService)
    service._conversation_policy = ConversationRetrievalPolicy()
    service._orchestrator = orchestrator

    result = await service.search_only(
        collection_id="collection",
        query="¿Y qué decía él?",
        conversation_history=[
            {"role": "user", "content": "La conversación trata sobre Cervantes y el amor."}
        ],
    )

    assert result is orchestrator.result
    assert orchestrator.calls[0]["query_text"] == "¿Y qué decía él?"
    assert "Cervantes" in str(orchestrator.calls[0]["retrieval_query_text"])
    assert orchestrator.calls[0]["retrieval_context_messages"] == 1

    await service.search_only(
        collection_id="collection",
        query="Define entropía",
        conversation_history=[{"role": "user", "content": "Cervantes"}],
    )

    assert orchestrator.calls[1]["query_text"] == "Define entropía"
    assert orchestrator.calls[1]["retrieval_query_text"] is None
    assert orchestrator.calls[1]["retrieval_context_messages"] == 0

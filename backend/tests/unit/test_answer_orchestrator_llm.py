"""Unit tests for LLM-specific behavior in answer orchestration."""

from __future__ import annotations

import pytest

from atenex_nova.application.orchestrators.answer_orchestrator import AnswerOrchestrator
from atenex_nova.shared.exceptions.base import ServiceUnavailableError


class _BlankGateway:
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        return "   "


class _TextGateway:
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        return "  respuesta valida  "


@pytest.mark.asyncio
async def test_generate_raises_service_unavailable_when_llm_returns_empty() -> None:
    orchestrator = AnswerOrchestrator(generator=_BlankGateway())

    with pytest.raises(ServiceUnavailableError) as exc:
        await orchestrator._generate("prompt", "direct_answer")

    assert exc.value.code == "SERVICE_UNAVAILABLE"
    assert "non-LLM fallback answers are disabled" in str(exc.value)


@pytest.mark.asyncio
async def test_generate_accepts_non_empty_llm_output() -> None:
    orchestrator = AnswerOrchestrator(generator=_TextGateway())

    text = await orchestrator._generate("prompt", "direct_answer")

    assert text == "respuesta valida"

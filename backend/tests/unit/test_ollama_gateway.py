"""Tests for the answer-facing Ollama HTTP contract."""

from __future__ import annotations

from typing import Any

import pytest

from atenex_nova.infrastructure.llm.llm_gateway import OllamaAdapter


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "response": "respuesta visible",
            "prompt_eval_count": 12,
            "eval_count": 3,
        }


class _RecordingClient:
    payload: dict[str, Any] | None = None

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> _RecordingClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any]) -> _Response:
        _ = url
        type(self).payload = json
        return _Response()


@pytest.mark.asyncio
async def test_ollama_disables_hidden_reasoning_for_visible_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "atenex_nova.infrastructure.llm.llm_gateway.httpx.AsyncClient",
        _RecordingClient,
    )

    result = await OllamaAdapter().generate("pregunta", max_tokens=96)

    assert result.text == "respuesta visible"
    assert _RecordingClient.payload is not None
    assert _RecordingClient.payload["think"] is False
    assert _RecordingClient.payload["options"] == {
        "num_predict": 96,
        "temperature": 0.3,
    }

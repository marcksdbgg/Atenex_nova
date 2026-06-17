"""Unit tests for embedding fallback visibility (H-9)."""

from __future__ import annotations

import pytest

from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.presentation.api.routers import health
from atenex_nova.shared.config.settings import Settings
from atenex_nova.shared.exceptions.base import ServiceUnavailableError


def test_ensure_indexable_blocks_fallback_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "atenex_nova.infrastructure.embeddings.embedding_adapter.get_settings",
        lambda: Settings(allow_fallback_embeddings=False),
    )
    adapter = EmbeddingGemmaAdapter.__new__(EmbeddingGemmaAdapter)
    adapter.model = None
    adapter._fallback_only = True
    adapter._dim = 384
    adapter._required = False
    adapter._model_name = "test"

    with pytest.raises(ServiceUnavailableError, match="hash fallback active"):
        adapter.ensure_indexable()


def test_ensure_indexable_allows_fallback_when_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "atenex_nova.infrastructure.embeddings.embedding_adapter.get_settings",
        lambda: Settings(allow_fallback_embeddings=True),
    )
    adapter = EmbeddingGemmaAdapter.__new__(EmbeddingGemmaAdapter)
    adapter.model = None
    adapter._fallback_only = True
    adapter._dim = 384
    adapter._required = False
    adapter._model_name = "test"

    adapter.ensure_indexable()


@pytest.mark.asyncio
async def test_embeddings_health_probe_exposes_fallback_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FallbackAdapter:
        uses_fallback = True

        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.1] * 384]

    monkeypatch.setattr(
        health,
        "EmbeddingGemmaAdapter",
        lambda **kwargs: _FallbackAdapter(),
    )

    probe = await health._probe_embeddings(Settings())
    assert probe.fallback is True
    assert probe.available is False
    assert probe.detail is not None

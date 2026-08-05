"""Reranker degradation must be explicit and failed loads must not repeat per query."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from atenex_nova.infrastructure.embeddings.reranker_adapter import RerankerAdapter
from atenex_nova.presentation.api.routers import health
from atenex_nova.shared.config.settings import Settings


@pytest.fixture(autouse=True)
def reset_reranker_cache() -> Iterator[None]:
    RerankerAdapter.reset_cache_for_tests()
    yield
    RerankerAdapter.reset_cache_for_tests()


def test_disabled_reranker_is_cached_as_an_explicit_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_calls = 0

    def disabled_settings() -> Settings:
        nonlocal settings_calls
        settings_calls += 1
        return Settings(enable_reranker=False, strict_mode=False)

    monkeypatch.setattr(
        "atenex_nova.infrastructure.embeddings.reranker_adapter.get_settings",
        disabled_settings,
    )

    first = RerankerAdapter(required=False)
    second = RerankerAdapter(required=False)

    assert settings_calls == 2
    assert first is not second
    assert first.is_available is False
    assert first.model_name == "heuristic"
    assert first.failure_detail == "reranker is disabled by configuration settings/profile"
    assert second.failure_detail == first.failure_detail


def test_failed_model_load_is_attempted_only_once_per_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_calls = 0

    class _FailingCrossEncoder:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            nonlocal load_calls
            load_calls += 1
            raise RuntimeError("local model missing")

    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    fake_sentence_transformers = SimpleNamespace(CrossEncoder=_FailingCrossEncoder)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_sentence_transformers)
    monkeypatch.setattr(
        "atenex_nova.infrastructure.embeddings.reranker_adapter.get_settings",
        lambda: Settings(
            enable_reranker=True,
            reranker_device="cpu",
            reranker_path="/models/missing",
            strict_mode=False,
        ),
    )

    first = RerankerAdapter(required=False)
    second = RerankerAdapter(required=False)

    assert load_calls == 1
    assert first.is_available is False
    assert second.failure_detail is not None
    assert "local model missing" in second.failure_detail


@pytest.mark.asyncio
async def test_reranker_health_exposes_heuristic_degradation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _UnavailableReranker:
        is_available = False
        model_name = "heuristic"
        failure_detail = "model is not present locally"

    monkeypatch.setattr(health, "RerankerAdapter", lambda **_kwargs: _UnavailableReranker())

    probe = await health._probe_reranker(Settings(reranker_path="/models/reranker"))

    assert probe.name == "reranker"
    assert probe.available is False
    assert probe.fallback is True
    assert probe.detail == "model is not present locally"

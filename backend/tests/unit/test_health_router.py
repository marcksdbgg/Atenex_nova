"""Unit tests for health router dependency probes."""

from __future__ import annotations

import pytest

from atenex_nova.presentation.api.dto.schemas import DependencyHealthResponse
from atenex_nova.presentation.api.routers import health


@pytest.mark.asyncio
async def test_runtime_dependencies_health_is_degraded_when_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_ollama(_settings):
        return DependencyHealthResponse(
            name="llm",
            endpoint="http://localhost:11434/api/tags",
            available=False,
            detail="connection refused",
        )

    async def fake_qdrant(_settings):
        return DependencyHealthResponse(
            name="qdrant",
            endpoint="http://localhost:6333/collections",
            available=True,
            detail=None,
        )

    monkeypatch.setattr(health, "_probe_ollama", fake_ollama)
    monkeypatch.setattr(health, "_probe_qdrant", fake_qdrant)

    response = await health.runtime_dependencies_health()

    assert response.status == "degraded"
    assert len(response.dependencies) == 2
    llm = next(item for item in response.dependencies if item.name == "llm")
    assert llm.available is False

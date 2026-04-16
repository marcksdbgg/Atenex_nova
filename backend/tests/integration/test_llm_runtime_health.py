"""Integration test to ensure LLM runtime is actually reachable."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from atenex_nova.main import app


@pytest.mark.asyncio
async def test_health_dependencies_reports_live_llm_runtime() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/dependencies")

    assert response.status_code == 200
    payload = response.json()
    llm = next((item for item in payload["dependencies"] if item["name"] == "llm"), None)
    assert llm is not None, "health endpoint must include LLM dependency state"
    assert llm["available"], f"LLM runtime inactive or misconfigured: {llm.get('detail')}"

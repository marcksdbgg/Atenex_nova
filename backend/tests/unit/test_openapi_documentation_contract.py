"""Contract tests for documented FastAPI routes."""

from __future__ import annotations

import re
from pathlib import Path

from atenex_nova.main import create_app

ROUTE_ROW_PATTERN = re.compile(
    r"^\|\s*(GET|POST|PATCH|PUT|DELETE)\s*\|\s*`([^`]+)`\s*\|",
)


def _documented_routes() -> set[tuple[str, str]]:
    docs_path = Path(__file__).resolve().parents[3] / "docs" / "api-endpoints.md"
    routes: set[tuple[str, str]] = set()
    for line in docs_path.read_text(encoding="utf-8").splitlines():
        match = ROUTE_ROW_PATTERN.match(line)
        if match:
            method, path = match.groups()
            routes.add((method, path))
    return routes


def _openapi_routes() -> set[tuple[str, str]]:
    schema = create_app().openapi()
    routes: set[tuple[str, str]] = set()
    for path, methods in schema["paths"].items():
        for method in methods:
            routes.add((method.upper(), path))
    return routes


def test_api_endpoints_document_matches_openapi_routes() -> None:
    documented_routes = _documented_routes()
    openapi_routes = _openapi_routes()

    assert documented_routes, "docs/api-endpoints.md did not expose route rows"
    assert documented_routes == openapi_routes

"""Health check router."""

from __future__ import annotations

import httpx
from fastapi import APIRouter

from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.presentation.api.dto.schemas import (
    DependencyHealthResponse,
    HealthResponse,
    RuntimeHealthResponse,
)
from atenex_nova.shared.config.settings import Settings, get_settings

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok", version="0.1.0")


async def _probe_ollama(settings: Settings) -> DependencyHealthResponse:
    endpoint = f"{settings.llm_url.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(endpoint)
            response.raise_for_status()
            payload = response.json()

        models = payload.get("models", [])
        names: list[str] = []
        if isinstance(models, list):
            names = [
                str(item.get("name", "")).strip()
                for item in models
                if isinstance(item, dict)
            ]
        expected = settings.llm_model.strip()
        has_model = any(name == expected or name.startswith(f"{expected}:") for name in names)
        detail = None if has_model else f"Model '{expected}' not present in Ollama tags"
        return DependencyHealthResponse(name="llm", endpoint=endpoint, available=has_model, detail=detail)
    except Exception as exc:
        return DependencyHealthResponse(name="llm", endpoint=endpoint, available=False, detail=str(exc))


async def _probe_llamacpp(settings: Settings) -> DependencyHealthResponse:
    endpoint = f"{settings.llm_url.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(endpoint)
            response.raise_for_status()
        return DependencyHealthResponse(name="llm", endpoint=endpoint, available=True)
    except Exception as exc:
        return DependencyHealthResponse(name="llm", endpoint=endpoint, available=False, detail=str(exc))


async def _probe_qdrant(settings: Settings) -> DependencyHealthResponse:
    endpoint = f"{settings.qdrant_url.rstrip('/')}/collections"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(endpoint)
            response.raise_for_status()
        return DependencyHealthResponse(name="qdrant", endpoint=endpoint, available=True)
    except Exception as exc:
        return DependencyHealthResponse(name="qdrant", endpoint=endpoint, available=False, detail=str(exc))


async def _probe_embeddings(settings: Settings) -> DependencyHealthResponse:
    endpoint = settings.embedding_model
    try:
        adapter = EmbeddingGemmaAdapter(
            model_name=settings.embedding_model,
            dim=settings.embedding_dimensions,
            required=False,
        )
        vectors = await adapter.embed(["health probe embeddings"])
        has_vectors = bool(vectors and vectors[0])
        using_fallback = adapter.uses_fallback
        available = has_vectors and not using_fallback
        detail = None
        if using_fallback:
            detail = "Embedding model is using deterministic fallback vectors"
        elif not has_vectors:
            detail = "Embedding probe returned empty vectors"
        return DependencyHealthResponse(
            name="embeddings",
            endpoint=endpoint,
            available=available,
            detail=detail,
            fallback=using_fallback,
        )
    except Exception as exc:
        return DependencyHealthResponse(
            name="embeddings",
            endpoint=endpoint,
            available=False,
            detail=str(exc),
            fallback=None,
        )


async def _probe_docling() -> DependencyHealthResponse:
    endpoint = "python:docling"
    try:
        from docling.document_converter import DocumentConverter  # type: ignore[import-not-found]

        _ = DocumentConverter
        return DependencyHealthResponse(name="docling", endpoint=endpoint, available=True)
    except Exception as exc:
        return DependencyHealthResponse(name="docling", endpoint=endpoint, available=False, detail=str(exc))


async def _probe_visual_runtime(settings: Settings) -> DependencyHealthResponse:
    endpoint = str(settings.visual_pages_path)
    try:
        settings.visual_pages_path.mkdir(parents=True, exist_ok=True)
        from PIL import Image  # type: ignore[import-not-found]

        _ = Image
        return DependencyHealthResponse(name="visual", endpoint=endpoint, available=True)
    except Exception as exc:
        return DependencyHealthResponse(name="visual", endpoint=endpoint, available=False, detail=str(exc))


async def _probe_turbovec(settings: Settings) -> DependencyHealthResponse:
    endpoint = str(settings.turbovec_path)
    try:
        import numpy as np
        from turbovec import IdMapIndex
        idx = IdMapIndex(dim=8, bit_width=settings.turbovec_bit_width)
        vecs = np.random.rand(2, 8).astype(np.float32)
        idx.add_with_ids(vecs, np.array([1, 2], dtype=np.uint64))
        return DependencyHealthResponse(name="turbovec", endpoint=endpoint, available=True)
    except Exception as exc:
        return DependencyHealthResponse(name="turbovec", endpoint=endpoint, available=False, detail=str(exc))


@router.get("/health/dependencies", response_model=RuntimeHealthResponse)
async def runtime_dependencies_health() -> RuntimeHealthResponse:
    settings = get_settings()
    llm_probe = await (_probe_ollama(settings) if settings.llm_backend == "ollama" else _probe_llamacpp(settings))
    qdrant_probe = await _probe_qdrant(settings)
    embeddings_probe = await _probe_embeddings(settings)
    docling_probe = await _probe_docling()
    visual_probe = await _probe_visual_runtime(settings)
    turbovec_probe = await _probe_turbovec(settings)
    sqlite_probe = _probe_sqlite(settings)
    dependencies = [llm_probe, qdrant_probe, embeddings_probe, docling_probe, visual_probe, turbovec_probe]
    if sqlite_probe is not None:
        dependencies.append(sqlite_probe)
    status = "ok" if all(item.available for item in dependencies if item.name != "database") else "degraded"
    if sqlite_probe is not None and not sqlite_probe.available:
        status = "degraded"
    return RuntimeHealthResponse(status=status, version="0.1.0", dependencies=dependencies)


def _probe_sqlite(settings: Settings) -> DependencyHealthResponse | None:
    if not settings.database_url.startswith("sqlite"):
        return None
    return DependencyHealthResponse(
        name="database",
        endpoint=settings.database_url,
        available=True,
        detail="SQLite mode: use a single worker for bulk ingestion or switch to PostgreSQL",
    )

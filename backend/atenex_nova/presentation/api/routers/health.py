"""Health check router."""

from __future__ import annotations

import httpx
from fastapi import APIRouter

from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.presentation.api.dto.schemas import DependencyHealthResponse, HealthResponse, RuntimeHealthResponse
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
        available = has_vectors and not adapter.uses_fallback
        detail = None
        if adapter.uses_fallback:
            detail = "Embedding model is using deterministic fallback vectors"
        elif not has_vectors:
            detail = "Embedding probe returned empty vectors"
        return DependencyHealthResponse(name="embeddings", endpoint=endpoint, available=available, detail=detail)
    except Exception as exc:
        return DependencyHealthResponse(name="embeddings", endpoint=endpoint, available=False, detail=str(exc))


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


@router.get("/health/dependencies", response_model=RuntimeHealthResponse)
async def runtime_dependencies_health() -> RuntimeHealthResponse:
    settings = get_settings()
    llm_probe = await (_probe_ollama(settings) if settings.llm_backend == "ollama" else _probe_llamacpp(settings))
    qdrant_probe = await _probe_qdrant(settings)
    embeddings_probe = await _probe_embeddings(settings)
    docling_probe = await _probe_docling()
    visual_probe = await _probe_visual_runtime(settings)
    dependencies = [llm_probe, qdrant_probe, embeddings_probe, docling_probe, visual_probe]
    status = "ok" if all(item.available for item in dependencies) else "degraded"
    return RuntimeHealthResponse(status=status, version="0.1.0", dependencies=dependencies)

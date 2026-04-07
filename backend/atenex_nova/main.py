"""Atenex Nova — FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from atenex_nova.infrastructure.db.session import create_all_tables, dispose_engine
from atenex_nova.presentation.api.routers import answers, collections, documents, evaluation, health, jobs, queries
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.logging.logger import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown lifecycle."""
    settings = get_settings()
    setup_logging(settings.log_level)
    await create_all_tables()
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Plataforma local de memoria documental y RAG de nueva generación",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health.router)
    app.include_router(collections.router)
    app.include_router(documents.router)
    app.include_router(jobs.router)
    app.include_router(answers.router)
    app.include_router(evaluation.router)
    app.include_router(queries.router)

    return app


app = create_app()

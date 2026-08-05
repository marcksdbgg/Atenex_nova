"""Integration coverage for full-corpus and conversational retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.application.orchestrators.retrieval_orchestrator import RetrievalOrchestrator
from atenex_nova.application.policies.conversation_retrieval_policy import (
    ConversationRetrievalPolicy,
)
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.entities.summary_node import SummaryNode
from atenex_nova.domain.value_objects.identifiers import DocumentStatus, new_id
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_query_repo import SqlQueryRepository
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository
from atenex_nova.shared.config.settings import EmbeddingProfile, Settings


@dataclass
class _UnavailableQdrant:
    @property
    def is_available(self) -> bool:
        return False


@dataclass
class _RecordingEmbedder:
    queries: list[str] = field(default_factory=list)

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.0] * 256


@dataclass
class _EmptyCandidateIndex:
    async def search(self, **_kwargs: object) -> list[dict[str, object]]:
        return []


@dataclass
class _HeuristicOnlyReranker:
    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [0.0] * len(pairs)


@dataclass
class _NoopVisualRetriever:
    async def search(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []


@pytest.fixture()
async def session_factory(tmp_path: Path):
    db_path = tmp_path / "retrieval-pagination.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_large_collection(factory) -> tuple[str, str]:
    collection = Collection(id=new_id(), name="65-document corpus")
    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    target_document_id = ""

    async with factory() as session:
        await SqlCollectionRepository(session).create(collection)
        document_repository = SqlDocumentRepository(session)
        for index in range(65):
            document = Document(
                id=new_id(),
                collection_id=collection.id,
                title="Cervantes source beyond page one" if index == 0 else f"Filler {index:02d}",
                source_path=f"/tmp/source-{index:02d}.txt",
                mime_type="text/plain",
                checksum=f"{index:064x}",
                status=DocumentStatus.READY,
                created_at=base_time + timedelta(seconds=index),
                updated_at=base_time + timedelta(seconds=index),
            )
            await document_repository.create(document)
            if index == 0:
                target_document_id = document.id

        await SqlSummaryRepository(session).create_many(
            [
                SummaryNode(
                    id=new_id(),
                    scope_type="document",
                    scope_id=target_document_id,
                    text=(
                        "Cervantes contrapone el amor vivido al artificio del amor fingido "
                        "en su lectura literaria."
                    ),
                )
            ]
        )
        await session.commit()

    return collection.id, target_document_id


@pytest.mark.asyncio
async def test_contextual_retrieval_reaches_document_after_first_fifty(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        embedding_profile=EmbeddingProfile.LITE,
        candidate_backend="purepy",
        strict_mode=False,
        enable_reranker=False,
    )
    monkeypatch.setattr(
        "atenex_nova.application.orchestrators.retrieval_orchestrator.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.candidate_index_factory.get_settings",
        lambda: settings,
    )
    collection_id, target_document_id = await _seed_large_collection(session_factory)
    original_query = "¿Y qué decía él?"
    retrieval_query = ConversationRetrievalPolicy().build(
        original_query,
        [
            {
                "role": "user",
                "content": "Estamos hablando de Cervantes y su concepción del amor.",
            }
        ],
    )
    embedder = _RecordingEmbedder()

    async with session_factory() as session:
        orchestrator = RetrievalOrchestrator(
            session,
            qdrant_adapter=_UnavailableQdrant(),
            embedder=embedder,
            visual_adapter=_NoopVisualRetriever(),
            reranker=_HeuristicOnlyReranker(),
        )
        orchestrator._candidate_index = _EmptyCandidateIndex()
        result = await orchestrator.search(
            collection_id=collection_id,
            query_text=original_query,
            retrieval_query_text=retrieval_query.retrieval_text,
            retrieval_context_messages=retrieval_query.history_messages_used,
        )

        assert result.query.text == original_query
        assert "cervantes" not in result.query.normalized_text
        assert "Cervantes" in result.query.retrieval_query
        assert result.query.retrieval_context_messages == 1
        assert any(
            hit.document_id == target_document_id
            and hit.title == "Cervantes source beyond page one"
            for hit in result.hits
        )
        assert embedder.queries == [result.query.retrieval_query]
        stored_query = await SqlQueryRepository(session).get_by_id(result.query.id)
        assert stored_query is not None
        assert stored_query.text == original_query
        assert "cervantes" not in stored_query.normalized_text
        assert stored_query.retrieval_context_messages == 0

        independent = await orchestrator.search(
            collection_id=collection_id,
            query_text="Define aprendizaje continuo",
        )
        assert independent.query.retrieval_query == "define aprendizaje continuo"
        assert independent.query.retrieval_context_messages == 0
        assert "Cervantes" not in independent.query.retrieval_query

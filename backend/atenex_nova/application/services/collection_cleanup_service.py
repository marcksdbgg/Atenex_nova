"""Application service for safe collection deletion and index cleanup."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from atenex_nova.infrastructure.db.models.tables import (
    AnswerModel,
    ChunkModel,
    CitationModel,
    DocumentModel,
    DocumentNodeModel,
    EvaluationCaseModel,
    EvaluationRunModel,
    JobModel,
    PipelineAuditModel,
    PropositionModel,
    QueryModel,
    RelationEdgeModel,
    SummaryNodeModel,
)
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter
from atenex_nova.shared.config.settings import get_settings


class CollectionCleanupService:
    """Delete collection metadata/indexes while preserving source files.

    This cleanup intentionally removes only system-generated artifacts:
    SQL records, vector indexes, and visual cache files. It never deletes the
    original files referenced by document source paths.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._collection_repo = SqlCollectionRepository(session)
        self._qdrant = QdrantAdapter(host="localhost", port=6333)

    async def delete_collection(self, collection_id: str) -> bool:
        collection = await self._collection_repo.get_by_id(collection_id)
        if collection is None:
            return False

        document_ids = await self._read_ids(
            select(DocumentModel.id).where(DocumentModel.collection_id == collection_id)
        )
        query_ids = await self._read_ids(
            select(QueryModel.id).where(QueryModel.collection_id == collection_id)
        )
        answer_ids = await self._read_ids(
            select(AnswerModel.id).where(AnswerModel.query_id.in_(query_ids))
        ) if query_ids else []
        evaluation_run_ids = await self._read_ids(
            select(EvaluationRunModel.id).where(EvaluationRunModel.collection_id == collection_id)
        )
        chunk_ids = await self._read_ids(
            select(ChunkModel.id).where(ChunkModel.document_id.in_(document_ids))
        ) if document_ids else []
        proposition_ids = await self._read_ids(
            select(PropositionModel.id).where(PropositionModel.document_id.in_(document_ids))
        ) if document_ids else []

        if answer_ids:
            await self._session.execute(delete(CitationModel).where(CitationModel.answer_id.in_(answer_ids)))
        if document_ids:
            await self._session.execute(delete(CitationModel).where(CitationModel.document_id.in_(document_ids)))

        if query_ids:
            await self._session.execute(delete(AnswerModel).where(AnswerModel.query_id.in_(query_ids)))
            await self._session.execute(delete(QueryModel).where(QueryModel.id.in_(query_ids)))

        if evaluation_run_ids:
            await self._session.execute(delete(EvaluationCaseModel).where(EvaluationCaseModel.run_id.in_(evaluation_run_ids)))
        await self._session.execute(delete(EvaluationRunModel).where(EvaluationRunModel.collection_id == collection_id))

        if proposition_ids:
            await self._session.execute(
                delete(RelationEdgeModel).where(
                    or_(
                        RelationEdgeModel.source_id.in_(proposition_ids),
                        RelationEdgeModel.target_id.in_(proposition_ids),
                    )
                )
            )

        await self._session.execute(
            delete(SummaryNodeModel).where(
                SummaryNodeModel.scope_type == "collection",
                SummaryNodeModel.scope_id == collection_id,
            )
        )
        if document_ids:
            await self._session.execute(
                delete(SummaryNodeModel).where(
                    SummaryNodeModel.scope_type == "document",
                    SummaryNodeModel.scope_id.in_(document_ids),
                )
            )
        if chunk_ids:
            await self._session.execute(
                delete(SummaryNodeModel).where(
                    SummaryNodeModel.scope_type == "section",
                    SummaryNodeModel.scope_id.in_(chunk_ids),
                )
            )

        if document_ids:
            await self._session.execute(delete(PropositionModel).where(PropositionModel.document_id.in_(document_ids)))
            await self._session.execute(delete(ChunkModel).where(ChunkModel.document_id.in_(document_ids)))
            await self._session.execute(delete(DocumentNodeModel).where(DocumentNodeModel.document_id.in_(document_ids)))
            await self._session.execute(delete(DocumentModel).where(DocumentModel.id.in_(document_ids)))

        target_ids = [collection_id, *document_ids, *query_ids, *answer_ids]
        if target_ids:
            await self._session.execute(delete(JobModel).where(JobModel.target_id.in_(target_ids)))
            await self._session.execute(delete(PipelineAuditModel).where(PipelineAuditModel.entity_id.in_(target_ids)))

        deleted = await self._collection_repo.delete(collection_id)

        await self._delete_vector_indexes(collection_id)
        self._delete_visual_cache(collection_id)
        return deleted

    async def _delete_vector_indexes(self, collection_id: str) -> None:
        await self._qdrant.delete_collection(f"collection_{collection_id}")
        await self._qdrant.delete_collection(f"collection_{collection_id}_propositions")
        await self._qdrant.delete_collection(f"collection_{collection_id}_summaries")
        await self._qdrant.delete_by_filter("pages_visual", {"collection_id": collection_id})

    def _delete_visual_cache(self, collection_id: str) -> None:
        visual_root = get_settings().visual_pages_path
        self._safe_unlink(visual_root / f"{collection_id}.json")
        self._safe_rmtree(visual_root / collection_id)

    async def _read_ids(self, statement: Select[Any]) -> list[str]:
        result = await self._session.execute(statement)
        return [str(row[0]) for row in result.all()]

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        if path.exists() and path.is_file():
            path.unlink()

    @staticmethod
    def _safe_rmtree(path: Path) -> None:
        if path.exists() and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

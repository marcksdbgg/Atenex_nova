"""Readiness barrier and bounded repair plan for ingested documents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.application.policies.visual_index_policy import should_index_visual
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.value_objects.identifiers import DocumentStatus, JobType
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import (
    SqlPropositionRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    missing: tuple[str, ...]
    chunk_count: int
    proposition_count: int
    section_summary_count: int
    document_summary_count: int
    visual_required: bool


@dataclass(frozen=True)
class RepairResult:
    jobs_created: int
    job_types: tuple[JobType, ...]
    status_changed: bool


class DocumentReadinessService:
    """Prove all required memory layers before publishing a document as READY."""

    _UPSTREAM_JOB_TYPES: ClassVar[set[JobType]] = {
        JobType.PARSE_DOCUMENT,
        JobType.NORMALIZE_DOCUMENT,
        JobType.SEGMENT_DOCUMENT,
        JobType.EMBED_DOCUMENT,
        JobType.EMBED_CHUNKS,
        JobType.EXTRACT_PROPOSITIONS,
    }

    def __init__(self, session: AsyncSession, settings: Any) -> None:
        self._session = session
        self._settings = settings
        self._document_repo = SqlDocumentRepository(session)
        self._chunk_repo = SqlChunkRepository(session)
        self._proposition_repo = SqlPropositionRepository(session)
        self._summary_repo = SqlSummaryRepository(session)
        self._job_repo = SqlJobRepository(session)

    async def evaluate(self, document: Document) -> ReadinessReport:
        chunks = await self._chunk_repo.get_by_document(document.id)
        propositions = await self._proposition_repo.list_by_document(document.id)
        section_summaries = await self._summary_repo.list_sections_by_document(document.id)
        document_summaries = await self._summary_repo.list_by_document(document.id)
        missing: list[str] = []

        if document.status not in {DocumentStatus.INDEXED, DocumentStatus.READY}:
            missing.append("document_not_indexed")
        if not chunks:
            missing.append("chunks_missing")
        elif any(not chunk.embedding_ref for chunk in chunks):
            missing.append("chunk_embeddings_missing")

        if not propositions:
            missing.append("propositions_missing")
        elif any(not proposition.embedding_ref for proposition in propositions):
            missing.append("proposition_embeddings_missing")

        section_counts: dict[str, int] = {}
        for summary in section_summaries:
            section_counts[summary.scope_id] = section_counts.get(summary.scope_id, 0) + 1
        expected_chunk_ids = {chunk.id for chunk in chunks}
        if (
            set(section_counts) != expected_chunk_ids
            or any(count != 1 for count in section_counts.values())
        ):
            missing.append("section_summaries_incomplete")
        if len(document_summaries) != 1:
            missing.append("document_summary_incomplete")

        all_required_summaries = [*section_summaries, *document_summaries]
        if all_required_summaries and any(
            not summary.embedding_ref for summary in all_required_summaries
        ):
            missing.append("summary_embeddings_missing")

        generation_started_at = await self._job_repo.latest_succeeded_created_at(
            document.id,
            {JobType.EMBED_DOCUMENT, JobType.EMBED_CHUNKS},
        )
        if generation_started_at is None:
            missing.append("index_embedding_job_incomplete")

        if not await self._job_repo.has_succeeded(
            document.id,
            JobType.EXTRACT_PROPOSITIONS,
            not_before=generation_started_at,
        ):
            missing.append("proposition_extraction_job_incomplete")
        if not await self._job_repo.has_succeeded(
            document.id,
            JobType.EMBED_PROPOSITIONS,
            not_before=generation_started_at,
        ):
            missing.append("proposition_embedding_job_incomplete")
        if not await self._job_repo.has_succeeded(
            document.id,
            JobType.GENERATE_SUMMARIES,
            not_before=generation_started_at,
        ):
            missing.append("summary_generation_job_incomplete")
        if not await self._job_repo.has_succeeded(
            document.id,
            JobType.EMBED_SUMMARIES,
            not_before=generation_started_at,
        ):
            missing.append("summary_embedding_job_incomplete")
        if not await self._job_repo.has_succeeded(
            document.id,
            JobType.BUILD_GRAPH,
            not_before=generation_started_at,
        ):
            missing.append("graph_job_incomplete")

        visual_required = should_index_visual(document, self._settings)
        if visual_required and not await self._job_repo.has_succeeded(
            document.id,
            JobType.INDEX_VISUAL_PAGES,
            not_before=generation_started_at,
        ):
            missing.append("visual_job_incomplete")

        unique_missing = tuple(dict.fromkeys(missing))
        return ReadinessReport(
            ready=not unique_missing,
            missing=unique_missing,
            chunk_count=len(chunks),
            proposition_count=len(propositions),
            section_summary_count=len(section_summaries),
            document_summary_count=len(document_summaries),
            visual_required=visual_required,
        )

    async def apply_barrier(self, document: Document) -> ReadinessReport:
        report = await self.evaluate(document)
        if report.ready:
            if document.status == DocumentStatus.INDEXED:
                document.mark_ready()
                await self._document_repo.update(document)
        elif document.status == DocumentStatus.READY:
            document.mark_incomplete()
            await self._document_repo.update(document)
        return report

    async def enqueue_repairs(self, document: Document) -> RepairResult:
        """Enqueue only missing stages; upstream jobs retain their normal fan-out."""
        report = await self.evaluate(document)
        if report.ready:
            _, created = await self._job_repo.ensure_pending(
                job_type=JobType.CHECK_DOCUMENT_READINESS,
                target_id=document.id,
            )
            return RepairResult(
                jobs_created=int(created),
                job_types=(JobType.CHECK_DOCUMENT_READINESS,) if created else (),
                status_changed=False,
            )

        status_changed = False
        base_missing = any(
            item in report.missing
            for item in (
                "document_not_indexed",
                "chunks_missing",
                "chunk_embeddings_missing",
                "index_embedding_job_incomplete",
            )
        )
        if base_missing:
            if document.status != DocumentStatus.REGISTERED:
                document.mark_registered()
                await self._document_repo.update(document)
                status_changed = True
            if await self._job_repo.has_active(document.id, self._UPSTREAM_JOB_TYPES):
                return RepairResult(0, (), status_changed)
            await self._job_repo.delete_pending_by_targets([document.id])
            _, created = await self._job_repo.ensure_pending(
                job_type=JobType.PARSE_DOCUMENT,
                target_id=document.id,
            )
            return RepairResult(
                jobs_created=int(created),
                job_types=(JobType.PARSE_DOCUMENT,) if created else (),
                status_changed=status_changed,
            )

        if document.status == DocumentStatus.READY:
            document.mark_incomplete()
            await self._document_repo.update(document)
            status_changed = True

        if await self._job_repo.has_active(document.id, self._UPSTREAM_JOB_TYPES):
            return RepairResult(0, (), status_changed)

        created_types: list[JobType] = []

        if any(
            item in report.missing
            for item in (
                "propositions_missing",
                "proposition_extraction_job_incomplete",
            )
        ):
            _, created = await self._job_repo.ensure_pending(
                job_type=JobType.EXTRACT_PROPOSITIONS,
                target_id=document.id,
            )
            if created:
                created_types.append(JobType.EXTRACT_PROPOSITIONS)
            return RepairResult(len(created_types), tuple(created_types), status_changed)

        if any(
            item in report.missing
            for item in (
                "proposition_embeddings_missing",
                "proposition_embedding_job_incomplete",
            )
        ):
            _, created = await self._job_repo.ensure_pending(
                job_type=JobType.EMBED_PROPOSITIONS,
                target_id=document.id,
            )
            if created:
                created_types.append(JobType.EMBED_PROPOSITIONS)

        summary_structure_missing = any(
            item in report.missing
            for item in (
                "section_summaries_incomplete",
                "document_summary_incomplete",
                "summary_generation_job_incomplete",
            )
        )
        if summary_structure_missing:
            _, created = await self._job_repo.ensure_pending(
                job_type=JobType.GENERATE_SUMMARIES,
                target_id=document.id,
            )
            if created:
                created_types.append(JobType.GENERATE_SUMMARIES)
        elif any(
            item in report.missing
            for item in ("summary_embeddings_missing", "summary_embedding_job_incomplete")
        ):
            summaries = [
                *(await self._summary_repo.list_sections_by_document(document.id)),
                *(await self._summary_repo.list_by_document(document.id)),
            ]
            _, created = await self._job_repo.ensure_pending(
                job_type=JobType.EMBED_SUMMARIES,
                target_id=document.id,
                payload={"summary_ids": [summary.id for summary in summaries]},
            )
            if created:
                created_types.append(JobType.EMBED_SUMMARIES)

        if "graph_job_incomplete" in report.missing:
            _, created = await self._job_repo.ensure_pending(
                job_type=JobType.BUILD_GRAPH,
                target_id=document.id,
            )
            if created:
                created_types.append(JobType.BUILD_GRAPH)
        elif "visual_job_incomplete" in report.missing:
            _, created = await self._job_repo.ensure_pending(
                job_type=JobType.INDEX_VISUAL_PAGES,
                target_id=document.id,
            )
            if created:
                created_types.append(JobType.INDEX_VISUAL_PAGES)

        if not created_types:
            _, created = await self._job_repo.ensure_pending(
                job_type=JobType.CHECK_DOCUMENT_READINESS,
                target_id=document.id,
            )
            if created:
                created_types.append(JobType.CHECK_DOCUMENT_READINESS)

        return RepairResult(len(created_types), tuple(created_types), status_changed)

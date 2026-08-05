"""SQL repository: SummaryNode."""

import json
from dataclasses import dataclass

from sqlalchemy import and_, delete, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.entities.summary_node import SummaryNode
from atenex_nova.domain.value_objects.identifiers import DocumentStatus
from atenex_nova.infrastructure.db.models.tables import (
    ChunkModel,
    DocumentModel,
    SummaryNodeModel,
)


@dataclass(frozen=True)
class SummaryUpsertResult:
    summary: SummaryNode
    content_changed: bool
    removed_ids: tuple[str, ...] = ()


class SqlSummaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(self, summaries: list[SummaryNode]) -> list[SummaryNode]:
        models = [
            SummaryNodeModel(
                id=item.id,
                scope_type=item.scope_type,
                scope_id=item.scope_id,
                text=item.text,
                provenance_json=json.dumps(item.provenance, ensure_ascii=False, sort_keys=True),
                embedding_ref=item.embedding_ref,
            )
            for item in summaries
        ]
        self._session.add_all(models)
        await self._session.flush()
        return summaries

    async def upsert_scope(
        self,
        summary: SummaryNode,
        *,
        canonical_identifier: bool = False,
        force_reembed: bool = False,
    ) -> SummaryUpsertResult:
        """Keep exactly one summary per scope and preserve embeddings when unchanged."""
        results = await self.upsert_scopes(
            [summary],
            canonical_identifier=canonical_identifier,
            force_reembed=force_reembed,
        )
        return results[0]

    async def upsert_scopes(
        self,
        summaries: list[SummaryNode],
        *,
        canonical_identifier: bool = False,
        force_reembed: bool = False,
    ) -> list[SummaryUpsertResult]:
        """Upsert distinct scopes with one lookup and one flush."""
        if not summaries:
            return []

        scope_keys = [(summary.scope_type, summary.scope_id) for summary in summaries]
        if len(set(scope_keys)) != len(scope_keys):
            raise ValueError("summary batch contains duplicate scopes")

        result = await self._session.execute(
            select(SummaryNodeModel)
            .where(
                tuple_(SummaryNodeModel.scope_type, SummaryNodeModel.scope_id).in_(
                    scope_keys
                )
            )
            .order_by(
                SummaryNodeModel.scope_type.asc(),
                SummaryNodeModel.scope_id.asc(),
                SummaryNodeModel.id.asc(),
            )
        )
        existing_by_scope: dict[tuple[str, str], list[SummaryNodeModel]] = {}
        for model in result.scalars().all():
            existing_by_scope.setdefault(
                (model.scope_type, model.scope_id), []
            ).append(model)

        upserted: list[tuple[SummaryNodeModel, bool, tuple[str, ...]]] = []
        for summary in summaries:
            existing = existing_by_scope.get(
                (summary.scope_type, summary.scope_id), []
            )
            desired_provenance = json.dumps(
                summary.provenance,
                ensure_ascii=False,
                sort_keys=True,
            )
            canonical = next(
                (item for item in existing if item.id == summary.id),
                None,
            )
            if canonical is None and existing and not canonical_identifier:
                canonical = existing[0]

            if canonical is None:
                canonical = SummaryNodeModel(
                    id=summary.id,
                    scope_type=summary.scope_type,
                    scope_id=summary.scope_id,
                    text=summary.text,
                    provenance_json=desired_provenance,
                    embedding_ref=summary.embedding_ref,
                )
                self._session.add(canonical)
                content_changed = True
            else:
                content_changed = (
                    canonical.text != summary.text
                    or (canonical.provenance_json or "{}") != desired_provenance
                )
                canonical.text = summary.text
                canonical.provenance_json = desired_provenance
                if content_changed or force_reembed:
                    canonical.embedding_ref = None

            removed_ids: list[str] = []
            for duplicate in existing:
                if duplicate is canonical:
                    continue
                removed_ids.append(duplicate.id)
                await self._session.delete(duplicate)
            upserted.append(
                (
                    canonical,
                    content_changed or force_reembed,
                    tuple(removed_ids),
                )
            )

        await self._session.flush()
        return [
            SummaryUpsertResult(
                summary=self._to_entity(canonical),
                content_changed=content_changed,
                removed_ids=removed_ids,
            )
            for canonical, content_changed, removed_ids in upserted
        ]

    async def list_by_scope(self, scope_type: str, scope_id: str) -> list[SummaryNode]:
        result = await self._session.execute(
            select(SummaryNodeModel).where(
                SummaryNodeModel.scope_type == scope_type,
                SummaryNodeModel.scope_id == scope_id,
            )
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_collection(self, collection_id: str) -> list[SummaryNode]:
        result = await self._session.execute(
            select(SummaryNodeModel).where(
                SummaryNodeModel.scope_type == "collection",
                SummaryNodeModel.scope_id == collection_id,
            )
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_document(self, document_id: str) -> list[SummaryNode]:
        result = await self._session.execute(
            select(SummaryNodeModel).where(
                SummaryNodeModel.scope_type == "document",
                SummaryNodeModel.scope_id == document_id,
            )
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_sections_by_document(self, document_id: str) -> list[SummaryNode]:
        result = await self._session.execute(
            select(SummaryNodeModel)
            .join(ChunkModel, ChunkModel.id == SummaryNodeModel.scope_id)
            .where(
                SummaryNodeModel.scope_type == "section",
                ChunkModel.document_id == document_id,
            )
            .order_by(ChunkModel.id.asc(), SummaryNodeModel.id.asc())
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_ids_for_document_cleanup(
        self,
        document_id: str,
        *,
        collection_id: str | None = None,
    ) -> list[str]:
        """Capture every summary ID invalidated by reparsing one document.

        A document retry invalidates its section/document summaries and, when the
        collection is supplied, the derived collection summary as well. Callers use
        these IDs to remove vector representations before deleting SQL rows.
        """
        section_scope_ids = select(ChunkModel.id).where(
            ChunkModel.document_id == document_id
        )
        predicates = [
            and_(
                SummaryNodeModel.scope_type == "document",
                SummaryNodeModel.scope_id == document_id,
            ),
            and_(
                SummaryNodeModel.scope_type == "section",
                SummaryNodeModel.scope_id.in_(section_scope_ids),
            ),
        ]
        if collection_id is not None:
            predicates.append(
                and_(
                    SummaryNodeModel.scope_type == "collection",
                    SummaryNodeModel.scope_id == collection_id,
                )
            )
        result = await self._session.execute(
            select(SummaryNodeModel.id).where(or_(*predicates))
        )
        return [str(summary_id) for summary_id in result.scalars().all()]

    async def list_ids_for_collection_cleanup(self, collection_id: str) -> list[str]:
        """Capture all summary IDs derived from a collection in one query."""
        document_scope_ids = select(DocumentModel.id).where(
            DocumentModel.collection_id == collection_id
        )
        section_scope_ids = (
            select(ChunkModel.id)
            .join(DocumentModel, DocumentModel.id == ChunkModel.document_id)
            .where(DocumentModel.collection_id == collection_id)
        )
        result = await self._session.execute(
            select(SummaryNodeModel.id).where(
                or_(
                    and_(
                        SummaryNodeModel.scope_type == "collection",
                        SummaryNodeModel.scope_id == collection_id,
                    ),
                    and_(
                        SummaryNodeModel.scope_type == "document",
                        SummaryNodeModel.scope_id.in_(document_scope_ids),
                    ),
                    and_(
                        SummaryNodeModel.scope_type == "section",
                        SummaryNodeModel.scope_id.in_(section_scope_ids),
                    ),
                )
            )
        )
        return [str(summary_id) for summary_id in result.scalars().all()]

    async def list_document_summaries_page(
        self,
        collection_id: str,
        *,
        limit: int,
        after: tuple[str, str] | None = None,
        ready_only: bool = True,
    ) -> list[SummaryNode]:
        """Read document summaries in bounded keyset pages."""
        if limit < 1:
            raise ValueError("limit must be positive")
        stmt = (
            select(SummaryNodeModel)
            .join(DocumentModel, DocumentModel.id == SummaryNodeModel.scope_id)
            .where(
                SummaryNodeModel.scope_type == "document",
                DocumentModel.collection_id == collection_id,
            )
        )
        if ready_only:
            stmt = stmt.where(DocumentModel.status == DocumentStatus.READY.value)
        if after is not None:
            scope_id, summary_id = after
            stmt = stmt.where(
                or_(
                    SummaryNodeModel.scope_id > scope_id,
                    and_(
                        SummaryNodeModel.scope_id == scope_id,
                        SummaryNodeModel.id > summary_id,
                    ),
                )
            )
        stmt = stmt.order_by(
            SummaryNodeModel.scope_id.asc(),
            SummaryNodeModel.id.asc(),
        ).limit(limit)
        result = await self._session.execute(stmt)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def get_by_ids(self, summary_ids: list[str]) -> list[SummaryNode]:
        if not summary_ids:
            return []
        result = await self._session.execute(
            select(SummaryNodeModel).where(SummaryNodeModel.id.in_(summary_ids))
        )
        by_id = {model.id: self._to_entity(model) for model in result.scalars().all()}
        return [by_id[sid] for sid in summary_ids if sid in by_id]

    async def mark_embedded(self, summary_ids: list[str], embedding_ref: str) -> None:
        if not summary_ids:
            return
        result = await self._session.execute(
            select(SummaryNodeModel).where(SummaryNodeModel.id.in_(summary_ids))
        )
        for model in result.scalars().all():
            model.embedding_ref = embedding_ref
        await self._session.flush()

    async def delete_by_scope(self, scope_type: str, scope_id: str) -> bool:
        result = await self._session.execute(
            delete(SummaryNodeModel).where(
                SummaryNodeModel.scope_type == scope_type,
                SummaryNodeModel.scope_id == scope_id,
            )
        )
        await self._session.flush()
        return result.rowcount > 0

    async def delete_by_ids(self, summary_ids: list[str]) -> int:
        """Delete an already-captured summary set idempotently."""
        if not summary_ids:
            return 0
        result = await self._session.execute(
            delete(SummaryNodeModel).where(SummaryNodeModel.id.in_(summary_ids))
        )
        await self._session.flush()
        return int(result.rowcount or 0)

    @staticmethod
    def _to_entity(model: SummaryNodeModel) -> SummaryNode:
        return SummaryNode(
            id=model.id,
            scope_type=model.scope_type,
            scope_id=model.scope_id,
            text=model.text,
            provenance=json.loads(model.provenance_json or "{}"),
            embedding_ref=model.embedding_ref,
        )

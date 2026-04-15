"""Retrieval orchestrator for phase 4 and 5."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlmodel.ext.asyncio.session import AsyncSession

from atenex_nova.application.policies.context_packing_policy import (
    ContextPackingPolicy,
    EvidencePack,
)
from atenex_nova.application.policies.query_routing_policy import QueryRoutingPolicy
from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.evidence_item import EvidenceItem
from atenex_nova.domain.entities.proposition import Proposition
from atenex_nova.domain.entities.query import Query
from atenex_nova.domain.entities.summary_node import SummaryNode
from atenex_nova.domain.repositories.vector_index import HybridIndex
from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import SqlPropositionRepository
from atenex_nova.infrastructure.db.repositories.sql_query_repo import SqlQueryRepository
from atenex_nova.infrastructure.db.repositories.sql_relation_repo import SqlRelationRepository
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository
from atenex_nova.infrastructure.embeddings.bm25_encoder import BM25SparseEncoder
from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.infrastructure.visual.colpali_adapter import ColPaliAdapter
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import StrictModeViolationError
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService

_TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)


@dataclass
class SearchHit:
    id: str
    source_type: str
    source_id: str
    document_id: str | None
    title: str
    snippet: str
    score: float
    rank: int
    page_number: int | None = None
    metadata: dict[str, str] | None = None


@dataclass
class SearchResult:
    query: Query
    hits: list[SearchHit]
    evidence_pack: EvidencePack


class RetrievalOrchestrator:
    """Coordinates query preprocessing, routing, retrieval, fusion and packing."""

    def __init__(
        self,
        session: AsyncSession,
        qdrant_adapter: HybridIndex | None = None,
        embedder: EmbeddingGemmaAdapter | None = None,
        visual_adapter: ColPaliAdapter | None = None,
        audit: PipelineAuditService | None = None,
    ) -> None:
        self._session = session
        self._qdrant = qdrant_adapter
        self._settings = get_settings()
        self._embedder = embedder or EmbeddingGemmaAdapter(
            dim=self._settings.embedding_dimensions,
            required=self._settings.embeddings_required,
        )
        self._visual = visual_adapter or ColPaliAdapter()
        self._router = QueryRoutingPolicy()
        self._packer = ContextPackingPolicy()
        self._audit = audit or PipelineAuditService(session=session)

    async def search(self, collection_id: str, query_text: str, mode: str = "auto") -> SearchResult:
        query_repo = SqlQueryRepository(self._session)
        doc_repo = SqlDocumentRepository(self._session)
        chunk_repo = SqlChunkRepository(self._session)
        proposition_repo = SqlPropositionRepository(self._session)
        summary_repo = SqlSummaryRepository(self._session)
        relation_repo = SqlRelationRepository(self._session)

        features = self._router.extract_features(query_text)
        route_mode = self._router.choose_mode(features) if mode == "auto" else mode
        route_mode_name = route_mode.value if hasattr(route_mode, "value") else str(route_mode)
        intent = self._router.classify_intent(features)
        query = Query(
            id=new_id(),
            collection_id=collection_id,
            text=query_text,
            normalized_text=features.normalized_text,
            language=features.language,
            intent=intent.value,
            route_mode=route_mode_name,
        )
        await query_repo.create(query)

        async with self._audit.step(
            run_id=query.id,
            entity_type="query",
            entity_id=query.id,
            pipeline="retrieval",
            stage="search",
            context={"collection_id": collection_id, "mode": mode, "route_mode": route_mode_name},
        ) as audit:
            documents = await doc_repo.list_by_collection(collection_id)
            document_titles = {document.id: document.title for document in documents}

            chunks = await chunk_repo.list_by_collection(collection_id)
            propositions = await proposition_repo.list_by_collection(collection_id)
            summaries = []
            for document in documents:
                summaries.extend(await summary_repo.list_by_document(document.id))
                for chunk in await chunk_repo.get_by_document(document.id):
                    summaries.extend(await summary_repo.list_by_scope("section", chunk.id))
            summaries.extend(await summary_repo.list_by_collection(collection_id))

            hits: list[SearchHit] = []
            async with self._audit.step(
                run_id=query.id,
                entity_type="query",
                entity_id=query.id,
                pipeline="retrieval",
                stage="score_chunks",
                context={"documents": len(documents), "chunks": len(chunks)},
            ) as step:
                chunk_hits = await self._score_chunks(query, chunks, document_titles)
                step.metrics(hit_count=len(chunk_hits), source="chunks")
                hits.extend(chunk_hits)

            async with self._audit.step(
                run_id=query.id,
                entity_type="query",
                entity_id=query.id,
                pipeline="retrieval",
                stage="score_propositions",
                context={"propositions": len(propositions)},
            ) as step:
                proposition_hits = await self._score_propositions(query, propositions, document_titles)
                step.metrics(hit_count=len(proposition_hits), source="propositions")
                hits.extend(proposition_hits)

            async with self._audit.step(
                run_id=query.id,
                entity_type="query",
                entity_id=query.id,
                pipeline="retrieval",
                stage="score_summaries",
                context={"summaries": len(summaries)},
            ) as step:
                summary_hits = self._score_summaries(query, summaries, document_titles)
                step.metrics(hit_count=len(summary_hits), source="summaries")
                hits.extend(summary_hits)

            if route_mode_name == "visual":
                async with self._audit.step(
                    run_id=query.id,
                    entity_type="query",
                    entity_id=query.id,
                    pipeline="retrieval",
                    stage="score_visual_pages",
                    context={"collection_id": collection_id},
                ) as step:
                    visual_hits = await self._score_visual_pages(collection_id, query, document_titles)
                    step.metrics(hit_count=len(visual_hits), source="visual_pages")
                    hits.extend(visual_hits)

            if route_mode_name == "multi_hop" and propositions:
                async with self._audit.step(
                    run_id=query.id,
                    entity_type="query",
                    entity_id=query.id,
                    pipeline="retrieval",
                    stage="expand_graph",
                    context={"seed_propositions": min(len(propositions), 3)},
                ) as step:
                    expanded = await relation_repo.expand([prop.id for prop in propositions[:3]], depth=2)
                    step.metrics(edge_count=len(expanded))
                    for edge in expanded:
                        hits.append(
                            SearchHit(
                                id=new_id(),
                                source_type="graph_edge",
                                source_id=edge.id,
                                document_id=None,
                                title="Graph expansion",
                                snippet=f"{edge.source_type}:{edge.source_id} -> {edge.relation} -> {edge.target_type}:{edge.target_id}",
                                score=edge.weight * 0.8,
                                rank=0,
                            )
                        )

            ranked_hits = self._rank_hits(hits, route_mode_name)
            audit.metrics(
                documents=len(documents),
                chunks=len(chunks),
                propositions=len(propositions),
                summaries=len(summaries),
                ranked_hits=len(ranked_hits),
                route_mode=route_mode_name,
                intent=intent.value,
            )
        evidence_items = [
            EvidenceItem(
                id=hit.id,
                query_id=query.id,
                source_type=hit.source_type,
                source_id=hit.source_id,
                score=hit.score,
                rank=index + 1,
                document_id=hit.document_id,
                page_number=hit.page_number,
                title=hit.title,
                snippet=hit.snippet,
                metadata=hit.metadata or {},
            )
            for index, hit in enumerate(ranked_hits)
        ]
        evidence_pack = self._packer.build(query.id, query.route_mode, evidence_items)
        self._enforce_strict_evidence(route_mode_name, evidence_pack.items)
        return SearchResult(query=query, hits=ranked_hits, evidence_pack=evidence_pack)

    def _enforce_strict_evidence(self, route_mode: str, evidence_items: list[EvidenceItem]) -> None:
        if not self._settings.strict_mode_enabled:
            return

        minimum_items = max(1, int(self._settings.min_evidence_items))
        if len(evidence_items) < minimum_items:
            raise StrictModeViolationError(
                message=(
                    f"strict mode requires at least {minimum_items} evidence items, "
                    f"got {len(evidence_items)}"
                ),
                code="INSUFFICIENT_EVIDENCE",
            )

        if route_mode == "visual" and self._settings.visual_required:
            has_visual = any(item.source_type == "visual_page" for item in evidence_items)
            if not has_visual:
                raise StrictModeViolationError(
                    message="strict visual mode requires at least one visual evidence item",
                    code="VISUAL_EVIDENCE_REQUIRED",
                )

    async def _score_chunks(
        self,
        query: Query,
        chunks: list[Chunk],
        document_titles: dict[str, str],
    ) -> list[SearchHit]:
        texts = [chunk.text for chunk in chunks]
        sparse_scores = BM25SparseEncoder().score(query.normalized_text or query.text, texts) if texts else []
        query_vector = (await self._embedder.embed([query.normalized_text or query.text]))[0]
        candidate_hits: list[SearchHit] = []
        for index, chunk in enumerate(chunks):
            dense_score = self._cosine(query_vector, (await self._embedder.embed([chunk.text]))[0])
            score = 0.6 * dense_score + 0.4 * (sparse_scores[index] if index < len(sparse_scores) else 0.0)
            candidate_hits.append(
                SearchHit(
                    id=chunk.id,
                    source_type="chunk",
                    source_id=chunk.id,
                    document_id=chunk.document_id,
                    title=document_titles.get(chunk.document_id, ""),
                    snippet=chunk.summary or chunk.text[:280],
                    score=score,
                    rank=0,
                )
            )
        return candidate_hits

    async def _score_propositions(self, query: Query, propositions: list[Proposition], document_titles: dict[str, str]) -> list[SearchHit]:
        if not propositions:
            return []
        texts = [prop.text for prop in propositions]
        sparse_scores = BM25SparseEncoder().score(query.normalized_text or query.text, texts)
        query_vector = (await self._embedder.embed([query.normalized_text or query.text]))[0]
        candidate_hits: list[SearchHit] = []
        for index, proposition in enumerate(propositions):
            dense_score = self._cosine(query_vector, (await self._embedder.embed([proposition.text]))[0])
            score = 0.65 * dense_score + 0.35 * (sparse_scores[index] if index < len(sparse_scores) else 0.0)
            candidate_hits.append(
                SearchHit(
                    id=proposition.id,
                    source_type="proposition",
                    source_id=proposition.id,
                    document_id=proposition.document_id,
                    title=document_titles.get(proposition.document_id, ""),
                    snippet=proposition.text,
                    score=score,
                    rank=0,
                )
            )
        return candidate_hits

    def _score_summaries(self, query: Query, summaries: list[SummaryNode], document_titles: dict[str, str]) -> list[SearchHit]:
        if not summaries:
            return []
        texts = [summary.text for summary in summaries]
        sparse_scores = BM25SparseEncoder().score(query.normalized_text or query.text, texts)
        hits: list[SearchHit] = []
        for index, summary in enumerate(summaries):
            score = 0.7 * (sparse_scores[index] if index < len(sparse_scores) else 0.0) + 0.2
            hits.append(
                SearchHit(
                    id=summary.id,
                    source_type="summary",
                    source_id=summary.id,
                    document_id=summary.scope_id if summary.scope_type == "document" else None,
                    title=document_titles.get(summary.scope_id, "Collection summary"),
                    snippet=summary.text,
                    score=score,
                    rank=0,
                )
            )
        return hits

    def _rank_hits(self, hits: list[SearchHit], route_mode: object) -> list[SearchHit]:
        route = route_mode.value if hasattr(route_mode, "value") else str(route_mode)
        boosts = {
            "exact": {"chunk": 1.15, "proposition": 1.1, "summary": 0.9},
            "factual_local": {"chunk": 1.1, "proposition": 1.15, "summary": 0.85},
            "multi_hop": {"chunk": 0.95, "proposition": 1.2, "summary": 1.0},
            "global": {"chunk": 0.9, "proposition": 1.0, "summary": 1.25},
            "argumentative": {"chunk": 1.0, "proposition": 1.2, "summary": 0.95},
            "visual": {"chunk": 1.05, "proposition": 0.95, "summary": 1.1, "visual_page": 1.3},
        }.get(route, {})
        for hit in hits:
            hit.score *= boosts.get(hit.source_type, 1.0)
            if route == "exact" and query_has_phrase(hit.snippet, hit.title):
                hit.score += 0.2
        ranked = sorted(hits, key=lambda item: item.score, reverse=True)
        for index, hit in enumerate(ranked, start=1):
            hit.rank = index
        return ranked[:12]

    async def _score_visual_pages(
        self, collection_id: str, query: Query, document_titles: dict[str, str]
    ) -> list[SearchHit]:
        pages = await self._visual.search(collection_id, query.normalized_text or query.text, limit=8)
        hits: list[SearchHit] = []
        for page in pages:
            metadata = page.get("metadata") or {}
            hits.append(
                SearchHit(
                    id=str(page.get("id")),
                    source_type="visual_page",
                    source_id=str(page.get("id")),
                    document_id=str(page.get("document_id") or "") or None,
                    title=str(page.get("title") or document_titles.get(str(page.get("document_id") or ""), "Visual page")),
                    snippet=str(page.get("text") or page.get("snippet") or "")[:280],
                    score=float(page.get("score", 0.0)),
                    rank=0,
                    page_number=page.get("page_number"),
                    metadata={k: str(v) for k, v in metadata.items()} if isinstance(metadata, dict) else None,
                )
            )
        return hits

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        if not left or not right:
            return 0.0
        limit = min(len(left), len(right))
        numerator = sum(left[i] * right[i] for i in range(limit))
        left_norm = sum(value * value for value in left[:limit]) ** 0.5
        right_norm = sum(value * value for value in right[:limit]) ** 0.5
        if not left_norm or not right_norm:
            return 0.0
        return float(numerator / (left_norm * right_norm))


def query_has_phrase(snippet: str, title: str) -> bool:
    lower = f"{snippet} {title}".lower()
    return any(marker in lower for marker in ("exact", "uuid", "código", "definition", "defines"))

"""Retrieval orchestration for hybrid, route-aware search."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from atenex_nova.application.policies.collection_publication_policy import (
    CollectionPublicationPolicy,
    CollectionPublicationReport,
)
from atenex_nova.application.policies.context_packing_policy import (
    ContextPackingPolicy,
    EvidencePack,
)
from atenex_nova.application.policies.indexing_policy import dense_goes_to_qdrant
from atenex_nova.application.policies.multi_query_retrieval_policy import (
    MultiQueryRetrievalPolicy,
    RetrievalQueryVariant,
)
from atenex_nova.application.policies.query_routing_policy import QueryRoutingPolicy
from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.entities.evidence_item import EvidenceItem
from atenex_nova.domain.entities.proposition import Proposition
from atenex_nova.domain.entities.query import Query
from atenex_nova.domain.entities.summary_node import SummaryNode
from atenex_nova.domain.repositories.vector_index import HybridIndex
from atenex_nova.domain.value_objects.identifiers import JobType, new_id
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import SqlPropositionRepository
from atenex_nova.infrastructure.db.repositories.sql_query_repo import SqlQueryRepository
from atenex_nova.infrastructure.db.repositories.sql_relation_repo import SqlRelationRepository
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository
from atenex_nova.infrastructure.embeddings.bm25_encoder import (
    BM25SparseEncoder,
    StableSparseEncoder,
    tokenize,
)
from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.infrastructure.embeddings.reranker_adapter import RerankerAdapter
from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter
from atenex_nova.infrastructure.visual.colpali_adapter import VisualPageRetriever
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import EntityNotFoundError, StrictModeViolationError
from atenex_nova.shared.logging.logger import get_logger
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService

logger = get_logger(__name__)

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
    metadata: dict[str, object] | None = None


@dataclass
class SearchResult:
    query: Query
    hits: list[SearchHit]
    evidence_pack: EvidencePack
    route_reason: str


class RetrievalOrchestrator:
    """Coordinates query preprocessing, routing, retrieval, fusion and packing."""

    def __init__(
        self,
        session: AsyncSession,
        qdrant_adapter: HybridIndex | None = None,
        embedder: EmbeddingGemmaAdapter | None = None,
        visual_adapter: VisualPageRetriever | None = None,
        audit: PipelineAuditService | None = None,
        reranker: RerankerAdapter | None = None,
    ) -> None:
        self._session = session
        self._settings = get_settings()
        if qdrant_adapter is None:
            qdrant_endpoint = urlparse(self._settings.qdrant_url)
            self._qdrant: HybridIndex = QdrantAdapter(
                host=qdrant_endpoint.hostname or "localhost",
                port=qdrant_endpoint.port or 6333,
                required=self._settings.qdrant_required,
            )
        else:
            self._qdrant = qdrant_adapter
        self._embedder = embedder or EmbeddingGemmaAdapter(
            dim=self._settings.embedding_dimensions,
            required=self._settings.embeddings_required,
        )
        self._visual = visual_adapter or VisualPageRetriever()
        self._router = QueryRoutingPolicy()
        self._multi_query = MultiQueryRetrievalPolicy()
        self._publication = CollectionPublicationPolicy()
        self._sparse_encoder: StableSparseEncoder | None = None
        self._packer = ContextPackingPolicy()
        self._audit = audit or PipelineAuditService(session=session)
        from atenex_nova.infrastructure.indexes.candidate_index_factory import (
            build_candidate_index,
        )

        self._candidate_index = build_candidate_index(session)
        self._reranker = reranker or RerankerAdapter(required=self._settings.reranker_required)

    def _use_candidate_index(self) -> bool:
        # Qdrant is the scalable dense path. The exhaustive SQL/PurePy estimator is
        # retained only as an offline fallback and has its own hard cardinality cap.
        return not (dense_goes_to_qdrant(self._settings) and self._qdrant.is_available)

    async def search(
        self,
        collection_id: str,
        query_text: str,
        mode: str = "auto",
        *,
        retrieval_query_text: str | None = None,
        retrieval_context_messages: int = 0,
    ) -> SearchResult:
        query_repo = SqlQueryRepository(self._session)
        collection_repo = SqlCollectionRepository(self._session)
        doc_repo = SqlDocumentRepository(self._session)
        chunk_repo = SqlChunkRepository(self._session)
        proposition_repo = SqlPropositionRepository(self._session)
        summary_repo = SqlSummaryRepository(self._session)
        relation_repo = SqlRelationRepository(self._session)

        features = self._router.extract_features(query_text)
        collection = await collection_repo.get_by_id(collection_id)
        if collection is None:
            raise EntityNotFoundError("Collection", collection_id)
        all_documents = await self._list_all_documents(doc_repo, collection_id)
        rebuild_active = await SqlJobRepository(self._session).has_active(
            collection_id,
            {JobType.REBUILD_COLLECTION},
        )
        publication = self._publication.evaluate(
            collection_id=collection_id,
            documents=all_documents,
            rebuild_active=rebuild_active,
        )
        documents = [
            document
            for document in all_documents
            if document.id in publication.ready_document_ids
        ]
        language = self._router.resolve_language(
            features.language,
            collection.language_profile,
        )
        route_mode = self._router.choose_mode(features) if mode == "auto" else mode
        route_mode_name = route_mode.value if hasattr(route_mode, "value") else str(route_mode)
        route_reason = self._router.explain_route(features, route_mode_name)
        if publication.failed_count:
            route_reason = (
                f"{route_reason} Corpus gap: {publication.failed_count} failed "
                "document(s) were excluded."
            )
        intent = self._router.classify_intent(features)
        retrieval_text = (retrieval_query_text or "").strip()
        query = Query(
            id=new_id(),
            collection_id=collection_id,
            text=query_text,
            normalized_text=features.normalized_text,
            language=language,
            intent=intent.value,
            route_mode=route_mode_name,
            retrieval_text=retrieval_text,
            retrieval_context_messages=(
                max(0, retrieval_context_messages) if retrieval_text else 0
            ),
        )
        multi_query_plan = self._multi_query.build(
            original_text=query.text,
            retrieval_text=query.retrieval_query,
            route_mode=route_mode_name,
        )
        planned_variants = list(multi_query_plan.variants)
        variant_fallback_reason: str | None = None
        if len(planned_variants) > 1 and not self._qdrant.is_available:
            retrieval_variants = planned_variants[:1]
            variant_fallback_reason = "qdrant_unavailable_single_local_query"
        else:
            retrieval_variants = planned_variants
        await query_repo.create(query)
        logger.info(
            f"Search started: '{query_text}' | Collection: {collection_id} | Mode: {mode} "
            f"-> Routed Mode: {route_mode_name} | Intent: {intent.value} | Language: {language}"
        )

        async with self._audit.step(
            run_id=query.id,
            entity_type="query",
            entity_id=query.id,
            pipeline="retrieval",
            stage="search",
            context={
                "collection_id": collection_id,
                "mode": mode,
                "route_mode": route_mode_name,
                "route_reason": route_reason,
                "retrieval_query_contextualized": bool(query.retrieval_text),
                "retrieval_context_messages": query.retrieval_context_messages,
                "multi_query_reason": multi_query_plan.reason,
                "multi_query_planned_variants": [
                    variant.audit_dict() for variant in planned_variants
                ],
                "multi_query_executed_variants": [
                    variant.audit_dict() for variant in retrieval_variants
                ],
                "multi_query_fallback_reason": variant_fallback_reason,
                "collection_publication": publication.audit_dict(),
                "dense_candidate_backend": (
                    "purepy"
                    if self._use_candidate_index()
                    else ("qdrant" if dense_goes_to_qdrant(self._settings) else "none")
                ),
            },
        ) as audit:
            document_titles = {document.id: document.title for document in documents}
            if not self._qdrant.is_available:
                chunks = await chunk_repo.list_by_collection(collection_id)
                propositions = await proposition_repo.list_by_collection(collection_id)
                summaries = await self._load_summaries(summary_repo, documents, chunk_repo, chunks, collection_id)
            else:
                chunks = []
                propositions = []
                summaries = []
            multi_query_started = time.perf_counter()
            variant_vectors: list[list[float]] = []
            embedding_variant_latencies: list[dict[str, object]] = []
            for variant in retrieval_variants:
                embedding_started = time.perf_counter()
                variant_vectors.append(await self._embedder.embed_query(variant.text))
                embedding_variant_latencies.append(
                    {
                        **variant.audit_dict(),
                        "latency_ms": round(
                            (time.perf_counter() - embedding_started) * 1000,
                            2,
                        ),
                    }
                )

            hits: list[SearchHit] = []

            async with self._audit.step(
                run_id=query.id,
                entity_type="query",
                entity_id=query.id,
                pipeline="retrieval",
                stage="score_chunks",
                context={"documents": len(documents), "chunks": len(chunks)},
            ) as step:
                chunk_variant_results: list[
                    tuple[RetrievalQueryVariant, list[SearchHit], float]
                ] = []
                chunk_variant_metrics: list[dict[str, object]] = []
                for variant, query_vector in zip(
                    retrieval_variants,
                    variant_vectors,
                    strict=True,
                ):
                    if variant.index > 0 and not self._qdrant.is_available:
                        variant_fallback_reason = "qdrant_failed_single_local_query"
                        break
                    dense_metrics = self._new_dense_metrics()
                    variant_started = time.perf_counter()
                    variant_hits = await self._score_chunks(
                        query,
                        query_vector,
                        chunks,
                        document_titles,
                        route_mode_name,
                        query_text=variant.text,
                        allow_local_fallback=variant.index == 0,
                        dense_metrics=dense_metrics,
                    )
                    latency_ms = round(
                        (time.perf_counter() - variant_started) * 1000,
                        2,
                    )
                    chunk_variant_results.append((variant, variant_hits, latency_ms))
                    chunk_variant_metrics.append(
                        {
                            **variant.audit_dict(),
                            "latency_ms": latency_ms,
                            "hit_count": len(variant_hits),
                            **dense_metrics,
                        }
                    )
                chunk_hits = self._fuse_query_variant_hits(
                    chunk_variant_results,
                    limit=20,
                )
                step.metrics(
                    hit_count=len(chunk_hits),
                    source="chunks",
                    variant_runs=chunk_variant_metrics,
                    dense_hits=sum(
                        int(metrics.get("dense_hits") or 0)
                        for metrics in chunk_variant_metrics
                    ),
                    dense_latency_ms=round(
                        sum(
                            float(metrics.get("dense_latency_ms") or 0.0)
                            for metrics in chunk_variant_metrics
                        ),
                        2,
                    ),
                )
                hits.extend(chunk_hits)

            if len(retrieval_variants) > 1 and not self._qdrant.is_available:
                retrieval_variants = retrieval_variants[:1]
                variant_vectors = variant_vectors[:1]
                variant_fallback_reason = "qdrant_failed_single_local_query"

            async with self._audit.step(
                run_id=query.id,
                entity_type="query",
                entity_id=query.id,
                pipeline="retrieval",
                stage="score_propositions",
                context={"propositions": len(propositions)},
            ) as step:
                proposition_variant_results: list[
                    tuple[RetrievalQueryVariant, list[SearchHit], float]
                ] = []
                proposition_variant_metrics: list[dict[str, object]] = []
                for variant, query_vector in zip(
                    retrieval_variants,
                    variant_vectors,
                    strict=True,
                ):
                    if variant.index > 0 and not self._qdrant.is_available:
                        variant_fallback_reason = "qdrant_failed_single_local_query"
                        break
                    variant_started = time.perf_counter()
                    variant_hits = await self._score_propositions(
                        query,
                        query_vector,
                        propositions,
                        document_titles,
                        route_mode_name,
                        query_text=variant.text,
                        allow_local_fallback=variant.index == 0,
                    )
                    latency_ms = round(
                        (time.perf_counter() - variant_started) * 1000,
                        2,
                    )
                    proposition_variant_results.append(
                        (variant, variant_hits, latency_ms)
                    )
                    proposition_variant_metrics.append(
                        {
                            **variant.audit_dict(),
                            "latency_ms": latency_ms,
                            "hit_count": len(variant_hits),
                        }
                    )
                proposition_hits = self._fuse_query_variant_hits(
                    proposition_variant_results,
                    limit=20,
                )
                step.metrics(
                    hit_count=len(proposition_hits),
                    source="propositions",
                    variant_runs=proposition_variant_metrics,
                )
                hits.extend(proposition_hits)

            if len(retrieval_variants) > 1 and not self._qdrant.is_available:
                retrieval_variants = retrieval_variants[:1]
                variant_vectors = variant_vectors[:1]
                variant_fallback_reason = "qdrant_failed_single_local_query"

            async with self._audit.step(
                run_id=query.id,
                entity_type="query",
                entity_id=query.id,
                pipeline="retrieval",
                stage="score_summaries",
                context={"summaries": len(summaries)},
            ) as step:
                summary_variant_results: list[
                    tuple[RetrievalQueryVariant, list[SearchHit], float]
                ] = []
                summary_variant_metrics: list[dict[str, object]] = []
                for variant, query_vector in zip(
                    retrieval_variants,
                    variant_vectors,
                    strict=True,
                ):
                    if variant.index > 0 and not self._qdrant.is_available:
                        variant_fallback_reason = "qdrant_failed_single_local_query"
                        break
                    variant_started = time.perf_counter()
                    variant_hits = await self._score_summaries(
                        query,
                        query_vector,
                        summaries,
                        document_titles,
                        route_mode_name,
                        query_text=variant.text,
                        allow_local_fallback=variant.index == 0,
                    )
                    latency_ms = round(
                        (time.perf_counter() - variant_started) * 1000,
                        2,
                    )
                    summary_variant_results.append(
                        (variant, variant_hits, latency_ms)
                    )
                    summary_variant_metrics.append(
                        {
                            **variant.audit_dict(),
                            "latency_ms": latency_ms,
                            "hit_count": len(variant_hits),
                        }
                    )
                summary_hits = self._fuse_query_variant_hits(
                    summary_variant_results,
                    limit=16,
                )
                step.metrics(
                    hit_count=len(summary_hits),
                    source="summaries",
                    variant_runs=summary_variant_metrics,
                )
                hits.extend(summary_hits)

            if len(retrieval_variants) > 1 and not self._qdrant.is_available:
                retrieval_variants = retrieval_variants[:1]
                variant_vectors = variant_vectors[:1]
                variant_fallback_reason = "qdrant_failed_single_local_query"

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

            if route_mode_name == "multi_hop" and not propositions:
                propositions = await proposition_repo.list_by_collection(collection_id)

            if route_mode_name == "multi_hop" and propositions:
                async with self._audit.step(
                    run_id=query.id,
                    entity_type="query",
                    entity_id=query.id,
                    pipeline="retrieval",
                    stage="expand_graph",
                    context={"seed_propositions": min(len(proposition_hits), 5)},
                ) as step:
                    allowed_relations = None
                    if intent.value == "argumentative":
                        allowed_relations = ["contradicts", "supports"]
                    elif intent.value == "factual":
                        allowed_relations = ["defines", "elaborates", "appears_in"]

                    seed_ids = [hit.source_id for hit in proposition_hits[:5]]
                    if seed_ids:
                        expanded = await relation_repo.expand(
                            seed_ids,
                            depth=2,
                            allowed_relations=allowed_relations
                        )
                    else:
                        expanded = []
                    step.metrics(edge_count=len(expanded))

                    proposition_by_id = {prop.id: prop for prop in propositions}
                    relation_verbs = {
                        "contradicts": "contradice a",
                        "supports": "respalda/apoya a",
                        "elaborates": "se detalla/elabora en",
                        "defines": "define a",
                        "appears_in": "aparece en",
                        "mentions": "menciona a",
                    }

                    logger.info(f"Expanding graph: found {len(expanded)} relation edges from seeds {seed_ids}")

                    for edge in expanded:
                        source_text = ""
                        doc_id = None
                        if edge.source_type == "proposition":
                            prop = proposition_by_id.get(edge.source_id)
                            if prop:
                                source_text = f"'{prop.text}'"
                                doc_id = prop.document_id
                            else:
                                source_text = f"Proposición {edge.source_id[:8]}"
                        else:
                            source_text = f"{edge.source_type} {edge.source_id[:8]}"

                        target_text = ""
                        if edge.target_type == "proposition":
                            prop = proposition_by_id.get(edge.target_id)
                            if prop:
                                target_text = f"'{prop.text}'"
                                if not doc_id:
                                    doc_id = prop.document_id
                            else:
                                target_text = f"Proposición {edge.target_id[:8]}"
                        elif edge.target_type == "document":
                            doc_title = document_titles.get(edge.target_id)
                            if doc_title:
                                target_text = f"Documento '{doc_title}'"
                            else:
                                target_text = f"Documento {edge.target_id[:8]}"
                        else:
                            target_text = f"{edge.target_type} {edge.target_id[:8]}"

                        verb = relation_verbs.get(edge.relation, edge.relation)
                        snippet = f"Relación: la afirmación {source_text} {verb} {target_text}."
                        logger.debug(f"Resolved edge {edge.id}: {source_text} -> {edge.relation} -> {target_text} (doc={doc_id})")

                        hits.append(
                            SearchHit(
                                id=new_id(),
                                source_type="graph_edge",
                                source_id=edge.id,
                                document_id=doc_id,
                                title="Graph expansion",
                                snippet=snippet,
                                score=max(0.1, edge.weight * 0.8),
                                rank=0,
                                metadata={
                                    "relation": edge.relation,
                                    "weight": edge.weight,
                                    "source_entity": edge.source_id,
                                    "target_entity": edge.target_id,
                                },
                            )
                        )

            validated_hits, discarded_evidence = await self._validate_published_hits(
                collection_id=collection_id,
                hits=hits,
                publication=publication,
                document_titles=document_titles,
                query_text=query.retrieval_query,
            )
            ranked_hits = self._rank_hits(
                query,
                validated_hits,
                route_mode_name,
                limit=self._result_limit(route_mode_name),
            )
            execution_metadata = {
                "reason": multi_query_plan.reason,
                "planned_count": len(planned_variants),
                "executed_count": len(retrieval_variants),
                "fallback_reason": variant_fallback_reason,
                "executed_variants": [
                    variant.audit_dict() for variant in retrieval_variants
                ],
            }
            for hit in ranked_hits:
                metadata = dict(hit.metadata or {})
                metadata["retrieval_query_plan"] = execution_metadata
                metadata["collection_publication"] = publication.audit_dict()
                hit.metadata = metadata
            audit.metrics(
                documents=len(documents),
                failed_documents=publication.failed_count,
                document_statuses=publication.status_counts,
                chunks=len(chunks),
                propositions=len(propositions),
                summaries=len(summaries),
                evidence_candidates=len(hits),
                evidence_validated=len(validated_hits),
                evidence_discarded_total=sum(discarded_evidence.values()),
                evidence_discarded_by_reason=discarded_evidence,
                ranked_hits=len(ranked_hits),
                route_mode=route_mode_name,
                intent=intent.value,
                retrieval_query_contextualized=bool(query.retrieval_text),
                retrieval_context_messages=query.retrieval_context_messages,
                multi_query_planned_count=len(planned_variants),
                multi_query_executed_count=len(retrieval_variants),
                multi_query_executed_variants=[
                    variant.audit_dict() for variant in retrieval_variants
                ],
                multi_query_embedding_variants=embedding_variant_latencies,
                multi_query_fallback_reason=variant_fallback_reason,
                multi_query_latency_ms=round(
                    (time.perf_counter() - multi_query_started) * 1000,
                    2,
                ),
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
        return SearchResult(query=query, hits=ranked_hits, evidence_pack=evidence_pack, route_reason=route_reason)

    async def _validate_published_hits(
        self,
        *,
        collection_id: str,
        hits: list[SearchHit],
        publication: CollectionPublicationReport,
        document_titles: dict[str, str],
        query_text: str,
    ) -> tuple[list[SearchHit], dict[str, int]]:
        """Rehydrate retrieved evidence from SQL and drop unpublished sources.

        Qdrant and the candidate index are retrieval accelerators, not authorities.
        Text, ownership and publication state come from the current SQL transaction.
        """
        from atenex_nova.infrastructure.db.models.tables import (
            ChunkModel,
            DocumentModel,
            PropositionModel,
            RelationEdgeModel,
            SummaryNodeModel,
        )

        ready_document_ids = publication.ready_document_ids
        chunk_ids = {hit.source_id for hit in hits if hit.source_type == "chunk"}
        proposition_ids = {
            hit.source_id for hit in hits if hit.source_type == "proposition"
        }
        summary_ids = {hit.source_id for hit in hits if hit.source_type == "summary"}
        graph_edge_ids = {
            hit.source_id for hit in hits if hit.source_type == "graph_edge"
        }

        chunk_models: dict[str, ChunkModel] = {}
        if chunk_ids:
            result = await self._session.execute(
                select(ChunkModel)
                .join(DocumentModel, DocumentModel.id == ChunkModel.document_id)
                .where(
                    ChunkModel.id.in_(chunk_ids),
                    DocumentModel.collection_id == collection_id,
                    DocumentModel.status == "ready",
                )
            )
            chunk_models = {model.id: model for model in result.scalars().all()}

        proposition_models: dict[str, PropositionModel] = {}
        if proposition_ids:
            result = await self._session.execute(
                select(PropositionModel)
                .join(
                    DocumentModel,
                    DocumentModel.id == PropositionModel.document_id,
                )
                .where(
                    PropositionModel.id.in_(proposition_ids),
                    DocumentModel.collection_id == collection_id,
                    DocumentModel.status == "ready",
                )
            )
            proposition_models = {
                model.id: model for model in result.scalars().all()
            }

        summary_models: dict[str, SummaryNodeModel] = {}
        section_documents: dict[str, str] = {}
        if summary_ids:
            result = await self._session.execute(
                select(SummaryNodeModel).where(SummaryNodeModel.id.in_(summary_ids))
            )
            summary_models = {model.id: model for model in result.scalars().all()}
            section_scope_ids = {
                model.scope_id
                for model in summary_models.values()
                if model.scope_type == "section"
            }
            if section_scope_ids:
                section_result = await self._session.execute(
                    select(ChunkModel.id, ChunkModel.document_id)
                    .join(DocumentModel, DocumentModel.id == ChunkModel.document_id)
                    .where(
                        ChunkModel.id.in_(section_scope_ids),
                        DocumentModel.collection_id == collection_id,
                        DocumentModel.status == "ready",
                    )
                )
                section_documents = {
                    str(chunk_id): str(document_id)
                    for chunk_id, document_id in section_result.all()
                }

        graph_edges: dict[str, RelationEdgeModel] = {}
        edge_proposition_documents: dict[str, str] = {}
        if graph_edge_ids:
            result = await self._session.execute(
                select(RelationEdgeModel).where(
                    RelationEdgeModel.id.in_(graph_edge_ids)
                )
            )
            graph_edges = {model.id: model for model in result.scalars().all()}
            edge_proposition_ids = {
                entity_id
                for edge in graph_edges.values()
                for entity_type, entity_id in (
                    (edge.source_type, edge.source_id),
                    (edge.target_type, edge.target_id),
                )
                if entity_type == "proposition"
            }
            if edge_proposition_ids:
                edge_prop_result = await self._session.execute(
                    select(PropositionModel.id, PropositionModel.document_id)
                    .join(
                        DocumentModel,
                        DocumentModel.id == PropositionModel.document_id,
                    )
                    .where(
                        PropositionModel.id.in_(edge_proposition_ids),
                        DocumentModel.collection_id == collection_id,
                        DocumentModel.status == "ready",
                    )
                )
                edge_proposition_documents = {
                    str(proposition_id): str(document_id)
                    for proposition_id, document_id in edge_prop_result.all()
                }

        validated: list[SearchHit] = []
        discarded: dict[str, int] = {}

        def reject(reason: str) -> None:
            discarded[reason] = discarded.get(reason, 0) + 1

        for hit in hits:
            if (
                hit.source_type in {"chunk", "proposition", "summary"}
                and self._uses_qdrant_payload(hit)
                and (hit.metadata or {}).get("embedding_contract")
                != self._settings.embedding_contract_fingerprint
            ):
                reject("incompatible_embedding_contract")
                continue

            if hit.source_type == "chunk":
                model = chunk_models.get(hit.source_id)
                if model is None:
                    reject("chunk_not_published")
                    continue
                metadata = {
                    **dict(hit.metadata or {}),
                    **self._json_mapping(model.metadata_json),
                    "document_id": model.document_id,
                    "source_text": model.text,
                    "publication_validation": "sql_ready",
                }
                content = self._clean_chunk_content(model.text)
                hit.id = model.id
                hit.source_id = model.id
                hit.document_id = model.document_id
                hit.title = document_titles.get(model.document_id, "")
                hit.snippet = (
                    self._best_chunk_excerpt(content, query_text)
                    if content
                    else (model.summary or model.text[:280])
                )
                hit.page_number = self._metadata_page_number(metadata)
                hit.metadata = metadata
                validated.append(hit)
                continue

            if hit.source_type == "proposition":
                model = proposition_models.get(hit.source_id)
                if model is None:
                    reject("proposition_not_published")
                    continue
                hit.id = model.id
                hit.source_id = model.id
                hit.document_id = model.document_id
                hit.title = document_titles.get(model.document_id, "")
                hit.snippet = model.text
                hit.metadata = {
                    **dict(hit.metadata or {}),
                    "document_id": model.document_id,
                    "source_chunk_id": model.source_chunk_id,
                    "kind": model.kind,
                    "source_text": model.text,
                    "publication_validation": "sql_ready",
                }
                validated.append(hit)
                continue

            if hit.source_type == "summary":
                model = summary_models.get(hit.source_id)
                if model is None:
                    reject("summary_missing")
                    continue
                document_id: str | None
                if model.scope_type == "document":
                    document_id = model.scope_id
                    if document_id not in ready_document_ids:
                        reject("summary_document_not_published")
                        continue
                elif model.scope_type == "section":
                    document_id = section_documents.get(model.scope_id)
                    if document_id is None:
                        reject("summary_section_not_published")
                        continue
                elif model.scope_type == "collection":
                    document_id = None
                    if model.scope_id != collection_id:
                        reject("summary_collection_mismatch")
                        continue
                else:
                    reject("summary_scope_unsupported")
                    continue
                hit.id = model.id
                hit.source_id = model.id
                hit.document_id = document_id
                hit.title = (
                    document_titles.get(document_id, "")
                    if document_id
                    else "Collection summary"
                )
                hit.snippet = model.text
                hit.metadata = {
                    **dict(hit.metadata or {}),
                    "scope_type": model.scope_type,
                    "scope_id": model.scope_id,
                    "provenance": self._json_mapping(model.provenance_json),
                    "source_text": model.text,
                    "publication_validation": "sql_ready",
                }
                validated.append(hit)
                continue

            if hit.source_type == "visual_page":
                if not hit.document_id or hit.document_id not in ready_document_ids:
                    reject("visual_document_not_published")
                    continue
                hit.title = document_titles.get(hit.document_id, hit.title)
                hit.metadata = {
                    **dict(hit.metadata or {}),
                    "publication_validation": "document_ready",
                }
                validated.append(hit)
                continue

            if hit.source_type == "graph_edge":
                edge = graph_edges.get(hit.source_id)
                if edge is None:
                    reject("graph_edge_missing")
                    continue
                source_document = self._published_graph_endpoint_document(
                    edge.source_type,
                    edge.source_id,
                    ready_document_ids,
                    edge_proposition_documents,
                )
                target_document = self._published_graph_endpoint_document(
                    edge.target_type,
                    edge.target_id,
                    ready_document_ids,
                    edge_proposition_documents,
                    allow_concept=True,
                )
                if source_document is None or target_document is None:
                    reject("graph_edge_not_published")
                    continue
                hit.document_id = (
                    None if source_document == "concept" else source_document
                )
                hit.metadata = {
                    **dict(hit.metadata or {}),
                    "relation": edge.relation,
                    "weight": edge.weight,
                    "source_entity": edge.source_id,
                    "target_entity": edge.target_id,
                    "publication_validation": "sql_ready",
                }
                validated.append(hit)
                continue

            reject("unsupported_source_type")

        return validated, dict(sorted(discarded.items()))

    @staticmethod
    def _uses_qdrant_payload(hit: SearchHit) -> bool:
        metadata = hit.metadata or {}
        stage = metadata.get("retrieval_stage")
        if isinstance(stage, str) and "qdrant" in stage:
            return True
        stages = metadata.get("retrieval_stages")
        return isinstance(stages, list) and any(
            isinstance(item, str) and "qdrant" in item for item in stages
        )

    @staticmethod
    def _published_graph_endpoint_document(
        entity_type: str,
        entity_id: str,
        ready_document_ids: frozenset[str],
        proposition_documents: dict[str, str],
        *,
        allow_concept: bool = False,
    ) -> str | None:
        if entity_type == "proposition":
            return proposition_documents.get(entity_id)
        if entity_type == "document":
            return entity_id if entity_id in ready_document_ids else None
        if allow_concept and entity_type == "concept" and entity_id:
            return "concept"
        return None

    @staticmethod
    def _json_mapping(raw: str | None) -> dict[str, object]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _metadata_page_number(metadata: dict[str, object]) -> int | None:
        page_numbers = metadata.get("page_numbers")
        if isinstance(page_numbers, list) and page_numbers:
            first = page_numbers[0]
            if isinstance(first, int):
                return first
        return None

    @staticmethod
    async def _list_all_documents(
        repository: SqlDocumentRepository,
        collection_id: str,
    ) -> list[Document]:
        documents: list[Document] = []
        async for page in repository.iter_by_collection_pages(collection_id):
            documents.extend(page)
        return documents

    async def _load_summaries(
        self,
        summary_repo: SqlSummaryRepository,
        documents: list[Document],
        chunk_repo: SqlChunkRepository,
        chunks: list[Chunk],
        collection_id: str,
    ) -> list[SummaryNode]:

        from atenex_nova.infrastructure.db.models.tables import ChunkModel, SummaryNodeModel

        summaries: list[SummaryNode] = []
        document_ids = [str(doc.id) for doc in documents]

        # 1. Load document and section level summaries in bounded SQL ``IN`` batches.
        for document_batch in self._sql_batches(document_ids):
            result = await self._session.execute(
                select(SummaryNodeModel).where(
                    SummaryNodeModel.scope_type.in_(["document", "section"]),
                    SummaryNodeModel.scope_id.in_(document_batch),
                )
            )
            summaries.extend([summary_repo._to_entity(model) for model in result.scalars().all()])

        # 2. Identify which documents need chunks loaded
        docs_with_chunks = {chunk.document_id for chunk in chunks}
        docs_needing_chunks = [doc_id for doc_id in document_ids if doc_id not in docs_with_chunks]

        loaded_chunks = list(chunks)
        for document_batch in self._sql_batches(docs_needing_chunks):
            result = await self._session.execute(
                select(ChunkModel).where(ChunkModel.document_id.in_(document_batch))
            )
            new_chunks = [chunk_repo._to_entity(m) for m in result.scalars().all()]
            loaded_chunks.extend(new_chunks)

        # 3. Load section level summaries for all chunks in bulk
        chunk_ids = [chunk.id for chunk in loaded_chunks]
        for chunk_batch in self._sql_batches(chunk_ids):
            result = await self._session.execute(
                select(SummaryNodeModel).where(
                    SummaryNodeModel.scope_type == "section",
                    SummaryNodeModel.scope_id.in_(chunk_batch),
                )
            )
            summaries.extend([summary_repo._to_entity(model) for model in result.scalars().all()])

        # 4. Load collection level summaries
        summaries.extend(await summary_repo.list_by_collection(collection_id))

        return summaries

    @staticmethod
    def _sql_batches(values: Sequence[str], batch_size: int = 500) -> list[list[str]]:
        return [
            list(values[start : start + batch_size])
            for start in range(0, len(values), batch_size)
        ]


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
        query_vector: list[float],
        chunks: list[Chunk],
        document_titles: dict[str, str],
        route_mode: str,
        *,
        query_text: str | None = None,
        allow_local_fallback: bool = True,
        dense_metrics: dict[str, object] | None = None,
    ) -> list[SearchHit]:
        retrieval_text = query_text or query.retrieval_query
        use_candidate_index = self._use_candidate_index()
        dense_hits = []
        if use_candidate_index:
            try:
                dense_started = time.perf_counter()
                candidates = await self._candidate_index.search(
                    collection_id=query.collection_id,
                    memory_layers=["chunk"],
                    query_vector=query_vector,
                    top_n=200,
                )
                if dense_metrics is not None:
                    dense_metrics["dense_latency_ms"] = round((time.perf_counter() - dense_started) * 1000, 2)
                if candidates:
                    node_ids = [c["node_id"] for c in candidates]
                    import json

                    from sqlmodel import select

                    from atenex_nova.infrastructure.db.models.tables import ChunkModel
                    stmt = select(ChunkModel).where(ChunkModel.id.in_(node_ids))
                    res = await self._session.execute(stmt)
                    chunk_models = res.scalars().all()
                    chunk_map = {m.id: m for m in chunk_models}

                    for c in candidates:
                        nid = c["node_id"]
                        if nid in chunk_map:
                            model = chunk_map[nid]
                            chunk_entity = Chunk(
                                id=model.id,
                                document_id=model.document_id,
                                text=model.text,
                                summary=model.summary,
                                token_count=model.token_count,
                                node_ids=json.loads(model.node_ids_json),
                                embedding_ref=model.embedding_ref,
                                sparse_ref=model.sparse_ref,
                                metadata=json.loads(model.metadata_json) if model.metadata_json else {},
                            )
                            hit = self._build_chunk_hit(
                                chunk=chunk_entity,
                                document_titles=document_titles,
                                score=c["score"],
                                stage="dense_turbo_ip",
                                query_text=retrieval_text,
                            )
                            dense_hits.append(hit)
                    if dense_metrics is not None:
                        dense_metrics["dense_hits"] = len(dense_hits)
            except Exception as e:
                logger.warning("Candidate index dense chunk search failed: %s", e)
                if dense_metrics is not None:
                    dense_metrics["fallback_reason"] = str(e)

        if not dense_hits and dense_goes_to_qdrant(self._settings) and self._qdrant.is_available:
            dense_started = time.perf_counter()
            try:
                dense_hits = self._convert_qdrant_hits(
                    await self._qdrant.search(f"collection_{query.collection_id}", query_vector, limit=40),
                    default_source_type="chunk",
                    document_titles=document_titles,
                    query_text=retrieval_text,
                )
            except Exception as e:
                logger.warning("Qdrant dense chunk search failed: %s", e)
                if dense_metrics is not None:
                    dense_metrics["fallback_reason"] = str(e)
            finally:
                if dense_metrics is not None:
                    dense_metrics["dense_latency_ms"] = round(
                        (time.perf_counter() - dense_started) * 1000,
                        2,
                    )
                    dense_metrics["dense_hits"] = len(dense_hits)

        sparse_hits = []
        if self._qdrant.is_available:
            try:
                sparse_encoder = self._get_sparse_encoder()
                sparse_indices, sparse_values = sparse_encoder.encode_query(retrieval_text)
                sparse_hits = self._convert_qdrant_hits(
                    await self._qdrant.search(
                        f"collection_{query.collection_id}",
                        query_vector=None,
                        limit=40,
                        query_sparse_indices=sparse_indices,
                        query_sparse_values=sparse_values,
                    ),
                    default_source_type="chunk",
                    document_titles=document_titles,
                    query_text=retrieval_text,
                )
            except Exception as e:
                logger.warning("Qdrant sparse chunk search failed: %s", e)
        if not sparse_hits and allow_local_fallback:
            if not chunks:
                repo = SqlChunkRepository(self._session)
                chunks = await repo.list_by_collection(query.collection_id)
            if chunks:
                sparse_hits = self._score_sparse_candidates(
                    query_text=retrieval_text,
                    items=chunks,
                    builder=lambda item, score: self._build_chunk_hit(
                        item,
                        document_titles,
                        score,
                        "local_sparse",
                        retrieval_text,
                    ),
                    text_getter=lambda item: item.text,
                    limit=40,
                )

        if not dense_hits and not sparse_hits:
            if not allow_local_fallback:
                return []
            logger.info("Candidate index and local search returned no hits for chunks, falling back to local BM25")
            if dense_metrics is not None and dense_metrics.get("fallback_reason") is None:
                dense_metrics["fallback_reason"] = "bm25_local_fallback"
            if not chunks:
                repo = SqlChunkRepository(self._session)
                chunks = await repo.list_by_collection(query.collection_id)
            if chunks:
                return self._score_sparse_candidates(
                    query_text=retrieval_text,
                    items=chunks,
                    builder=lambda item, score: self._build_chunk_hit(
                        item,
                        document_titles,
                        score,
                        "local_sparse",
                        retrieval_text,
                    ),
                    text_getter=lambda item: item.text,
                    limit=20,
                )
            return []

        if not dense_hits:
            return self._sort_and_limit_hits(
                query,
                sparse_hits,
                route_mode,
                limit=20,
                query_text=retrieval_text,
            )
        if not sparse_hits:
            return self._sort_and_limit_hits(
                query,
                dense_hits,
                route_mode,
                limit=20,
                query_text=retrieval_text,
            )
        return self._fuse_hits(
            query,
            dense_hits,
            sparse_hits,
            route_mode,
            limit=20,
            query_text=retrieval_text,
        )

    async def _score_propositions(
        self,
        query: Query,
        query_vector: list[float],
        propositions: list[Proposition],
        document_titles: dict[str, str],
        route_mode: str,
        *,
        query_text: str | None = None,
        allow_local_fallback: bool = True,
    ) -> list[SearchHit]:
        retrieval_text = query_text or query.retrieval_query
        use_candidate_index = self._use_candidate_index()
        dense_hits = []
        if use_candidate_index:
            try:
                candidates = await self._candidate_index.search(
                    collection_id=query.collection_id,
                    memory_layers=["proposition"],
                    query_vector=query_vector,
                    top_n=200,
                )
                if candidates:
                    node_ids = [c["node_id"] for c in candidates]
                    from sqlmodel import select

                    from atenex_nova.infrastructure.db.models.tables import PropositionModel
                    stmt = select(PropositionModel).where(PropositionModel.id.in_(node_ids))
                    res = await self._session.execute(stmt)
                    prop_models = res.scalars().all()
                    prop_map = {m.id: m for m in prop_models}

                    for c in candidates:
                        nid = c["node_id"]
                        if nid in prop_map:
                            model = prop_map[nid]
                            prop_entity = Proposition(
                                id=model.id,
                                document_id=model.document_id,
                                source_chunk_id=model.source_chunk_id,
                                text=model.text,
                                kind=model.kind,
                                embedding_ref=model.embedding_ref,
                            )
                            hit = self._build_proposition_hit(
                                proposition=prop_entity,
                                document_titles=document_titles,
                                score=c["score"],
                                stage="dense_turbo_ip",
                            )
                            dense_hits.append(hit)
            except Exception as e:
                logger.warning("Candidate index dense proposition search failed: %s", e)

        if not dense_hits and dense_goes_to_qdrant(self._settings) and self._qdrant.is_available:
            try:
                dense_hits = self._convert_qdrant_hits(
                    await self._qdrant.search(
                        f"collection_{query.collection_id}_propositions",
                        query_vector,
                        limit=40,
                    ),
                    default_source_type="proposition",
                    document_titles=document_titles,
                    query_text=retrieval_text,
                )
            except Exception as e:
                logger.warning("Qdrant dense proposition search failed: %s", e)

        sparse_hits = []
        if self._qdrant.is_available:
            try:
                sparse_encoder = self._get_sparse_encoder()
                sparse_indices, sparse_values = sparse_encoder.encode_query(retrieval_text)
                sparse_hits = self._convert_qdrant_hits(
                    await self._qdrant.search(
                        f"collection_{query.collection_id}_propositions",
                        query_vector=None,
                        limit=40,
                        query_sparse_indices=sparse_indices,
                        query_sparse_values=sparse_values,
                    ),
                    default_source_type="proposition",
                    document_titles=document_titles,
                    query_text=retrieval_text,
                )
            except Exception as e:
                logger.warning("Qdrant sparse proposition search failed: %s", e)
        elif allow_local_fallback:
            if not propositions:
                repo = SqlPropositionRepository(self._session)
                propositions = await repo.list_by_collection(query.collection_id)
            if propositions:
                sparse_hits = self._score_sparse_candidates(
                    query_text=retrieval_text,
                    items=propositions,
                    builder=lambda item, score: self._build_proposition_hit(item, document_titles, score, "local_sparse"),
                    text_getter=lambda item: item.text,
                    limit=40,
                )

        if not dense_hits and not sparse_hits:
            if not allow_local_fallback:
                return []
            logger.info("Candidate index and local search returned no hits for propositions, falling back to local BM25")
            if not propositions:
                repo = SqlPropositionRepository(self._session)
                propositions = await repo.list_by_collection(query.collection_id)
            if propositions:
                return self._score_sparse_candidates(
                    query_text=retrieval_text,
                    items=propositions,
                    builder=lambda item, score: self._build_proposition_hit(item, document_titles, score, "local_sparse"),
                    text_getter=lambda item: item.text,
                    limit=20,
                )
            return []

        if not dense_hits:
            return self._sort_and_limit_hits(
                query,
                sparse_hits,
                route_mode,
                limit=20,
                query_text=retrieval_text,
            )
        if not sparse_hits:
            return self._sort_and_limit_hits(
                query,
                dense_hits,
                route_mode,
                limit=20,
                query_text=retrieval_text,
            )
        return self._fuse_hits(
            query,
            dense_hits,
            sparse_hits,
            route_mode,
            limit=20,
            query_text=retrieval_text,
        )

    async def _score_summaries(
        self,
        query: Query,
        query_vector: list[float],
        summaries: list[SummaryNode],
        document_titles: dict[str, str],
        route_mode: str,
        *,
        query_text: str | None = None,
        allow_local_fallback: bool = True,
    ) -> list[SearchHit]:
        retrieval_text = query_text or query.retrieval_query
        use_candidate_index = self._use_candidate_index()
        dense_hits = []
        if use_candidate_index:
            try:
                candidates = await self._candidate_index.search(
                    collection_id=query.collection_id,
                    memory_layers=["summary"],
                    query_vector=query_vector,
                    top_n=200,
                )
                if candidates:
                    node_ids = [c["node_id"] for c in candidates]
                    from sqlmodel import select

                    from atenex_nova.infrastructure.db.models.tables import SummaryNodeModel
                    stmt = select(SummaryNodeModel).where(SummaryNodeModel.id.in_(node_ids))
                    res = await self._session.execute(stmt)
                    sum_models = res.scalars().all()
                    sum_map = {m.id: m for m in sum_models}

                    for c in candidates:
                        nid = c["node_id"]
                        if nid in sum_map:
                            model = sum_map[nid]
                            sum_entity = SummaryNode(
                                id=model.id,
                                scope_type=model.scope_type,
                                scope_id=model.scope_id,
                                text=model.text,
                                embedding_ref=model.embedding_ref,
                            )
                            hit = self._build_summary_hit(
                                summary=sum_entity,
                                document_titles=document_titles,
                                score=c["score"],
                                stage="dense_turbo_ip",
                            )
                            dense_hits.append(hit)
            except Exception as e:
                logger.warning("Candidate index dense summary search failed: %s", e)

        if not dense_hits and dense_goes_to_qdrant(self._settings) and self._qdrant.is_available:
            try:
                dense_hits = self._convert_qdrant_hits(
                    await self._qdrant.search(
                        f"collection_{query.collection_id}_summaries",
                        query_vector,
                        limit=30,
                    ),
                    default_source_type="summary",
                    document_titles=document_titles,
                    query_text=retrieval_text,
                )
            except Exception as e:
                logger.warning("Qdrant dense summary search failed: %s", e)

        sparse_hits = []
        if self._qdrant.is_available:
            try:
                sparse_encoder = self._get_sparse_encoder()
                sparse_indices, sparse_values = sparse_encoder.encode_query(retrieval_text)
                sparse_hits = self._convert_qdrant_hits(
                    await self._qdrant.search(
                        f"collection_{query.collection_id}_summaries",
                        query_vector=None,
                        limit=30,
                        query_sparse_indices=sparse_indices,
                        query_sparse_values=sparse_values,
                    ),
                    default_source_type="summary",
                    document_titles=document_titles,
                    query_text=retrieval_text,
                )
            except Exception as e:
                logger.warning("Qdrant sparse summary search failed: %s", e)
        elif allow_local_fallback:
            if not summaries:
                doc_repo = SqlDocumentRepository(self._session)
                documents = await self._list_all_documents(doc_repo, query.collection_id)
                chunk_repo = SqlChunkRepository(self._session)
                repo = SqlSummaryRepository(self._session)
                summaries = await self._load_summaries(repo, documents, chunk_repo, [], query.collection_id)
            if summaries:
                sparse_hits = self._score_sparse_candidates(
                    query_text=retrieval_text,
                    items=summaries,
                    builder=lambda item, score: self._build_summary_hit(item, document_titles, score, "local_sparse"),
                    text_getter=lambda item: item.text,
                    limit=40,
                )

        if not dense_hits and not sparse_hits:
            if not allow_local_fallback:
                return []
            logger.info("Candidate index and local search returned no hits for summaries, falling back to local BM25")
            if not summaries:
                doc_repo = SqlDocumentRepository(self._session)
                documents = await self._list_all_documents(doc_repo, query.collection_id)
                chunk_repo = SqlChunkRepository(self._session)
                repo = SqlSummaryRepository(self._session)
                summaries = await self._load_summaries(repo, documents, chunk_repo, [], query.collection_id)
            if summaries:
                return self._score_sparse_candidates(
                    query_text=retrieval_text,
                    items=summaries,
                    builder=lambda item, score: self._build_summary_hit(item, document_titles, score, "local_sparse"),
                    text_getter=lambda item: item.text,
                    limit=16,
                )
            return []

        if not dense_hits:
            return self._sort_and_limit_hits(
                query,
                sparse_hits,
                route_mode,
                limit=16,
                query_text=retrieval_text,
            )
        if not sparse_hits:
            return self._sort_and_limit_hits(
                query,
                dense_hits,
                route_mode,
                limit=16,
                query_text=retrieval_text,
            )
        return self._fuse_hits(
            query,
            dense_hits,
            sparse_hits,
            route_mode,
            limit=16,
            query_text=retrieval_text,
        )

    def _score_sparse_candidates(
        self,
        query_text: str,
        items: Sequence[object],
        builder: Callable[[object, float], SearchHit],
        text_getter: Callable[[object], str],
        limit: int,
    ) -> list[SearchHit]:
        texts = [text_getter(item) for item in items]
        scores = BM25SparseEncoder().score(query_text, texts) if texts else []
        ranked_indices = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
        hits: list[SearchHit] = []
        for rank, index in enumerate(ranked_indices[:limit], start=1):
            score = scores[index]
            if score <= 0:
                continue
            hit = builder(items[index], score)
            hit.rank = rank
            hits.append(hit)
        return hits

    def _new_dense_metrics(self) -> dict[str, object]:
        return {
            "dense_candidate_backend": (
                "purepy"
                if self._use_candidate_index()
                else ("qdrant" if dense_goes_to_qdrant(self._settings) else "none")
            ),
            "dense_hits": 0,
            "dense_latency_ms": 0.0,
            "fallback_reason": None,
        }

    def _get_sparse_encoder(self) -> StableSparseEncoder:
        if self._sparse_encoder is None:
            self._sparse_encoder = StableSparseEncoder()
        return self._sparse_encoder

    def _fuse_query_variant_hits(
        self,
        variant_results: list[tuple[RetrievalQueryVariant, list[SearchHit], float]],
        *,
        limit: int,
    ) -> list[SearchHit]:
        if not variant_results:
            return []
        if len(variant_results) == 1:
            variant, hits, latency_ms = variant_results[0]
            for hit in hits:
                metadata = dict(hit.metadata or {})
                metadata["retrieval_query_expanded"] = False
                metadata["retrieval_query_variant_indices"] = [variant.index]
                metadata["retrieval_query_variants"] = [variant.audit_dict()]
                metadata["retrieval_query_variant_latency_ms"] = latency_ms
                hit.metadata = metadata
            return hits[:limit]

        fused: dict[str, SearchHit] = {}
        variants_by_hit: dict[str, list[dict[str, object]]] = {}
        contributions_by_hit: dict[str, list[dict[str, object]]] = {}
        for variant, hits, latency_ms in variant_results:
            for rank, hit in enumerate(hits, start=1):
                key = self._hit_key(hit)
                existing = fused.get(key)
                if existing is None:
                    existing = SearchHit(
                        id=hit.id,
                        source_type=hit.source_type,
                        source_id=hit.source_id,
                        document_id=hit.document_id,
                        title=hit.title,
                        snippet=hit.snippet,
                        score=0.0,
                        rank=0,
                        page_number=hit.page_number,
                        metadata=dict(hit.metadata or {}),
                    )
                    fused[key] = existing
                else:
                    existing.metadata = self._merge_hit_metadata(
                        existing.metadata,
                        hit.metadata,
                    )
                existing.score += self._rrf_score(rank, weight=1.0)
                variants_by_hit.setdefault(key, []).append(variant.audit_dict())
                contributions_by_hit.setdefault(key, []).append(
                    {
                        "variant_index": variant.index,
                        "rank": rank,
                        "source_score": round(hit.score, 6),
                        "latency_ms": latency_ms,
                    }
                )

        for key, hit in fused.items():
            metadata = dict(hit.metadata or {})
            variant_payloads = variants_by_hit[key]
            metadata["retrieval_query_expanded"] = True
            metadata["retrieval_query_variant_indices"] = [
                int(payload["index"]) for payload in variant_payloads
            ]
            metadata["retrieval_query_variants"] = variant_payloads
            metadata["retrieval_query_rrf_score"] = round(hit.score, 8)
            metadata["retrieval_query_contributions"] = contributions_by_hit[key]
            hit.metadata = metadata

        ranked = sorted(fused.values(), key=lambda item: item.score, reverse=True)
        for rank, hit in enumerate(ranked[:limit], start=1):
            hit.rank = rank
        return ranked[:limit]

    def _fuse_hits(
        self,
        query: Query,
        dense_hits: list[SearchHit],
        sparse_hits: list[SearchHit],
        route_mode: str,
        limit: int,
        *,
        query_text: str | None = None,
    ) -> list[SearchHit]:
        retrieval_text = query_text or query.retrieval_query
        fused: dict[str, SearchHit] = {}
        dense_ranks = {self._hit_key(hit): rank for rank, hit in enumerate(dense_hits, start=1)}
        sparse_ranks = {self._hit_key(hit): rank for rank, hit in enumerate(sparse_hits, start=1)}

        for hit in [*dense_hits, *sparse_hits]:
            key = self._hit_key(hit)
            existing = fused.get(key)
            if existing is None:
                fused[key] = SearchHit(
                    id=hit.id,
                    source_type=hit.source_type,
                    source_id=hit.source_id,
                    document_id=hit.document_id,
                    title=hit.title,
                    snippet=hit.snippet,
                    score=0.0,
                    rank=0,
                    page_number=hit.page_number,
                    metadata=dict(hit.metadata or {}),
                )
                existing = fused[key]
            existing.score += self._rrf_score(dense_ranks.get(key), weight=0.65)
            existing.score += self._rrf_score(sparse_ranks.get(key), weight=0.35)
            lexical = self._lexical_overlap(retrieval_text, f"{hit.title} {hit.snippet}")
            existing.score += lexical * 0.25
            if hit.metadata:
                existing.metadata = self._merge_hit_metadata(existing.metadata, hit.metadata)

        return self._sort_and_limit_hits(
            query,
            list(fused.values()),
            route_mode,
            limit=limit,
            query_text=retrieval_text,
        )

    @staticmethod
    def _merge_hit_metadata(
        existing: dict[str, object] | None,
        incoming: dict[str, object] | None,
    ) -> dict[str, object]:
        existing_metadata = dict(existing or {})
        incoming_metadata = dict(incoming or {})
        merged_metadata = {**existing_metadata, **incoming_metadata}
        stages: list[str] = []
        for metadata in (existing_metadata, incoming_metadata):
            raw_stages = metadata.get("retrieval_stages")
            if isinstance(raw_stages, list):
                stages.extend(stage for stage in raw_stages if isinstance(stage, str))
            stage = metadata.get("retrieval_stage")
            if isinstance(stage, str):
                stages.append(stage)
        distinct_stages = list(dict.fromkeys(stages))
        if distinct_stages:
            merged_metadata["retrieval_stage"] = distinct_stages[0]
            merged_metadata["retrieval_stages"] = distinct_stages
        return merged_metadata

    def _sort_and_limit_hits(
        self,
        query: Query,
        hits: list[SearchHit],
        route_mode: str,
        limit: int,
        *,
        query_text: str | None = None,
    ) -> list[SearchHit]:
        """Score hits with heuristics only; neural rerank runs once in ``_rank_hits``."""
        self._apply_heuristic_scores(
            query,
            hits,
            route_mode,
            query_text=query_text,
        )
        ranked = sorted(hits, key=lambda item: item.score, reverse=True)
        for index, hit in enumerate(ranked[:limit], start=1):
            hit.rank = index
        return ranked[:limit]

    def _apply_heuristic_scores(
        self,
        query: Query,
        hits: list[SearchHit],
        route_mode: str,
        neural_scores: list[float] | None = None,
        *,
        query_text: str | None = None,
    ) -> None:
        retrieval_text = query_text or query.retrieval_query
        for index, hit in enumerate(hits):
            overlap = self._lexical_overlap(retrieval_text, f"{hit.title} {hit.snippet}")
            phrase_bonus = 0.15 if route_mode == "exact" and query_has_phrase(hit.snippet, hit.title) else 0.0
            contradiction_bonus = (
                0.12 if route_mode == "argumentative" and self._contains_contradiction(hit.snippet) else 0.0
            )
            metadata_bonus = 0.08 if (hit.metadata or {}).get("heading_path") else 0.0

            if neural_scores:
                base_score = neural_scores[index]
                hit.score = base_score + (hit.score * 0.1) + (overlap * 0.2) + phrase_bonus + contradiction_bonus + metadata_bonus
            else:
                hit.score += overlap * 0.35 + phrase_bonus + contradiction_bonus + metadata_bonus

            hit.score *= self._route_source_weight(route_mode, hit.source_type)

    def _rerank_hits(
        self,
        query: Query,
        hits: list[SearchHit],
        route_mode: str,
        limit: int,
    ) -> list[SearchHit]:
        query_text = query.retrieval_query

        neural_scores: list[float] = []
        if self._settings.reranker_enabled or self._settings.reranker_required:
            pairs = [(query_text, f"{hit.title} {hit.snippet}") for hit in hits]
            neural_scores = self._reranker.predict(pairs)

        self._apply_heuristic_scores(query, hits, route_mode, neural_scores=neural_scores or None)

        ranked = sorted(hits, key=lambda item: item.score, reverse=True)
        for index, hit in enumerate(ranked[:limit], start=1):
            hit.rank = index
        return ranked[:limit]

    def _rank_hits(self, query: Query, hits: list[SearchHit], route_mode: str, limit: int) -> list[SearchHit]:
        substantive_hits = [
            hit
            for hit in hits
            if not (
                hit.source_type == "chunk"
                and bool((hit.metadata or {}).get("metadata_only"))
            )
        ]
        return self._rerank_hits(query, substantive_hits or hits, route_mode, limit=limit)

    async def _score_visual_pages(
        self,
        collection_id: str,
        query: Query,
        document_titles: dict[str, str],
    ) -> list[SearchHit]:
        pages = await self._visual.search(
            collection_id,
            query.retrieval_query,
            limit=8,
            session=self._session,
        )
        hits: list[SearchHit] = []
        for page in pages:
            metadata = page.get("metadata") or {}
            snippet = str(page.get("text") or page.get("snippet") or "")[:280]
            hits.append(
                SearchHit(
                    id=str(page.get("id")),
                    source_type="visual_page",
                    source_id=str(page.get("id")),
                    document_id=str(page.get("document_id") or "") or None,
                    title=str(page.get("title") or document_titles.get(str(page.get("document_id") or ""), "Visual page")),
                    snippet=snippet,
                    score=float(page.get("score", 0.0))
                    + self._lexical_overlap(query.retrieval_query, snippet),
                    rank=0,
                    page_number=self._to_int(page.get("page_number")),
                    metadata=metadata if isinstance(metadata, dict) else None,
                )
            )
        return self._sort_and_limit_hits(query, hits, "visual", limit=8)

    def _convert_qdrant_hits(
        self,
        qdrant_hits: list[dict[str, object]],
        default_source_type: str,
        document_titles: dict[str, str],
        query_text: str,
    ) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for index, hit in enumerate(qdrant_hits, start=1):
            payload_obj = hit.get("payload")
            payload = payload_obj if isinstance(payload_obj, dict) else {}
            source_id = str(
                payload.get("chunk_id")
                or payload.get("proposition_id")
                or payload.get("summary_id")
                or hit.get("id")
            )
            document_id_value = payload.get("document_id")
            document_id = str(document_id_value) if document_id_value else None
            title = str(payload.get("title") or document_titles.get(document_id or "", "Collection summary"))
            snippet = str(payload.get("summary") or payload.get("text") or "")[:320]
            page_number = self._extract_page_number(payload)
            metadata = {
                key: value
                for key, value in payload.items()
                if key not in {"text", "summary", "title"}
            }
            metadata["source_text"] = str(payload.get("text") or payload.get("summary") or snippet)
            metadata["retrieval_stage"] = "dense_qdrant"
            dense_score = float(hit.get("score") or 0.0)
            lexical_bonus = self._lexical_overlap(
                query_text,
                " ".join(
                    str(part)
                    for part in (
                        title,
                        snippet,
                        payload.get("sparse_ref"),
                    )
                    if part
                ),
            )
            hits.append(
                SearchHit(
                    id=str(hit.get("id") or source_id),
                    source_type=str(payload.get("source_type") or default_source_type),
                    source_id=source_id,
                    document_id=document_id,
                    title=title,
                    snippet=snippet,
                    score=dense_score + (lexical_bonus * 0.2),
                    rank=index,
                    page_number=page_number,
                    metadata=metadata,
                )
            )
        return hits

    def _build_chunk_hit(
        self,
        chunk: Chunk,
        document_titles: dict[str, str],
        score: float,
        stage: str,
        query_text: str = "",
    ) -> SearchHit:
        metadata = dict(chunk.metadata)
        metadata["source_text"] = chunk.text
        metadata["retrieval_stage"] = stage
        content = self._clean_chunk_content(chunk.text)
        metadata["metadata_only"] = not bool(content)
        page_numbers = metadata.get("page_numbers")
        page_number = None
        if isinstance(page_numbers, list) and page_numbers:
            first_page = page_numbers[0]
            if isinstance(first_page, int):
                page_number = first_page
        return SearchHit(
            id=chunk.id,
            source_type="chunk",
            source_id=chunk.id,
            document_id=chunk.document_id,
            title=document_titles.get(chunk.document_id, ""),
            snippet=(
                self._best_chunk_excerpt(content, query_text)
                if content
                else (chunk.summary or chunk.text[:280])
            ),
            score=score,
            rank=0,
            page_number=page_number,
            metadata=metadata,
        )

    @staticmethod
    def _clean_chunk_content(text: str) -> str:
        """Remove source-envelope fields while preserving the original Spanish content."""
        metadata_prefixes = (
            "title:",
            "video id:",
            "video url:",
            "channel:",
            "subtitle language:",
            "subtitle source:",
            "generated at:",
            "kind:",
            "language:",
        )
        content_lines = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line == "-----" or line.lower().startswith(metadata_prefixes):
                continue
            content_lines.append(line)
        return " ".join(content_lines)

    @staticmethod
    def _best_chunk_excerpt(content: str, query_text: str, max_chars: int = 520) -> str:
        """Select a query-centered excerpt from long transcript chunks."""
        if len(content) <= max_chars:
            return content
        query_terms = list(dict.fromkeys(tokenize(query_text)))
        if not query_terms:
            return content[:max_chars].rsplit(" ", 1)[0]

        lowered = content.lower()
        candidate_positions = [
            match.start()
            for term in query_terms
            for match in re.finditer(rf"(?<!\w){re.escape(term)}(?!\w)", lowered)
        ]
        if not candidate_positions:
            return content[:max_chars].rsplit(" ", 1)[0]

        best_start = 0
        best_score = -1
        for position in candidate_positions:
            start = max(0, position - (max_chars // 3))
            window = lowered[start : start + max_chars]
            unique_hits = sum(1 for term in query_terms if term in window)
            total_hits = sum(window.count(term) for term in query_terms)
            score = (unique_hits * 100) + total_hits
            if score > best_score:
                best_start = start
                best_score = score

        excerpt = content[best_start : best_start + max_chars]
        if best_start > 0 and " " in excerpt:
            excerpt = excerpt.split(" ", 1)[1]
        if best_start + max_chars < len(content) and " " in excerpt:
            excerpt = excerpt.rsplit(" ", 1)[0]
        return excerpt.strip()

    def _build_proposition_hit(
        self,
        proposition: Proposition,
        document_titles: dict[str, str],
        score: float,
        stage: str,
    ) -> SearchHit:
        return SearchHit(
            id=proposition.id,
            source_type="proposition",
            source_id=proposition.id,
            document_id=proposition.document_id,
            title=document_titles.get(proposition.document_id, ""),
            snippet=proposition.text,
            score=score,
            rank=0,
            metadata={
                "source_chunk_id": proposition.source_chunk_id,
                "kind": proposition.kind,
                "source_text": proposition.text,
                "retrieval_stage": stage,
            },
        )

    def _build_summary_hit(
        self,
        summary: SummaryNode,
        document_titles: dict[str, str],
        score: float,
        stage: str,
    ) -> SearchHit:
        document_id = summary.scope_id if summary.scope_type == "document" else None
        return SearchHit(
            id=summary.id,
            source_type="summary",
            source_id=summary.id,
            document_id=document_id,
            title=document_titles.get(summary.scope_id, "Collection summary"),
            snippet=summary.text,
            score=score,
            rank=0,
            metadata={
                "scope_type": summary.scope_type,
                "scope_id": summary.scope_id,
                "source_text": summary.text,
                "retrieval_stage": stage,
            },
        )

    def _route_source_weight(self, route_mode: str, source_type: str) -> float:
        boosts = {
            "exact": {"chunk": 1.15, "proposition": 1.05, "summary": 0.85},
            "factual_local": {"chunk": 1.12, "proposition": 1.08, "summary": 0.9},
            "multi_hop": {"chunk": 1.1, "proposition": 1.1, "summary": 0.9, "graph_edge": 0.8},
            "global": {"chunk": 0.88, "proposition": 1.0, "summary": 1.25},
            "argumentative": {"chunk": 1.0, "proposition": 1.22, "summary": 0.95, "graph_edge": 1.08},
            "visual": {"chunk": 1.0, "proposition": 0.92, "summary": 1.05, "visual_page": 1.3},
        }
        return boosts.get(route_mode, {}).get(source_type, 1.0)

    @staticmethod
    def _hit_key(hit: SearchHit) -> str:
        return f"{hit.source_type}:{hit.source_id}"

    @staticmethod
    def _rrf_score(rank: int | None, weight: float) -> float:
        if rank is None:
            return 0.0
        return weight / (60.0 + rank)

    @staticmethod
    def _extract_page_number(payload: dict[str, object]) -> int | None:
        page_numbers = payload.get("page_numbers")
        if isinstance(page_numbers, list) and page_numbers:
            return RetrievalOrchestrator._to_int(page_numbers[0])
        return RetrievalOrchestrator._to_int(payload.get("page_number"))

    @staticmethod
    def _to_int(value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _lexical_overlap(query_text: str, text: str) -> float:
        query_terms = set(tokenize(query_text))
        if not query_terms:
            return 0.0
        text_terms = set(tokenize(text))
        if not text_terms:
            return 0.0
        return len(query_terms.intersection(text_terms)) / max(len(query_terms), 1)

    @staticmethod
    def _contains_contradiction(text: str) -> bool:
        lower = text.lower()
        return any(marker in lower for marker in ("however", "but", "sin embargo", "no obstante", "contradict"))

    @staticmethod
    def _result_limit(route_mode: str) -> int:
        return {
            "exact": 8,
            "factual_local": 10,
            "multi_hop": 20,
            "global": 8,
            "argumentative": 12,
            "visual": 8,
        }.get(route_mode, 10)

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        if not left or not right:
            return 0.0
        limit = min(len(left), len(right))
        numerator = sum(left[index] * right[index] for index in range(limit))
        left_norm = sum(value * value for value in left[:limit]) ** 0.5
        right_norm = sum(value * value for value in right[:limit]) ** 0.5
        if not left_norm or not right_norm:
            return 0.0
        return float(numerator / (left_norm * right_norm))


def query_has_phrase(snippet: str, title: str) -> bool:
    lower = f"{snippet} {title}".lower()
    return any(marker in lower for marker in ("exact", "uuid", "codigo", "definition", "defines"))

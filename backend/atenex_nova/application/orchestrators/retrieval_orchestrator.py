"""Retrieval orchestration for hybrid, route-aware search."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlparse

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
from atenex_nova.infrastructure.embeddings.bm25_encoder import (
    BM25SparseEncoder,
    StableSparseEncoder,
    tokenize,
)
from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter
from atenex_nova.infrastructure.visual.colpali_adapter import ColPaliAdapter
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import StrictModeViolationError
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
        visual_adapter: ColPaliAdapter | None = None,
        audit: PipelineAuditService | None = None,
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
        route_reason = self._router.explain_route(features, route_mode_name)
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
        logger.info(
            f"Search started: '{query_text}' | Collection: {collection_id} | Mode: {mode} "
            f"-> Routed Mode: {route_mode_name} | Intent: {intent.value} | Language: {features.language}"
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
            },
        ) as audit:
            documents = await doc_repo.list_by_collection(collection_id)
            document_titles = {document.id: document.title for document in documents}
            if not self._qdrant.is_available:
                chunks = await chunk_repo.list_by_collection(collection_id)
                propositions = await proposition_repo.list_by_collection(collection_id)
                summaries = await self._load_summaries(summary_repo, documents, chunk_repo, chunks, collection_id)
            else:
                chunks = []
                propositions = []
                summaries = []
            query_vector = (await self._embedder.embed([query.normalized_text or query.text]))[0]

            hits: list[SearchHit] = []

            async with self._audit.step(
                run_id=query.id,
                entity_type="query",
                entity_id=query.id,
                pipeline="retrieval",
                stage="score_chunks",
                context={"documents": len(documents), "chunks": len(chunks)},
            ) as step:
                chunk_hits = await self._score_chunks(query, query_vector, chunks, document_titles, route_mode_name)
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
                proposition_hits = await self._score_propositions(
                    query,
                    query_vector,
                    propositions,
                    document_titles,
                    route_mode_name,
                )
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
                summary_hits = await self._score_summaries(
                    query,
                    query_vector,
                    summaries,
                    document_titles,
                    route_mode_name,
                )
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

            ranked_hits = self._rank_hits(query, hits, route_mode_name, limit=self._result_limit(route_mode_name))
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
        return SearchResult(query=query, hits=ranked_hits, evidence_pack=evidence_pack, route_reason=route_reason)

    async def _load_summaries(
        self,
        summary_repo: SqlSummaryRepository,
        documents: list[object],
        chunk_repo: SqlChunkRepository,
        chunks: list[Chunk],
        collection_id: str,
    ) -> list[SummaryNode]:
        from sqlmodel import select

        from atenex_nova.infrastructure.db.models.tables import ChunkModel, SummaryNodeModel

        summaries: list[SummaryNode] = []
        document_ids = [str(doc.id) for doc in documents]

        # 1. Load document and section level summaries for these documents in bulk
        if document_ids:
            result = await self._session.execute(
                select(SummaryNodeModel).where(
                    SummaryNodeModel.scope_type.in_(["document", "section"]),
                    SummaryNodeModel.scope_id.in_(document_ids),
                )
            )
            summaries.extend([summary_repo._to_entity(model) for model in result.scalars().all()])

        # 2. Identify which documents need chunks loaded
        docs_with_chunks = {chunk.document_id for chunk in chunks}
        docs_needing_chunks = [doc_id for doc_id in document_ids if doc_id not in docs_with_chunks]

        loaded_chunks = list(chunks)
        if docs_needing_chunks:
            result = await self._session.execute(
                select(ChunkModel).where(ChunkModel.document_id.in_(docs_needing_chunks))
            )
            new_chunks = [chunk_repo._to_entity(m) for m in result.scalars().all()]
            loaded_chunks.extend(new_chunks)

        # 3. Load section level summaries for all chunks in bulk
        chunk_ids = [chunk.id for chunk in loaded_chunks]
        if chunk_ids:
            result = await self._session.execute(
                select(SummaryNodeModel).where(
                    SummaryNodeModel.scope_type == "section",
                    SummaryNodeModel.scope_id.in_(chunk_ids),
                )
            )
            summaries.extend([summary_repo._to_entity(model) for model in result.scalars().all()])

        # 4. Load collection level summaries
        summaries.extend(await summary_repo.list_by_collection(collection_id))

        return summaries


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
    ) -> list[SearchHit]:
        if not self._qdrant.is_available:
            if not chunks:
                repo = SqlChunkRepository(self._session)
                chunks = await repo.list_by_collection(query.collection_id)
            if not chunks:
                return []
            logger.info("Qdrant unavailable, falling back to local BM25 search for chunks")
            return self._score_sparse_candidates(
                query_text=query.normalized_text or query.text,
                items=chunks,
                builder=lambda item, score: self._build_chunk_hit(item, document_titles, score, "local_sparse"),
                text_getter=lambda item: item.text,
                limit=20,
            )

        dense_hits = []
        try:
            dense_hits = self._convert_qdrant_hits(
                await self._qdrant.search(f"collection_{query.collection_id}", query_vector, limit=40),
                default_source_type="chunk",
                document_titles=document_titles,
                query_text=query.normalized_text or query.text,
            )
        except Exception as e:
            logger.warning("Qdrant dense chunk search failed: %s", e)

        sparse_hits = []
        try:
            sparse_encoder = StableSparseEncoder()
            sparse_indices, sparse_values = sparse_encoder.encode_query(query.normalized_text or query.text)
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
                query_text=query.normalized_text or query.text,
            )
        except Exception as e:
            logger.warning("Qdrant sparse chunk search failed: %s", e)

        if not dense_hits and not sparse_hits:
            logger.info("Qdrant search returned no hits for chunks, falling back to local BM25")
            if not chunks:
                repo = SqlChunkRepository(self._session)
                chunks = await repo.list_by_collection(query.collection_id)
            if chunks:
                return self._score_sparse_candidates(
                    query_text=query.normalized_text or query.text,
                    items=chunks,
                    builder=lambda item, score: self._build_chunk_hit(item, document_titles, score, "local_sparse"),
                    text_getter=lambda item: item.text,
                    limit=20,
                )
            return []

        if not dense_hits:
            return self._rerank_hits(query, sparse_hits, route_mode, limit=20)
        if not sparse_hits:
            return self._rerank_hits(query, dense_hits, route_mode, limit=20)
        return self._fuse_hits(query, dense_hits, sparse_hits, route_mode, limit=20)

    async def _score_propositions(
        self,
        query: Query,
        query_vector: list[float],
        propositions: list[Proposition],
        document_titles: dict[str, str],
        route_mode: str,
    ) -> list[SearchHit]:
        if not self._qdrant.is_available:
            if not propositions:
                repo = SqlPropositionRepository(self._session)
                propositions = await repo.list_by_collection(query.collection_id)
            if not propositions:
                return []
            logger.info("Qdrant unavailable, falling back to local BM25 search for propositions")
            return self._score_sparse_candidates(
                query_text=query.normalized_text or query.text,
                items=propositions,
                builder=lambda item, score: self._build_proposition_hit(item, document_titles, score, "local_sparse"),
                text_getter=lambda item: item.text,
                limit=20,
            )

        dense_hits = []
        try:
            dense_hits = self._convert_qdrant_hits(
                await self._qdrant.search(
                    f"collection_{query.collection_id}_propositions",
                    query_vector,
                    limit=40,
                ),
                default_source_type="proposition",
                document_titles=document_titles,
                query_text=query.normalized_text or query.text,
            )
        except Exception as e:
            logger.warning("Qdrant dense proposition search failed: %s", e)

        sparse_hits = []
        try:
            sparse_encoder = StableSparseEncoder()
            sparse_indices, sparse_values = sparse_encoder.encode_query(query.normalized_text or query.text)
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
                query_text=query.normalized_text or query.text,
            )
        except Exception as e:
            logger.warning("Qdrant sparse proposition search failed: %s", e)

        if not dense_hits and not sparse_hits:
            logger.info("Qdrant search returned no hits for propositions, falling back to local BM25")
            if not propositions:
                repo = SqlPropositionRepository(self._session)
                propositions = await repo.list_by_collection(query.collection_id)
            if propositions:
                return self._score_sparse_candidates(
                    query_text=query.normalized_text or query.text,
                    items=propositions,
                    builder=lambda item, score: self._build_proposition_hit(item, document_titles, score, "local_sparse"),
                    text_getter=lambda item: item.text,
                    limit=20,
                )
            return []

        if not dense_hits:
            return self._rerank_hits(query, sparse_hits, route_mode, limit=20)
        if not sparse_hits:
            return self._rerank_hits(query, dense_hits, route_mode, limit=20)
        return self._fuse_hits(query, dense_hits, sparse_hits, route_mode, limit=20)

    async def _score_summaries(
        self,
        query: Query,
        query_vector: list[float],
        summaries: list[SummaryNode],
        document_titles: dict[str, str],
        route_mode: str,
    ) -> list[SearchHit]:
        if not self._qdrant.is_available:
            if not summaries:
                doc_repo = SqlDocumentRepository(self._session)
                documents = await doc_repo.list_by_collection(query.collection_id)
                chunk_repo = SqlChunkRepository(self._session)
                repo = SqlSummaryRepository(self._session)
                summaries = await self._load_summaries(repo, documents, chunk_repo, [], query.collection_id)
            if not summaries:
                return []
            logger.info("Qdrant unavailable, falling back to local BM25 search for summaries")
            return self._score_sparse_candidates(
                query_text=query.normalized_text or query.text,
                items=summaries,
                builder=lambda item, score: self._build_summary_hit(item, document_titles, score, "local_sparse"),
                text_getter=lambda item: item.text,
                limit=16,
            )

        dense_hits = []
        try:
            dense_hits = self._convert_qdrant_hits(
                await self._qdrant.search(
                    f"collection_{query.collection_id}_summaries",
                    query_vector,
                    limit=30,
                ),
                default_source_type="summary",
                document_titles=document_titles,
                query_text=query.normalized_text or query.text,
            )
        except Exception as e:
            logger.warning("Qdrant dense summary search failed: %s", e)

        sparse_hits = []
        try:
            sparse_encoder = StableSparseEncoder()
            sparse_indices, sparse_values = sparse_encoder.encode_query(query.normalized_text or query.text)
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
                query_text=query.normalized_text or query.text,
            )
        except Exception as e:
            logger.warning("Qdrant sparse summary search failed: %s", e)

        if not dense_hits and not sparse_hits:
            logger.info("Qdrant search returned no hits for summaries, falling back to local BM25")
            if not summaries:
                doc_repo = SqlDocumentRepository(self._session)
                documents = await doc_repo.list_by_collection(query.collection_id)
                chunk_repo = SqlChunkRepository(self._session)
                repo = SqlSummaryRepository(self._session)
                summaries = await self._load_summaries(repo, documents, chunk_repo, [], query.collection_id)
            if summaries:
                return self._score_sparse_candidates(
                    query_text=query.normalized_text or query.text,
                    items=summaries,
                    builder=lambda item, score: self._build_summary_hit(item, document_titles, score, "local_sparse"),
                    text_getter=lambda item: item.text,
                    limit=16,
                )
            return []

        if not dense_hits:
            return self._rerank_hits(query, sparse_hits, route_mode, limit=16)
        if not sparse_hits:
            return self._rerank_hits(query, dense_hits, route_mode, limit=16)
        return self._fuse_hits(query, dense_hits, sparse_hits, route_mode, limit=16)

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

    def _fuse_hits(
        self,
        query: Query,
        dense_hits: list[SearchHit],
        sparse_hits: list[SearchHit],
        route_mode: str,
        limit: int,
    ) -> list[SearchHit]:
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
            lexical = self._lexical_overlap(query.normalized_text or query.text, f"{hit.title} {hit.snippet}")
            existing.score += lexical * 0.25
            if hit.metadata:
                existing.metadata = {**(existing.metadata or {}), **hit.metadata}

        return self._rerank_hits(query, list(fused.values()), route_mode, limit=limit)

    def _rerank_hits(
        self,
        query: Query,
        hits: list[SearchHit],
        route_mode: str,
        limit: int,
    ) -> list[SearchHit]:
        query_text = query.normalized_text or query.text

        from atenex_nova.infrastructure.embeddings.reranker_adapter import RerankerAdapter
        reranker = RerankerAdapter()
        pairs = [(query_text, f"{hit.title} {hit.snippet}") for hit in hits]
        neural_scores = reranker.predict(pairs)

        for i, hit in enumerate(hits):
            overlap = self._lexical_overlap(query_text, f"{hit.title} {hit.snippet}")
            phrase_bonus = 0.15 if route_mode == "exact" and query_has_phrase(hit.snippet, hit.title) else 0.0
            contradiction_bonus = 0.12 if route_mode == "argumentative" and self._contains_contradiction(hit.snippet) else 0.0
            metadata_bonus = 0.08 if (hit.metadata or {}).get("heading_path") else 0.0

            if neural_scores:
                base_score = neural_scores[i]
                hit.score = base_score + (hit.score * 0.1) + (overlap * 0.2) + phrase_bonus + contradiction_bonus + metadata_bonus
            else:
                hit.score += overlap * 0.35 + phrase_bonus + contradiction_bonus + metadata_bonus

            hit.score *= self._route_source_weight(route_mode, hit.source_type)

        ranked = sorted(hits, key=lambda item: item.score, reverse=True)
        for index, hit in enumerate(ranked[:limit], start=1):
            hit.rank = index
        return ranked[:limit]

    def _rank_hits(self, query: Query, hits: list[SearchHit], route_mode: str, limit: int) -> list[SearchHit]:
        return self._rerank_hits(query, hits, route_mode, limit=limit)

    async def _score_visual_pages(
        self,
        collection_id: str,
        query: Query,
        document_titles: dict[str, str],
    ) -> list[SearchHit]:
        pages = await self._visual.search(collection_id, query.normalized_text or query.text, limit=8)
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
                    score=float(page.get("score", 0.0)) + self._lexical_overlap(query.normalized_text or query.text, snippet),
                    rank=0,
                    page_number=self._to_int(page.get("page_number")),
                    metadata=metadata if isinstance(metadata, dict) else None,
                )
            )
        return self._rerank_hits(query, hits, "visual", limit=8)

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
    ) -> SearchHit:
        metadata = dict(chunk.metadata)
        metadata["source_text"] = chunk.text
        metadata["retrieval_stage"] = stage
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
            snippet=chunk.summary or chunk.text[:280],
            score=score,
            rank=0,
            page_number=page_number,
            metadata=metadata,
        )

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
            "multi_hop": {"chunk": 0.95, "proposition": 1.2, "summary": 1.0, "graph_edge": 1.15},
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
            "multi_hop": 12,
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

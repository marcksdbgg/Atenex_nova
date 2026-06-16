"""Job handlers for phase 4 memory enrichment."""

from __future__ import annotations

import itertools
import re
from collections import Counter
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.entities.proposition import Proposition
from atenex_nova.domain.entities.relation_edge import RelationEdge
from atenex_nova.domain.entities.summary_node import SummaryNode
from atenex_nova.domain.value_objects.identifiers import JobType, RelationType, new_id
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import SqlPropositionRepository
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository
from atenex_nova.infrastructure.embeddings.bm25_encoder import StableSparseEncoder
from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.infrastructure.graph.graph_store import GraphStore
from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter, QdrantDocument
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService
from atenex_nova.workers.runner import BaseJobHandler

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def split_sentences(text: str) -> list[str]:
    sentences = [segment.strip() for segment in SENTENCE_RE.split(text) if segment.strip()]
    return [sentence for sentence in sentences if len(sentence) > 20]


def classify_proposition(text: str) -> str:
    lower = text.lower()
    if any(marker in lower for marker in ("is defined as", "means", "se define", "defined as")):
        return "definition"
    if any(marker in lower for marker in ("must", "should", "debe", "shall", "required")):
        return "rule"
    if any(marker in lower for marker in ("because", "causes", "leads to", "provoca", "por eso")):
        return "causal"
    if any(marker in lower for marker in ("step", "first", "second", "procedure", "proceso", "instrucción")):
        return "procedure"
    if any(marker in lower for marker in ("vs", "versus", "compare", "diferencia", "better", "mejor")):
        return "comparison"
    return "fact"


def summarize_texts(texts: list[str], max_sentences: int = 3) -> str:
    words: Counter[str] = Counter()
    for text in texts:
        for token in re.findall(r"[\w\-]+", text.lower()):
            if len(token) > 3:
                words[token] += 1
    scored: list[tuple[float, str]] = []
    for text in texts:
        tokens = [token.lower() for token in re.findall(r"[\w\-]+", text)]
        score = sum(words[token] for token in tokens)
        scored.append((score, text.strip()))
    selected = [text for _, text in sorted(scored, reverse=True)[:max_sentences]]
    return " ".join(selected)


class ExtractPropositionsJobHandler(BaseJobHandler):
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        document_id = job.target_id
        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            chunk_repo = SqlChunkRepository(session)
            proposition_repo = SqlPropositionRepository(session)
            job_repo = SqlJobRepository(session)
            audit = PipelineAuditService(session=session)

            document = await doc_repo.get_by_id(document_id)
            if document is None:
                raise ValueError(f"Document {document_id} not found")

            chunks = await chunk_repo.get_by_document(document_id)
            async with audit.step(
                run_id=job.id,
                entity_type="document",
                entity_id=document_id,
                pipeline="memory_enrichment",
                stage="extract_propositions",
                context={"chunk_count": len(chunks)},
            ) as step:
                propositions: list[Proposition] = []
                for chunk in chunks:
                    for sentence in split_sentences(chunk.text or chunk.summary):
                        propositions.append(
                            Proposition(
                                id=new_id(),
                                document_id=document_id,
                                source_chunk_id=chunk.id,
                                text=sentence,
                                kind=classify_proposition(sentence),
                            )
                        )

                if not propositions:
                    propositions = [
                        Proposition(
                            id=new_id(),
                            document_id=document_id,
                            source_chunk_id=chunks[0].id if chunks else document_id,
                            text=document.title,
                            kind="fact",
                        )
                    ]

                await proposition_repo.create_many(propositions)
                step.metrics(propositions_created=len(propositions), proposition_types=sorted({prop.kind for prop in propositions}))

            for job_type in (
                JobType.EMBED_PROPOSITIONS,
                JobType.GENERATE_SUMMARIES,
                JobType.BUILD_GRAPH,
            ):
                await job_repo.create(Job(id=new_id(), job_type=job_type, target_id=document_id))

            await session.commit()
            return {"propositions_created": len(propositions)}


class EmbedPropositionsJobHandler(BaseJobHandler):
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        document_id = job.target_id
        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            proposition_repo = SqlPropositionRepository(session)
            audit = PipelineAuditService(session=session)

            document = await doc_repo.get_by_id(document_id)
            if document is None:
                raise ValueError(f"Document {document_id} not found")

            propositions = await proposition_repo.list_by_document(document_id)
            if not propositions:
                return {"embedded_propositions": 0}

            async with audit.step(
                run_id=job.id,
                entity_type="document",
                entity_id=document_id,
                pipeline="memory_enrichment",
                stage="embed_propositions",
                context={"proposition_count": len(propositions)},
            ) as step:
                settings = get_settings()
                qdrant_endpoint = urlparse(settings.qdrant_url)
                qdrant_host = qdrant_endpoint.hostname or "localhost"
                qdrant_port = qdrant_endpoint.port or 6333

                embedder = EmbeddingGemmaAdapter(
                    dim=settings.embedding_dimensions,
                    required=settings.embeddings_required,
                )
                vectors = await embedder.embed([prop.text for prop in propositions])

                # Quantize and index candidates using IngestionOrchestrator
                from atenex_nova.application.orchestrators.ingestion_orchestrator import (
                    IngestionOrchestrator,
                )
                ingestion_orch = IngestionOrchestrator(session)
                await ingestion_orch.index_nodes(
                    collection_id=str(document.collection_id),
                    memory_layer="proposition",
                    node_ids=[prop.id for prop in propositions],
                    vectors=vectors,
                    embedding_model=settings.embedding_model,
                    dimension=settings.embedding_dimensions,
                )

                sparse_encoder = StableSparseEncoder()
                sparse_encodings = [sparse_encoder.encode_document(prop.text) for prop in propositions]
                qdrant = None
                try:
                    qdrant = QdrantAdapter(
                        host=qdrant_host,
                        port=qdrant_port,
                        required=settings.qdrant_required,
                    )
                    collection_name = f"collection_{document.collection_id}_propositions"
                    await qdrant.init_collection(collection_name, embedder.embedding_dim)
                    await qdrant.upsert(
                        collection_name,
                        [
                            QdrantDocument(
                                id=prop.id,
                                vector=vector,
                                payload={
                                    "document_id": prop.document_id,
                                    "collection_id": document.collection_id,
                                    "proposition_id": prop.id,
                                    "title": document.title,
                                    "text": prop.text,
                                    "kind": prop.kind,
                                    "source_chunk_id": prop.source_chunk_id,
                                    "sparse_encoder": sparse_encoder.encoder_name,
                                    "sparse_fallback": sparse_encoder.uses_fallback,
                                },
                                sparse_indices=sparse[0],
                                sparse_values=sparse[1],
                            )
                            for prop, vector, sparse in zip(propositions, vectors, sparse_encodings, strict=False)
                        ],
                    )
                except Exception:
                    if settings.strict_mode_enabled:
                        raise
                    qdrant = None

                step.metrics(
                    embedded_propositions=len(propositions),
                    embedding_dim=embedder.embedding_dim,
                    fallback_embeddings=embedder.uses_fallback,
                    qdrant_available=bool(qdrant and qdrant.is_available),
                )

            await session.commit()

            if qdrant is None:
                return {"embedded_propositions": len(propositions), "qdrant": "unavailable"}

            return {"embedded_propositions": len(propositions)}


class GenerateSummariesJobHandler(BaseJobHandler):
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        document_id = job.target_id
        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            chunk_repo = SqlChunkRepository(session)
            proposition_repo = SqlPropositionRepository(session)
            summary_repo = SqlSummaryRepository(session)
            job_repo = SqlJobRepository(session)
            audit = PipelineAuditService(session=session)

            document = await doc_repo.get_by_id(document_id)
            if document is None:
                raise ValueError(f"Document {document_id} not found")

            chunks = await chunk_repo.get_by_document(document_id)
            propositions = await proposition_repo.list_by_document(document_id)

            async with audit.step(
                run_id=job.id,
                entity_type="document",
                entity_id=document_id,
                pipeline="memory_enrichment",
                stage="generate_summaries",
                context={"chunk_count": len(chunks), "proposition_count": len(propositions)},
            ) as step:
                section_summaries: list[SummaryNode] = []
                for chunk in chunks:
                    section_summaries.append(
                        SummaryNode(
                            id=new_id(),
                            scope_type="section",
                            scope_id=chunk.id,
                            text=summarize_texts([chunk.summary or chunk.text]),
                        )
                    )

                document_summary = SummaryNode(
                    id=new_id(),
                    scope_type="document",
                    scope_id=document.id,
                    text=summarize_texts([prop.text for prop in propositions] or [chunk.text for chunk in chunks]),
                )

                collection_summary = SummaryNode(
                    id=new_id(),
                    scope_type="collection",
                    scope_id=document.collection_id,
                    text=summarize_texts([document_summary.text] + [chunk.summary or chunk.text for chunk in chunks]),
                )

                summaries = [*section_summaries, document_summary, collection_summary]
                await summary_repo.create_many(summaries)
                step.metrics(summaries_created=len(summaries), summary_scopes=[summary.scope_type for summary in summaries])

            await job_repo.create(Job(id=new_id(), job_type=JobType.EMBED_SUMMARIES, target_id=document_id))
            await session.commit()
            return {"summaries_created": len(summaries)}


class EmbedSummariesJobHandler(BaseJobHandler):
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        document_id = job.target_id
        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            summary_repo = SqlSummaryRepository(session)
            chunk_repo = SqlChunkRepository(session)
            audit = PipelineAuditService(session=session)

            document = await doc_repo.get_by_id(document_id)
            if document is None:
                raise ValueError(f"Document {document_id} not found")

            summaries = await summary_repo.list_by_document(document_id)
            summaries.extend(await summary_repo.list_by_collection(document.collection_id))
            for chunk in await chunk_repo.get_by_document(document_id):
                summaries.extend(await summary_repo.list_by_scope("section", chunk.id))
            if not summaries:
                return {"embedded_summaries": 0}

            async with audit.step(
                run_id=job.id,
                entity_type="document",
                entity_id=document_id,
                pipeline="memory_enrichment",
                stage="embed_summaries",
                context={"summary_count": len(summaries)},
            ) as step:
                settings = get_settings()
                qdrant_endpoint = urlparse(settings.qdrant_url)
                qdrant_host = qdrant_endpoint.hostname or "localhost"
                qdrant_port = qdrant_endpoint.port or 6333

                embedder = EmbeddingGemmaAdapter(
                    dim=settings.embedding_dimensions,
                    required=settings.embeddings_required,
                )
                vectors = await embedder.embed([summary.text for summary in summaries])

                # Quantize and index candidates using IngestionOrchestrator
                from atenex_nova.application.orchestrators.ingestion_orchestrator import (
                    IngestionOrchestrator,
                )
                ingestion_orch = IngestionOrchestrator(session)
                await ingestion_orch.index_nodes(
                    collection_id=str(document.collection_id),
                    memory_layer="summary",
                    node_ids=[summary.id for summary in summaries],
                    vectors=vectors,
                    embedding_model=settings.embedding_model,
                    dimension=settings.embedding_dimensions,
                )

                sparse_encoder = StableSparseEncoder()
                sparse_encodings = [sparse_encoder.encode_document(summary.text) for summary in summaries]
                qdrant_unavailable = False

                try:
                    qdrant = QdrantAdapter(
                        host=qdrant_host,
                        port=qdrant_port,
                        required=settings.qdrant_required,
                    )
                    collection_name = f"collection_{document.collection_id}_summaries"
                    await qdrant.init_collection(collection_name, embedder.embedding_dim)
                    await qdrant.upsert(
                        collection_name,
                        [
                            QdrantDocument(
                                id=summary.id,
                                vector=vector,
                                payload={
                                    "scope_type": summary.scope_type,
                                    "scope_id": summary.scope_id,
                                    "collection_id": document.collection_id,
                                    "title": document.title,
                                    "text": summary.text,
                                    "sparse_encoder": sparse_encoder.encoder_name,
                                    "sparse_fallback": sparse_encoder.uses_fallback,
                                },
                                sparse_indices=sparse[0],
                                sparse_values=sparse[1],
                            )
                            for summary, vector, sparse in zip(summaries, vectors, sparse_encodings, strict=False)
                        ],
                    )
                except Exception:
                    if settings.strict_mode_enabled:
                        raise
                    qdrant_unavailable = True
                    step.metrics(embedded_summaries=len(summaries), qdrant_available=False)
                else:
                    step.metrics(
                        embedded_summaries=len(summaries),
                        embedding_dim=embedder.embedding_dim,
                        fallback_embeddings=embedder.uses_fallback,
                        qdrant_available=True,
                    )

            await session.commit()
            if qdrant_unavailable:
                return {"embedded_summaries": len(summaries), "qdrant": "unavailable"}

            return {"embedded_summaries": len(summaries)}


class BuildGraphJobHandler(BaseJobHandler):
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        document_id = job.target_id
        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            proposition_repo = SqlPropositionRepository(session)
            job_repo = SqlJobRepository(session)
            graph_store = GraphStore(session)
            audit = PipelineAuditService(session=session)

            document = await doc_repo.get_by_id(document_id)
            if document is None:
                raise ValueError(f"Document {document_id} not found")

            propositions = await proposition_repo.list_by_document(document_id)
            async with audit.step(
                run_id=job.id,
                entity_type="document",
                entity_id=document_id,
                pipeline="memory_enrichment",
                stage="build_graph",
                context={"proposition_count": len(propositions)},
            ) as step:
                edges: list[RelationEdge] = []
                for proposition in propositions:
                    edges.append(
                        RelationEdge(
                            id=new_id(),
                            source_type="proposition",
                            source_id=proposition.id,
                            target_type="document",
                            target_id=document_id,
                            relation=RelationType.APPEARS_IN.value,
                            weight=1.0,
                        )
                    )
                for left, right in itertools.pairwise(propositions):
                    relation = RelationType.ELABORATES.value
                    lower = f"{left.text} {right.text}".lower()
                    if any(marker in lower for marker in ("however", "but", "sin embargo")):
                        relation = RelationType.CONTRADICTS.value
                    elif any(marker in lower for marker in ("means", "defines", "se define")):
                        relation = RelationType.DEFINES.value
                    elif any(marker in lower for marker in ("because", "causes", "provoca")):
                        relation = RelationType.SUPPORTS.value
                    edges.append(
                        RelationEdge(
                            id=new_id(),
                            source_type="proposition",
                            source_id=left.id,
                            target_type="proposition",
                            target_id=right.id,
                            relation=relation,
                            weight=0.8,
                        )
                    )

                # --- CONCEPT-BASED CROSS-REFERENCES ---
                en_stopwords = {
                    "the", "and", "a", "of", "to", "in", "is", "that", "it", "on", "for", "with", "as", "by", "an", "at",
                    "are", "this", "be", "from", "or", "have", "your", "will", "they", "were", "been", "was", "these",
                    "those", "their", "there", "about", "which", "would", "could", "should", "other", "some", "more",
                    "most", "each", "both", "such", "under", "after", "before", "between", "through", "during"
                }
                es_stopwords = {
                    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "en", "para", "por", "con", "como",
                    "sobre", "entre", "desde", "hasta", "hacia", "donde", "cuando", "quien", "que", "este", "esta",
                    "esto", "estos", "estas", "todo", "toda", "todos", "todas", "pero", "sino", "solo", "solamente",
                    "también", "tampoco", "contra", "bajo", "cabe", "ante", "tras", "cual", "cuales", "quienes",
                    "cuyo", "cuya", "cuyos", "cuyas"
                }
                stopwords = en_stopwords.union(es_stopwords)

                def extract_keywords(text: str) -> set[str]:
                    import re
                    cleaned = re.sub(r"[^\w\s]", " ", text)
                    words = cleaned.split()
                    keywords = set()
                    for w in words:
                        w_lower = w.lower()
                        if len(w_lower) >= 5 and w_lower not in stopwords:
                            keywords.add(w_lower)
                    return keywords

                prop_keywords = []
                keyword_counts: dict[str, int] = {}
                for prop in propositions:
                    kws = extract_keywords(prop.text)
                    prop_keywords.append(kws)
                    for kw in kws:
                        keyword_counts[kw] = keyword_counts.get(kw, 0) + 1

                threshold = max(2, len(propositions) * 0.25)
                filtered_keywords = []
                for kws in prop_keywords:
                    valid_kws = {kw for kw in kws if keyword_counts.get(kw, 0) <= threshold}
                    filtered_keywords.append(valid_kws)

                cross_ref_count = {prop.id: 0 for prop in propositions}
                for i, prop1 in enumerate(propositions):
                    kws1 = filtered_keywords[i]
                    if not kws1:
                        continue
                    for j in range(i + 2, len(propositions)):
                        prop2 = propositions[j]
                        if cross_ref_count[prop1.id] >= 5 or cross_ref_count[prop2.id] >= 5:
                            continue
                        kws2 = filtered_keywords[j]
                        shared = kws1.intersection(kws2)
                        if shared:
                            edges.append(
                                RelationEdge(
                                    id=new_id(),
                                    source_type="proposition",
                                    source_id=prop1.id,
                                    target_type="proposition",
                                    target_id=prop2.id,
                                    relation=RelationType.MENTIONS.value,
                                    weight=0.6,
                                )
                            )
                            cross_ref_count[prop1.id] += 1
                            cross_ref_count[prop2.id] += 1

                await graph_store.upsert_edges(edges)
                step.metrics(graph_edges_created=len(edges), relation_types=sorted({edge.relation for edge in edges}))

            await job_repo.create(Job(id=new_id(), job_type=JobType.INDEX_VISUAL_PAGES, target_id=document_id))
            await session.commit()
            return {"graph_edges_created": len(edges)}

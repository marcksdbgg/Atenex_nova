"""Job handlers for phase 4 memory enrichment."""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from atenex_nova.application.policies.indexing_policy import dense_goes_to_qdrant
from atenex_nova.application.policies.visual_index_policy import should_index_visual
from atenex_nova.application.services.document_readiness_service import (
    DocumentReadinessService,
)
from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.entities.proposition import Proposition
from atenex_nova.domain.entities.relation_edge import RelationEdge
from atenex_nova.domain.entities.summary_node import SummaryNode
from atenex_nova.domain.value_objects.identifiers import JobType, RelationType, new_id
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import SqlPropositionRepository
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository
from atenex_nova.infrastructure.embeddings.bm25_encoder import StableSparseEncoder
from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.infrastructure.graph.graph_store import GraphStore
from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter, QdrantDocument
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import ServiceUnavailableError
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService
from atenex_nova.workers.runner import BaseJobHandler

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
WORD_RE = re.compile(r"[\w\-]+", flags=re.UNICODE)
SUMMARY_METHOD = "ordered_extractive_v2"
COLLECTION_MEMORY_DEFAULT_BATCH_SIZE = 32
COLLECTION_MEMORY_MAX_BATCH_SIZE = 128
GRAPH_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "after",
        "an",
        "and",
        "ante",
        "are",
        "as",
        "at",
        "be",
        "been",
        "before",
        "between",
        "both",
        "bajo",
        "by",
        "cabe",
        "como",
        "con",
        "contra",
        "could",
        "cual",
        "cuales",
        "cuando",
        "cuya",
        "cuyas",
        "cuyo",
        "cuyos",
        "de",
        "desde",
        "donde",
        "during",
        "each",
        "el",
        "en",
        "entre",
        "esta",
        "estas",
        "este",
        "estos",
        "esto",
        "from",
        "for",
        "hacia",
        "hasta",
        "have",
        "in",
        "is",
        "it",
        "la",
        "las",
        "los",
        "more",
        "most",
        "of",
        "on",
        "or",
        "other",
        "para",
        "pero",
        "por",
        "que",
        "quien",
        "quienes",
        "should",
        "sino",
        "solo",
        "solamente",
        "some",
        "sobre",
        "such",
        "también",
        "tampoco",
        "that",
        "the",
        "their",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "todo",
        "toda",
        "todos",
        "todas",
        "tras",
        "un",
        "una",
        "unas",
        "under",
        "unos",
        "was",
        "were",
        "will",
        "with",
        "would",
        "which",
        "your",
    }
)


@dataclass(frozen=True)
class SummaryEvidence:
    source_index: int
    sentence_index: int


@dataclass(frozen=True)
class ExtractiveSummary:
    text: str
    evidence: tuple[SummaryEvidence, ...]


@dataclass(frozen=True)
class MemoryAggregate:
    text: str
    selected_source_ids: tuple[str, ...]
    source_count: int


def split_sentences(text: str) -> list[str]:
    sentences = [segment.strip() for segment in SENTENCE_RE.split(text) if segment.strip()]
    return [sentence for sentence in sentences if len(sentence) > 20]


def _chunk_order_key(chunk: Chunk) -> tuple[int, int, str]:
    raw_index = chunk.metadata.get("chunk_index", 1_000_000)
    try:
        chunk_index = int(raw_index)
    except (TypeError, ValueError):
        chunk_index = 1_000_000

    raw_pages = chunk.metadata.get("page_numbers")
    page_numbers: list[int] = []
    if isinstance(raw_pages, list):
        for raw_page in raw_pages:
            try:
                page_numbers.append(int(raw_page))
            except (TypeError, ValueError):
                continue
    return chunk_index, min(page_numbers, default=1_000_000), chunk.id


def _order_propositions_for_graph(
    propositions: list[Proposition],
    chunks: list[Chunk],
) -> list[Proposition]:
    """Restore source order explicitly instead of relying on SQL row order."""
    ordered_chunks = sorted(chunks, key=_chunk_order_key)
    chunk_rank = {chunk.id: index for index, chunk in enumerate(ordered_chunks)}
    sentence_rank: dict[tuple[str, str], int] = {}
    for chunk in ordered_chunks:
        for index, sentence in enumerate(split_sentences(chunk.text or chunk.summary)):
            sentence_rank.setdefault((chunk.id, sentence), index)

    missing_rank = len(ordered_chunks) + 1
    return sorted(
        propositions,
        key=lambda proposition: (
            chunk_rank.get(proposition.source_chunk_id, missing_rank),
            sentence_rank.get(
                (proposition.source_chunk_id, proposition.text),
                1_000_000,
            ),
            proposition.text.casefold(),
            proposition.kind,
            proposition.id,
        ),
    )


def _build_cross_reference_edges(
    propositions: list[Proposition],
) -> list[RelationEdge]:
    """Build bounded keyword links with an exact early exit for saturated sources."""

    def extract_keywords(text: str) -> set[str]:
        cleaned = re.sub(r"[^\w\s]", " ", text)
        return {
            word_lower
            for word in cleaned.split()
            if len(word_lower := word.lower()) >= 5
            and word_lower not in GRAPH_STOPWORDS
        }

    proposition_keywords: list[set[str]] = []
    keyword_counts: dict[str, int] = {}
    for proposition in propositions:
        keywords = extract_keywords(proposition.text)
        proposition_keywords.append(keywords)
        for keyword in keywords:
            keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1

    threshold = max(2, len(propositions) * 0.25)
    filtered_keywords = [
        {
            keyword
            for keyword in keywords
            if keyword_counts.get(keyword, 0) <= threshold
        }
        for keywords in proposition_keywords
    ]

    edges: list[RelationEdge] = []
    cross_reference_count = {proposition.id: 0 for proposition in propositions}
    for index, source in enumerate(propositions):
        source_keywords = filtered_keywords[index]
        if not source_keywords or cross_reference_count[source.id] >= 5:
            continue
        for target_index in range(index + 2, len(propositions)):
            if cross_reference_count[source.id] >= 5:
                break
            target = propositions[target_index]
            if cross_reference_count[target.id] >= 5:
                continue
            if source_keywords.intersection(filtered_keywords[target_index]):
                edges.append(
                    RelationEdge(
                        id=new_id(),
                        source_type="proposition",
                        source_id=source.id,
                        target_type="proposition",
                        target_id=target.id,
                        relation=RelationType.MENTIONS.value,
                        weight=0.6,
                    )
                )
                cross_reference_count[source.id] += 1
                cross_reference_count[target.id] += 1
    return edges


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


def deterministic_summary_id(scope_type: str, scope_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"atenex:summary:{scope_type}:{scope_id}"))


def extractive_summary(texts: list[str], max_sentences: int = 3) -> ExtractiveSummary:
    """Select grounded sentences while restoring their original source order."""
    if max_sentences < 1:
        raise ValueError("max_sentences must be positive")

    candidates: list[tuple[int, int, str, tuple[str, ...]]] = []
    seen_text: set[str] = set()
    for source_index, raw_text in enumerate(texts):
        normalized_source = " ".join(str(raw_text).split())
        if not normalized_source:
            continue
        source_sentences = [
            " ".join(item.split())
            for item in SENTENCE_RE.split(normalized_source)
            if item.strip()
        ] or [normalized_source]
        for sentence_index, sentence in enumerate(source_sentences):
            dedupe_key = sentence.casefold()
            if dedupe_key in seen_text:
                continue
            seen_text.add(dedupe_key)
            tokens = tuple(
                token.casefold()
                for token in WORD_RE.findall(sentence)
                if len(token) > 3
            )
            candidates.append((source_index, sentence_index, sentence, tokens))

    if not candidates:
        return ExtractiveSummary(text="", evidence=())

    corpus_frequency: Counter[str] = Counter(
        token for _, _, _, tokens in candidates for token in set(tokens)
    )
    ranked: list[tuple[float, int]] = []
    for index, (_, _, sentence, tokens) in enumerate(candidates):
        if tokens:
            topicality = sum(corpus_frequency[token] for token in tokens)
            score = topicality / math.sqrt(len(tokens))
        else:
            score = min(len(sentence), 120) / 120.0
        ranked.append((score, index))

    chosen: list[int] = []
    chosen_token_sets: list[set[str]] = []
    for _, candidate_index in sorted(
        ranked,
        key=lambda item: (
            -item[0],
            candidates[item[1]][0],
            candidates[item[1]][1],
        ),
    ):
        candidate_tokens = set(candidates[candidate_index][3])
        if candidate_tokens and any(
            len(candidate_tokens & previous) / max(1, len(candidate_tokens | previous)) >= 0.8
            for previous in chosen_token_sets
        ):
            continue
        chosen.append(candidate_index)
        chosen_token_sets.append(candidate_tokens)
        if len(chosen) >= max_sentences:
            break

    chosen.sort(key=lambda index: (candidates[index][0], candidates[index][1]))
    return ExtractiveSummary(
        text=" ".join(candidates[index][2] for index in chosen),
        evidence=tuple(
            SummaryEvidence(
                source_index=candidates[index][0],
                sentence_index=candidates[index][1],
            )
            for index in chosen
        ),
    )


def summarize_texts(texts: list[str], max_sentences: int = 3) -> str:
    """Backward-compatible text-only wrapper for the extractive fallback."""
    return extractive_summary(texts, max_sentences=max_sentences).text


async def _enqueue_readiness_check(job_repo: SqlJobRepository, document_id: str) -> bool:
    _, created = await job_repo.ensure_pending(
        job_type=JobType.CHECK_DOCUMENT_READINESS,
        target_id=document_id,
    )
    return created


def _reduce_memory_level(
    aggregates: list[MemoryAggregate],
    *,
    batch_size: int,
) -> list[MemoryAggregate]:
    reduced: list[MemoryAggregate] = []
    for start in range(0, len(aggregates), batch_size):
        batch = aggregates[start : start + batch_size]
        extracted = extractive_summary(
            [item.text for item in batch],
            max_sentences=min(6, len(batch)),
        )
        selected_indexes = tuple(
            dict.fromkeys(evidence.source_index for evidence in extracted.evidence)
        )
        selected_source_ids = tuple(
            dict.fromkeys(
                source_id
                for index in selected_indexes
                for source_id in batch[index].selected_source_ids
            )
        )
        reduced.append(
            MemoryAggregate(
                text=extracted.text,
                selected_source_ids=selected_source_ids,
                source_count=sum(item.source_count for item in batch),
            )
        )
    return reduced


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

            chunks = sorted(
                await chunk_repo.get_by_document(document_id),
                key=_chunk_order_key,
            )
            async with audit.step(
                run_id=job.id,
                entity_type="document",
                entity_id=document_id,
                pipeline="memory_enrichment",
                stage="extract_propositions",
                context={"chunk_count": len(chunks)},
            ) as step:
                propositions = await proposition_repo.list_by_document(document_id)
                propositions_created = 0
                if not propositions:
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
                    propositions_created = len(propositions)
                step.metrics(
                    propositions_created=propositions_created,
                    propositions_reused=len(propositions) - propositions_created,
                    proposition_types=sorted({prop.kind for prop in propositions}),
                )

            for job_type in (
                JobType.EMBED_PROPOSITIONS,
                JobType.GENERATE_SUMMARIES,
                JobType.BUILD_GRAPH,
            ):
                await job_repo.ensure_pending(job_type=job_type, target_id=document_id)

            await session.commit()
            return {
                "propositions_created": propositions_created,
                "propositions_total": len(propositions),
            }


class EmbedPropositionsJobHandler(BaseJobHandler):
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        document_id = job.target_id
        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            proposition_repo = SqlPropositionRepository(session)
            job_repo = SqlJobRepository(session)
            audit = PipelineAuditService(session=session)

            document = await doc_repo.get_by_id(document_id)
            if document is None:
                raise ValueError(f"Document {document_id} not found")

            all_propositions = await proposition_repo.list_by_document(document_id)
            propositions = [prop for prop in all_propositions if not prop.embedding_ref]
            if not propositions:
                await _enqueue_readiness_check(job_repo, document_id)
                await session.commit()
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
                embedder.ensure_indexable()
                proposition_texts = [prop.text for prop in propositions]
                vectors = await embedder.embed_documents(
                    proposition_texts,
                    titles=[document.title] * len(proposition_texts),
                )

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
                    store_dense_in_qdrant = dense_goes_to_qdrant(settings)
                    await qdrant.init_collection(
                        collection_name,
                        embedder.embedding_dim,
                        dense_enabled=store_dense_in_qdrant,
                    )
                    await qdrant.upsert(
                        collection_name,
                        [
                            QdrantDocument(
                                id=prop.id,
                                vector=vector if store_dense_in_qdrant else None,
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
                                    "embedding_contract": settings.embedding_contract_fingerprint,
                                },
                                sparse_indices=sparse[0],
                                sparse_values=sparse[1],
                            )
                            for prop, vector, sparse in zip(propositions, vectors, sparse_encodings, strict=False)
                        ],
                    )
                except ServiceUnavailableError:
                    raise
                except Exception:
                    if settings.qdrant_required:
                        raise
                    qdrant = None

                step.metrics(
                    embedded_propositions=len(propositions),
                    embedding_dim=embedder.embedding_dim,
                    fallback_embeddings=embedder.uses_fallback,
                    qdrant_available=bool(qdrant and qdrant.is_available),
                )

            await proposition_repo.mark_embedded(
                [proposition.id for proposition in propositions],
                embedding_ref="quantized_vectors",
            )
            await _enqueue_readiness_check(job_repo, document_id)
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
            chunks.sort(key=_chunk_order_key)

            async with audit.step(
                run_id=job.id,
                entity_type="document",
                entity_id=document_id,
                pipeline="memory_enrichment",
                stage="generate_summaries",
                context={"chunk_count": len(chunks), "proposition_count": len(propositions)},
            ) as step:
                changed_count = 0
                duplicate_ids_removed: list[str] = []
                desired_section_summaries: list[SummaryNode] = []
                for chunk in chunks:
                    extracted = extractive_summary([chunk.text], max_sentences=3)
                    desired_section_summaries.append(
                        SummaryNode(
                            id=deterministic_summary_id("section", chunk.id),
                            scope_type="section",
                            scope_id=chunk.id,
                            text=extracted.text,
                            provenance={
                                "method": SUMMARY_METHOD,
                                "source_scope_type": "chunk",
                                "source_scope_ids": [chunk.id],
                                "selected": [
                                    {
                                        "scope_id": chunk.id,
                                        "sentence_index": evidence.sentence_index,
                                    }
                                    for evidence in extracted.evidence
                                ],
                            },
                        )
                    )

                section_results = await summary_repo.upsert_scopes(
                    desired_section_summaries
                )
                section_summaries = [result.summary for result in section_results]
                changed_count += sum(
                    int(result.content_changed) for result in section_results
                )
                duplicate_ids_removed.extend(
                    removed_id
                    for result in section_results
                    for removed_id in result.removed_ids
                )

                section_texts = [summary.text for summary in section_summaries]
                section_ids = [summary.id for summary in section_summaries]
                document_extracted = extractive_summary(
                    section_texts or [document.title],
                    max_sentences=6,
                )
                document_source_ids = section_ids or [document.id]
                document_summary_result = await summary_repo.upsert_scope(
                    SummaryNode(
                        id=deterministic_summary_id("document", document.id),
                        scope_type="document",
                        scope_id=document.id,
                        text=document_extracted.text,
                        provenance={
                            "method": SUMMARY_METHOD,
                            "source_scope_type": (
                                "section_summary" if section_ids else "document_metadata"
                            ),
                            "source_scope_ids": document_source_ids,
                            "selected": [
                                {
                                    "scope_id": document_source_ids[evidence.source_index],
                                    "sentence_index": evidence.sentence_index,
                                }
                                for evidence in document_extracted.evidence
                            ],
                        },
                    )
                )
                document_summary = document_summary_result.summary
                changed_count += int(document_summary_result.content_changed)
                duplicate_ids_removed.extend(document_summary_result.removed_ids)

                summaries = [*section_summaries, document_summary]
                step.metrics(
                    summaries_total=len(summaries),
                    summaries_changed=changed_count,
                    duplicate_summaries_removed=len(duplicate_ids_removed),
                    summary_scopes=[summary.scope_type for summary in summaries],
                    proposition_count=len(propositions),
                )

            await job_repo.ensure_pending(
                job_type=JobType.EMBED_SUMMARIES,
                target_id=document_id,
                payload={"summary_ids": [summary.id for summary in summaries]},
            )
            await session.commit()
            return {
                "summaries_total": len(summaries),
                "summaries_changed": changed_count,
                "duplicate_summaries_removed": len(duplicate_ids_removed),
            }


class EmbedSummariesJobHandler(BaseJobHandler):
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        document_id = job.target_id
        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            summary_repo = SqlSummaryRepository(session)
            chunk_repo = SqlChunkRepository(session)
            job_repo = SqlJobRepository(session)
            audit = PipelineAuditService(session=session)

            document = await doc_repo.get_by_id(document_id)
            if document is None:
                raise ValueError(f"Document {document_id} not found")

            payload_ids = (getattr(job, "payload", None) or {}).get("summary_ids")
            if isinstance(payload_ids, list) and payload_ids:
                summaries = await summary_repo.get_by_ids([str(item) for item in payload_ids])
            else:
                summaries = await summary_repo.list_by_document(document_id)
                for chunk in await chunk_repo.get_by_document(document_id):
                    summaries.extend(await summary_repo.list_by_scope("section", chunk.id))

            # Never re-embed the entire collection summary set per document (O(N²)).
            summaries = [summary for summary in summaries if summary.scope_type != "collection"]
            summaries = [summary for summary in summaries if not summary.embedding_ref]
            seen_ids: set[str] = set()
            deduped: list[SummaryNode] = []
            for summary in summaries:
                if summary.id in seen_ids:
                    continue
                seen_ids.add(summary.id)
                deduped.append(summary)
            summaries = deduped
            if not summaries:
                await _enqueue_readiness_check(job_repo, document_id)
                await session.commit()
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
                embedder.ensure_indexable()
                summary_texts = [summary.text for summary in summaries]
                vectors = await embedder.embed_documents(
                    summary_texts,
                    titles=[document.title] * len(summary_texts),
                )

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
                    store_dense_in_qdrant = dense_goes_to_qdrant(settings)
                    await qdrant.init_collection(
                        collection_name,
                        embedder.embedding_dim,
                        dense_enabled=store_dense_in_qdrant,
                    )
                    await qdrant.upsert(
                        collection_name,
                        [
                            QdrantDocument(
                                id=summary.id,
                                vector=vector if store_dense_in_qdrant else None,
                                payload={
                                    "scope_type": summary.scope_type,
                                    "scope_id": summary.scope_id,
                                    "collection_id": document.collection_id,
                                    "document_id": document.id,
                                    "title": document.title,
                                    "text": summary.text,
                                    "provenance": summary.provenance,
                                    "sparse_encoder": sparse_encoder.encoder_name,
                                    "sparse_fallback": sparse_encoder.uses_fallback,
                                    "embedding_contract": settings.embedding_contract_fingerprint,
                                },
                                sparse_indices=sparse[0],
                                sparse_values=sparse[1],
                            )
                            for summary, vector, sparse in zip(summaries, vectors, sparse_encodings, strict=False)
                        ],
                    )
                except ServiceUnavailableError:
                    raise
                except Exception:
                    if settings.qdrant_required:
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

            await summary_repo.mark_embedded(
                [summary.id for summary in summaries],
                embedding_ref="quantized_vectors",
            )
            await _enqueue_readiness_check(job_repo, document_id)
            await session.commit()
            if qdrant_unavailable:
                return {"embedded_summaries": len(summaries), "qdrant": "unavailable"}

            return {"embedded_summaries": len(summaries)}


class BuildCollectionMemoryJobHandler(BaseJobHandler):
    """Build one collection memory node from READY document summaries in O(N)."""

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        collection_id = job.target_id
        requested_batch_size = int(
            (job.payload or {}).get("batch_size", COLLECTION_MEMORY_DEFAULT_BATCH_SIZE)
        )
        batch_size = min(
            COLLECTION_MEMORY_MAX_BATCH_SIZE,
            max(2, requested_batch_size),
        )

        async with self.session_factory() as session:
            collection_repo = SqlCollectionRepository(session)
            summary_repo = SqlSummaryRepository(session)
            job_repo = SqlJobRepository(session)
            audit = PipelineAuditService(session=session)

            collection = await collection_repo.get_by_id(collection_id)
            if collection is None:
                raise ValueError(f"Collection {collection_id} not found")

            async with audit.step(
                run_id=job.id,
                entity_type="collection",
                entity_id=collection_id,
                pipeline="memory_enrichment",
                stage="build_collection_memory",
                context={"batch_size": batch_size},
            ) as step:
                cursor: tuple[str, str] | None = None
                previous_scope_id: str | None = None
                source_count = 0
                source_digest = hashlib.sha256()
                leaf_aggregates: list[MemoryAggregate] = []

                while True:
                    page = await summary_repo.list_document_summaries_page(
                        collection_id,
                        limit=batch_size,
                        after=cursor,
                        ready_only=True,
                    )
                    if not page:
                        break
                    cursor = (page[-1].scope_id, page[-1].id)

                    unique_page: list[SummaryNode] = []
                    for summary in page:
                        if summary.scope_id == previous_scope_id:
                            continue
                        previous_scope_id = summary.scope_id
                        unique_page.append(summary)
                        source_count += 1
                        source_digest.update(summary.id.encode("utf-8"))
                        source_digest.update(b"\0")

                    if not unique_page:
                        continue
                    extracted = extractive_summary(
                        [summary.text for summary in unique_page],
                        max_sentences=min(4, len(unique_page)),
                    )
                    selected_ids = tuple(
                        dict.fromkeys(
                            unique_page[evidence.source_index].id
                            for evidence in extracted.evidence
                        )
                    )
                    leaf_aggregates.append(
                        MemoryAggregate(
                            text=extracted.text,
                            selected_source_ids=selected_ids,
                            source_count=len(unique_page),
                        )
                    )

                existing = await summary_repo.list_by_collection(collection_id)
                existing_ids = [summary.id for summary in existing]
                if not leaf_aggregates:
                    await summary_repo.delete_by_scope("collection", collection_id)
                    await job_repo.ensure_pending(
                        job_type=JobType.EMBED_COLLECTION_MEMORY,
                        target_id=collection_id,
                        payload={
                            "obsolete_summary_ids": existing_ids,
                            "delete_only": True,
                        },
                        merge_pending_payload=True,
                    )
                    step.metrics(
                        source_document_summaries=0,
                        collection_summary_created=False,
                        obsolete_summaries=len(existing_ids),
                    )
                    await session.commit()
                    return {
                        "source_document_summaries": 0,
                        "collection_summary_created": False,
                    }

                aggregates = leaf_aggregates
                hierarchy_levels = 1
                while len(aggregates) > 1:
                    aggregates = _reduce_memory_level(aggregates, batch_size=batch_size)
                    hierarchy_levels += 1
                final = aggregates[0]

                desired = SummaryNode(
                    id=deterministic_summary_id("collection", collection_id),
                    scope_type="collection",
                    scope_id=collection_id,
                    text=final.text,
                    provenance={
                        "method": "hierarchical_ordered_extractive_v1",
                        "source_scope_type": "document_summary",
                        "source_summary_count": source_count,
                        "source_summary_ids_sha256": source_digest.hexdigest(),
                        "selected_source_summary_ids": list(final.selected_source_ids),
                        "leaf_batch_count": len(leaf_aggregates),
                        "hierarchy_levels": hierarchy_levels,
                        "batch_size": batch_size,
                    },
                )
                upserted = await summary_repo.upsert_scope(
                    desired,
                    canonical_identifier=True,
                    force_reembed=True,
                )
                obsolete_ids = list(upserted.removed_ids)
                await job_repo.ensure_pending(
                    job_type=JobType.EMBED_COLLECTION_MEMORY,
                    target_id=collection_id,
                    payload={
                        "summary_id": upserted.summary.id,
                        "obsolete_summary_ids": obsolete_ids,
                        "delete_only": False,
                    },
                    merge_pending_payload=True,
                )
                step.metrics(
                    source_document_summaries=source_count,
                    leaf_batches=len(leaf_aggregates),
                    hierarchy_levels=hierarchy_levels,
                    selected_sources=len(final.selected_source_ids),
                    obsolete_summaries=len(obsolete_ids),
                )

            await session.commit()
            return {
                "source_document_summaries": source_count,
                "leaf_batches": len(leaf_aggregates),
                "hierarchy_levels": hierarchy_levels,
                "summary_id": upserted.summary.id,
                "obsolete_summaries": len(obsolete_ids),
            }


class EmbedCollectionMemoryJobHandler(BaseJobHandler):
    """Replace collection-summary vector representations atomically by scope."""

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        collection_id = job.target_id
        async with self.session_factory() as session:
            collection_repo = SqlCollectionRepository(session)
            summary_repo = SqlSummaryRepository(session)
            audit = PipelineAuditService(session=session)
            collection = await collection_repo.get_by_id(collection_id)
            if collection is None:
                raise ValueError(f"Collection {collection_id} not found")

            obsolete_ids = [
                str(item)
                for item in (job.payload or {}).get("obsolete_summary_ids", [])
            ]
            settings = get_settings()

            from atenex_nova.infrastructure.indexes.candidate_index_factory import (
                build_candidate_index,
            )
            from atenex_nova.infrastructure.indexes.quantized_code_store import (
                QuantizedCodeStore,
            )

            if obsolete_ids:
                await build_candidate_index(session).remove_vectors(
                    collection_id,
                    obsolete_ids,
                )
                await QuantizedCodeStore(session).delete_by_node_ids(obsolete_ids)

            qdrant_endpoint = urlparse(settings.qdrant_url)
            qdrant = QdrantAdapter(
                host=qdrant_endpoint.hostname or "localhost",
                port=qdrant_endpoint.port or 6333,
                required=settings.qdrant_required,
            )
            qdrant_collection = f"collection_{collection_id}_summaries"
            await qdrant.delete_by_filter(
                qdrant_collection,
                {"scope_type": "collection", "scope_id": collection_id},
            )

            summaries = await summary_repo.list_by_collection(collection_id)
            if not summaries or bool((job.payload or {}).get("delete_only")):
                await session.commit()
                return {
                    "embedded_collection_summaries": 0,
                    "obsolete_summaries_removed": len(obsolete_ids),
                }
            if len(summaries) != 1:
                raise ValueError(
                    f"Collection {collection_id} must have exactly one summary, got {len(summaries)}"
                )
            summary = summaries[0]

            async with audit.step(
                run_id=job.id,
                entity_type="collection",
                entity_id=collection_id,
                pipeline="memory_enrichment",
                stage="embed_collection_memory",
                context={"summary_id": summary.id},
            ) as step:
                embedder = EmbeddingGemmaAdapter(
                    dim=settings.embedding_dimensions,
                    required=settings.embeddings_required,
                )
                embedder.ensure_indexable()
                vectors = await embedder.embed_documents(
                    [summary.text],
                    titles=[collection.name],
                )

                from atenex_nova.application.orchestrators.ingestion_orchestrator import (
                    IngestionOrchestrator,
                )

                await IngestionOrchestrator(session).index_nodes(
                    collection_id=collection_id,
                    memory_layer="summary",
                    node_ids=[summary.id],
                    vectors=vectors,
                    embedding_model=settings.embedding_model,
                    dimension=settings.embedding_dimensions,
                )

                sparse_encoder = StableSparseEncoder()
                sparse_indices, sparse_values = sparse_encoder.encode_document(summary.text)
                store_dense_in_qdrant = dense_goes_to_qdrant(settings)
                await qdrant.init_collection(
                    qdrant_collection,
                    embedder.embedding_dim,
                    dense_enabled=store_dense_in_qdrant,
                )
                await qdrant.upsert(
                    qdrant_collection,
                    [
                        QdrantDocument(
                            id=summary.id,
                            vector=vectors[0] if store_dense_in_qdrant else None,
                            payload={
                                "scope_type": summary.scope_type,
                                "scope_id": summary.scope_id,
                                "collection_id": collection_id,
                                "title": collection.name,
                                "text": summary.text,
                                "provenance": summary.provenance,
                                "sparse_encoder": sparse_encoder.encoder_name,
                                "sparse_fallback": sparse_encoder.uses_fallback,
                                "embedding_contract": settings.embedding_contract_fingerprint,
                            },
                            sparse_indices=sparse_indices,
                            sparse_values=sparse_values,
                        )
                    ],
                )
                await summary_repo.mark_embedded(
                    [summary.id],
                    embedding_ref="quantized_vectors",
                )
                step.metrics(
                    embedded_collection_summaries=1,
                    embedding_dim=embedder.embedding_dim,
                    fallback_embeddings=embedder.uses_fallback,
                    qdrant_available=qdrant.is_available,
                )

            await session.commit()
            return {
                "embedded_collection_summaries": 1,
                "summary_id": summary.id,
                "obsolete_summaries_removed": len(obsolete_ids),
            }


class CheckDocumentReadinessJobHandler(BaseJobHandler):
    """Publish READY only after every required memory layer is proven complete."""

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        async with self.session_factory() as session:
            document_repo = SqlDocumentRepository(session)
            document = await document_repo.get_by_id(job.target_id)
            if document is None:
                raise ValueError(f"Document {job.target_id} not found")

            report = await DocumentReadinessService(
                session,
                get_settings(),
            ).apply_barrier(document)
            await session.commit()
            return {
                "ready": report.ready,
                "missing": list(report.missing),
                "chunk_count": report.chunk_count,
                "proposition_count": report.proposition_count,
                "section_summary_count": report.section_summary_count,
                "document_summary_count": report.document_summary_count,
                "visual_required": report.visual_required,
            }


class BuildGraphJobHandler(BaseJobHandler):
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        document_id = job.target_id
        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            chunk_repo = SqlChunkRepository(session)
            proposition_repo = SqlPropositionRepository(session)
            job_repo = SqlJobRepository(session)
            graph_store = GraphStore(session)
            audit = PipelineAuditService(session=session)

            document = await doc_repo.get_by_id(document_id)
            if document is None:
                raise ValueError(f"Document {document_id} not found")

            chunks = await chunk_repo.get_by_document(document_id)
            propositions = _order_propositions_for_graph(
                await proposition_repo.list_by_document(document_id),
                chunks,
            )
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

                edges.extend(_build_cross_reference_edges(propositions))

                await graph_store.upsert_edges(edges)
                step.metrics(graph_edges_created=len(edges), relation_types=sorted({edge.relation for edge in edges}))

            settings = get_settings()
            if should_index_visual(document, settings):
                await job_repo.ensure_pending(
                    job_type=JobType.INDEX_VISUAL_PAGES,
                    target_id=document_id,
                )
            else:
                async with audit.step(
                    run_id=job.id,
                    entity_type="document",
                    entity_id=document_id,
                    pipeline="visual_indexing",
                    stage="skipped_text_only",
                    context={"mime_type": document.mime_type},
                ) as skip_step:
                    skip_step.metrics(visual_indexing="skipped_text_only")
                await _enqueue_readiness_check(job_repo, document_id)

            await session.commit()
            return {"graph_edges_created": len(edges)}

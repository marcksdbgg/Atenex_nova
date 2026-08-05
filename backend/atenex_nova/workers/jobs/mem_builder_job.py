"""Job handlers for memory building (chunking, embedding, indexing)."""

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from atenex_nova.application.policies.indexing_policy import dense_goes_to_qdrant
from atenex_nova.application.policies.token_budget_policy import TokenBudgetPolicy
from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.document_node import DocumentNode
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.value_objects.identifiers import DocumentStatus, JobType, new_id
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.repositories.sql_node_repo import SqlDocumentNodeRepository
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import SqlPropositionRepository
from atenex_nova.infrastructure.db.repositories.sql_relation_repo import SqlRelationRepository
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository
from atenex_nova.infrastructure.embeddings.bm25_encoder import StableSparseEncoder
from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter, QdrantDocument
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService
from atenex_nova.workers.runner import BaseJobHandler

logger = logging.getLogger(__name__)


def build_document_chunks(
    document_id: str,
    nodes: list[DocumentNode],
    *,
    policy: TokenBudgetPolicy,
    min_tokens: int,
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    """Build hard-bounded chunks while preserving node-local source spans."""
    chunks: list[Chunk] = []
    text_parts: list[str] = []
    node_ids: list[str] = []
    source_spans: list[dict[str, object]] = []
    heading_path: list[str] = []
    page_numbers: list[int] = []
    node_types: list[str] = []
    bboxes: list[dict[str, object]] = []

    def current_text() -> str:
        return "\n\n".join(text_parts)

    def flush() -> None:
        nonlocal text_parts, node_ids, source_spans, heading_path, page_numbers, node_types, bboxes
        if not text_parts:
            return
        text = current_text()
        token_count = policy.estimate_tokens(text)
        if token_count > max_tokens:
            raise ValueError(
                f"chunk budget invariant violated: {token_count} > {max_tokens} tokens"
            )
        chunks.append(
            Chunk(
                id=new_id(),
                document_id=document_id,
                text=text,
                summary=text[:280],
                token_count=max(1, token_count),
                node_ids=list(node_ids),
                metadata={
                    "chunk_index": len(chunks),
                    "heading_path": list(heading_path),
                    "page_numbers": list(page_numbers),
                    "bboxes": list(bboxes),
                    "node_types": list(node_types),
                    "source_spans": list(source_spans),
                    "chunk_max_tokens": max_tokens,
                    "chunk_overlap_tokens": overlap_tokens,
                },
            )
        )
        text_parts = []
        node_ids = []
        source_spans = []
        heading_path = []
        page_numbers = []
        node_types = []
        bboxes = []

    for node in nodes:
        if node.metadata.get("content_role") == "metadata":
            # Keep export envelopes in the source tree for audit/navigation, but do
            # not let administrative headers consume embedding or retrieval budget.
            continue
        source_field = "normalized_text" if node.normalized_text else "raw_text"
        node_text = node.normalized_text or node.raw_text
        if not node_text.strip():
            continue
        segments = policy.split_text(
            node_text,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )
        raw_heading_path = node.metadata.get("heading_path", [])
        candidate_heading_path = (
            [str(item) for item in raw_heading_path]
            if isinstance(raw_heading_path, (list, tuple))
            else []
        )

        for segment_index, segment in enumerate(segments):
            existing_text = current_text()
            candidate_text = (
                f"{existing_text}\n\n{segment.text}" if existing_text else segment.text
            )
            current_tokens = policy.estimate_tokens(existing_text)
            exceeds_budget = policy.estimate_tokens(candidate_text) > max_tokens
            structural_boundary = policy.should_split(
                current_tokens=current_tokens,
                next_node_tokens=segment.token_count,
                node_type=node.node_type.value,
                min_tokens=min_tokens,
                max_tokens=max_tokens,
            )
            if text_parts and (exceeds_budget or structural_boundary):
                flush()

            text_parts.append(segment.text)
            if node.id not in node_ids:
                node_ids.append(node.id)
            span: dict[str, object] = {
                "node_id": node.id,
                "char_start": segment.char_start,
                "char_end": segment.char_end,
                "segment_index": segment_index,
                "segment_count": len(segments),
                "overlap_left": segment_index > 0,
                "source_field": source_field,
            }
            for metadata_key in (
                "source_char_start",
                "source_char_end",
                "content_role",
                "timestamp_start",
                "timestamp_end",
            ):
                metadata_value = node.metadata.get(metadata_key)
                if metadata_value is not None:
                    span[metadata_key] = metadata_value
            source_spans.append(span)
            if not heading_path and candidate_heading_path:
                heading_path = candidate_heading_path
            if node.page_number is not None and node.page_number not in page_numbers:
                page_numbers.append(node.page_number)
            node_types.append(node.node_type.value)
            if node.bbox and node.bbox not in bboxes:
                bboxes.append(node.bbox)

            if policy.estimate_tokens(current_text()) > max_tokens:
                raise ValueError("chunk budget invariant violated after adding a source segment")

    flush()
    return chunks


class SegmentDocumentJobHandler(BaseJobHandler):
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        document_id = job.target_id

        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            node_repo = SqlDocumentNodeRepository(session)
            chunk_repo = SqlChunkRepository(session)
            audit = PipelineAuditService(session=session)

            doc = await doc_repo.get_by_id(document_id)
            if not doc:
                raise ValueError(f"Document {document_id} not found")
            if doc.status == DocumentStatus.FAILED:
                return {"chunks_created": 0, "skipped": "document_failed"}

            nodes = await node_repo.get_by_document(document_id)
            if doc.status in {DocumentStatus.SEGMENTED, DocumentStatus.EMBEDDED, DocumentStatus.INDEXED, DocumentStatus.READY}:
                existing_chunks = await chunk_repo.get_by_document(document_id)
                if existing_chunks:
                    return {"chunks_created": len(existing_chunks), "skipped": "already_segmented"}

            async with audit.step(
                run_id=job.id,
                entity_type="document",
                entity_id=document_id,
                pipeline="memory_building",
                stage="segment",
                context={"node_count": len(nodes)},
            ) as step:
                settings = get_settings()
                policy = TokenBudgetPolicy()
                chunks = build_document_chunks(
                    document_id,
                    nodes,
                    policy=policy,
                    min_tokens=settings.chunk_min_tokens,
                    max_tokens=settings.chunk_max_tokens,
                    overlap_tokens=settings.chunk_overlap_tokens,
                )

                await chunk_repo.create_many(chunks)
                doc.mark_segmented()
                await doc_repo.update(doc)
                step.metrics(
                    chunks_created=len(chunks),
                    nodes_consumed=len(nodes),
                    max_chunk_tokens=max((chunk.token_count for chunk in chunks), default=0),
                    chunk_budget=settings.chunk_max_tokens,
                    chunk_overlap=settings.chunk_overlap_tokens,
                )

            # Enqueue Embed Job
            job_repo = SqlJobRepository(session)
            next_job = Job(id=new_id(), job_type=JobType.EMBED_DOCUMENT, target_id=document_id)
            await job_repo.create(next_job)
            await session.commit()
            return {"chunks_created": len(chunks)}


class EmbedDocumentJobHandler(BaseJobHandler):
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        document_id = job.target_id

        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            chunk_repo = SqlChunkRepository(session)
            node_repo = SqlDocumentNodeRepository(session)
            audit = PipelineAuditService(session=session)

            doc = await doc_repo.get_by_id(document_id)
            if not doc:
                raise ValueError(f"Document {document_id} not found")
            if doc.status == DocumentStatus.FAILED:
                return {"embedded": 0, "skipped": "document_failed"}

            chunks = await chunk_repo.get_by_document(document_id)
            if not chunks:
                return {"embedded": 0}

            # Filter chunks that need embedding
            chunks_to_embed = [c for c in chunks if not c.embedding_ref]

            async with audit.step(
                run_id=job.id,
                entity_type="document",
                entity_id=document_id,
                pipeline="memory_building",
                stage="embed_index",
                context={"chunk_count": len(chunks), "chunks_to_embed": len(chunks_to_embed)},
            ) as step:
                if chunks_to_embed:
                    settings = get_settings()
                    qdrant_endpoint = urlparse(settings.qdrant_url)
                    qdrant_host = qdrant_endpoint.hostname or "localhost"
                    qdrant_port = qdrant_endpoint.port or 6333

                    embedder = EmbeddingGemmaAdapter(
                        dim=settings.embedding_dimensions,
                        required=settings.embeddings_required,
                    )
                    embedder.ensure_indexable()

                    document_nodes = {node.id: node for node in await node_repo.get_by_document(document_id)}

                    texts_to_embed: list[str] = []
                    for c in chunks_to_embed:
                        linked_nodes = [document_nodes[node_id] for node_id in c.node_ids if node_id in document_nodes]
                        heading_path: list[str] = []
                        for node in linked_nodes:
                            candidate_path = node.metadata.get("heading_path", []) if isinstance(node.metadata, dict) else []
                            if candidate_path:
                                heading_path = [str(item) for item in candidate_path]
                                break
                        embedding_text = c.text
                        if heading_path:
                            embedding_text = f"Sección: {' > '.join(heading_path)}\n\n{embedding_text}"
                        texts_to_embed.append(embedding_text)

                    vectors = await embedder.embed_documents(
                        texts_to_embed,
                        titles=[doc.title] * len(texts_to_embed),
                    )

                    # Quantize and index candidates using IngestionOrchestrator
                    from atenex_nova.application.orchestrators.ingestion_orchestrator import (
                        IngestionOrchestrator,
                    )
                    ingestion_orch = IngestionOrchestrator(session)
                    await ingestion_orch.index_nodes(
                        collection_id=str(doc.collection_id),
                        memory_layer="chunk",
                        node_ids=[c.id for c in chunks_to_embed],
                        vectors=vectors,
                        embedding_model=settings.embedding_model,
                        dimension=settings.embedding_dimensions,
                    )

                    qdrant = QdrantAdapter(
                        host=qdrant_host,
                        port=qdrant_port,
                        required=settings.qdrant_required,
                    )
                    sparse_encoder = StableSparseEncoder()
                    collection_name = f"collection_{doc.collection_id}"
                    store_dense_in_qdrant = dense_goes_to_qdrant(settings)
                    await qdrant.init_collection(
                        collection_name,
                        embedder.embedding_dim,
                        dense_enabled=store_dense_in_qdrant,
                    )

                    vector_docs: list[QdrantDocument] = []
                    for chunk, vector in zip(chunks_to_embed, vectors, strict=False):
                        # Stable source IDs make retries idempotent and let SQL/Qdrant
                        # parity be checked without an opaque mapping table.
                        point_id = chunk.id
                        chunk.embedding_ref = point_id
                        sparse_terms = {
                            token.lower().strip(".,:;!?()[]{}")
                            for token in chunk.text.split()
                            if len(token.strip(".,:;!?()[]{}")) > 3
                        }
                        chunk.sparse_ref = " ".join(sorted(sparse_terms)[:32])
                        sparse_indices, sparse_values = sparse_encoder.encode_document(chunk.text)
                        linked_nodes = [document_nodes[node_id] for node_id in chunk.node_ids if node_id in document_nodes]
                        page_numbers = sorted({node.page_number for node in linked_nodes if node.page_number is not None})
                        heading_path = []
                        for node in linked_nodes:
                            candidate_path = node.metadata.get("heading_path", []) if isinstance(node.metadata, dict) else []
                            if candidate_path:
                                heading_path = [str(item) for item in candidate_path]
                                break
                        bbox_candidates = [node.bbox for node in linked_nodes if node.bbox]
                        chunk.metadata = {
                            **chunk.metadata,
                            "document_title": doc.title,
                            "page_numbers": page_numbers,
                            "heading_path": heading_path,
                            "node_types": [node.node_type.value for node in linked_nodes],
                            "source_text": chunk.text,
                            "summary": chunk.summary,
                            "bboxes": bbox_candidates,
                        }
                        await chunk_repo.update(chunk)

                        vector_docs.append(QdrantDocument(
                            id=point_id,
                            vector=vector if store_dense_in_qdrant else None,
                            payload={
                                "document_id": document_id,
                                "collection_id": doc.collection_id,
                                "chunk_id": chunk.id,
                                "title": doc.title,
                                "text": chunk.text,
                                "summary": chunk.summary,
                                "node_ids": chunk.node_ids,
                                "sparse_ref": chunk.sparse_ref,
                                "sparse_encoder": sparse_encoder.encoder_name,
                                "sparse_fallback": sparse_encoder.uses_fallback,
                                "embedding_contract": settings.embedding_contract_fingerprint,
                                "page_numbers": page_numbers,
                                "heading_path": heading_path,
                                "bboxes": bbox_candidates,
                            },
                            sparse_indices=sparse_indices,
                            sparse_values=sparse_values,
                        ))

                    await qdrant.upsert(collection_name, vector_docs)
                    step.metrics(
                        embedded_chunks=len(chunks_to_embed),
                        embedding_dim=embedder.embedding_dim,
                        fallback_embeddings=embedder.uses_fallback,
                        qdrant_available=qdrant.is_available,
                        qdrant_collection=collection_name,
                        qdrant_upserts=len(vector_docs),
                    )
                else:
                    step.metrics(embedded_chunks=0, qdrant_available=True)

            doc.mark_embedded()
            doc.mark_indexed()
            await doc_repo.update(doc)

            # Phase 4 starts once the textual memory is ready.
            from atenex_nova.domain.value_objects.identifiers import JobType as NextJobType
            from atenex_nova.domain.value_objects.identifiers import new_id as next_new_id
            from atenex_nova.infrastructure.db.repositories.sql_job_repo import (
                SqlJobRepository as NextJobRepo,
            )

            next_job = Job(id=next_new_id(), job_type=NextJobType.EXTRACT_PROPOSITIONS, target_id=document_id)
            await NextJobRepo(session).create(next_job)

            await session.commit()
            return {"embedded_and_indexed": len(chunks_to_embed)}


class RebuildCollectionJobHandler(BaseJobHandler):
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        collection_id = job.target_id
        async with self.session_factory() as session:
            collection_repo = SqlCollectionRepository(session)
            doc_repo = SqlDocumentRepository(session)
            chunk_repo = SqlChunkRepository(session)
            node_repo = SqlDocumentNodeRepository(session)
            proposition_repo = SqlPropositionRepository(session)
            summary_repo = SqlSummaryRepository(session)
            relation_repo = SqlRelationRepository(session)
            job_repo = SqlJobRepository(session)
            audit = PipelineAuditService(session=session)

            collection = await collection_repo.get_by_id(collection_id)
            if collection is None:
                raise ValueError(f"Collection {collection_id} not found")

            documents = []
            async for page in doc_repo.iter_by_collection_pages(collection_id):
                documents.extend(page)
            target_ids = [collection_id, *[document.id for document in documents]]
            if await job_repo.has_running_by_targets(
                target_ids,
                exclude_job_id=job.id,
            ):
                raise RuntimeError(
                    f"Collection {collection_id} has running ingestion jobs; "
                    "retry rebuild after they stop"
                )

            # Capture every persistent ID before deleting any SQL rows. A full
            # rebuild removes all four candidate layers and all Qdrant namespaces.
            chunks = await chunk_repo.list_by_collection(collection_id)
            propositions = await proposition_repo.list_by_collection(collection_id)
            summary_ids = await summary_repo.list_ids_for_collection_cleanup(collection_id)
            document_ids = [document.id for document in documents]

            from atenex_nova.workers.jobs.ingestion_job import (
                _build_qdrant_adapter,
                _load_visual_records,
                _remove_visual_asset_dir,
                _visual_cache_path,
            )

            visual_root = get_settings().visual_pages_path
            visual_cache = _visual_cache_path(visual_root, collection_id)
            visual_records = _load_visual_records(visual_cache)
            visual_ids = [
                str(item["id"])
                for item in (visual_records or [])
                if item.get("id") is not None
            ]
            async with audit.step(
                run_id=job.id,
                entity_type="collection",
                entity_id=collection_id,
                pipeline="memory_building",
                stage="rebuild_collection",
                context={"document_count": len(documents)},
            ) as step:
                removed_jobs = await job_repo.delete_pending_by_targets(target_ids, exclude_job_id=job.id)

                from atenex_nova.infrastructure.indexes.candidate_index_factory import (
                    build_candidate_index,
                )

                candidate_idx = build_candidate_index(session)
                await candidate_idx.delete_collection_indexes(collection_id)

                qdrant = _build_qdrant_adapter()
                chunk_namespace = f"collection_{collection_id}"
                await qdrant.delete_collection(chunk_namespace)
                await qdrant.delete_collection(f"{chunk_namespace}_propositions")
                await qdrant.delete_collection(f"{chunk_namespace}_summaries")
                await qdrant.delete_points("pages_visual", visual_ids)
                await qdrant.delete_by_filter(
                    "pages_visual",
                    {"collection_id": collection_id},
                )
                qdrant_cleanup_complete = qdrant.is_available

                # Reset relational state only after external namespaces were
                # addressed. Bulk deletes preserve one transaction for all docs.
                await relation_repo.delete_by_node_ids(
                    [proposition.id for proposition in propositions]
                )
                await summary_repo.delete_by_ids(summary_ids)
                await proposition_repo.delete_by_documents(document_ids)
                await chunk_repo.delete_by_documents(document_ids)
                await node_repo.delete_by_documents(document_ids)

                for document in documents:
                    document.mark_registered()
                    await doc_repo.update(document)
                    await job_repo.create(
                        Job(
                            id=new_id(),
                            job_type=JobType.PARSE_DOCUMENT,
                            target_id=document.id,
                        )
                    )

                if visual_cache.is_symlink() or visual_cache.exists():
                    visual_cache.unlink()
                for document_id in document_ids:
                    _remove_visual_asset_dir(visual_root, document_id)

                step.metrics(
                    documents_requeued=len(documents),
                    parse_jobs_created=len(documents),
                    stale_jobs_removed=removed_jobs,
                    stale_chunk_vectors=len(chunks),
                    stale_proposition_vectors=len(propositions),
                    stale_summary_vectors=len(summary_ids),
                    stale_visual_vectors=len(visual_ids),
                    candidate_namespaces=("chunk", "proposition", "summary", "visual"),
                    qdrant_cleanup_complete=qdrant_cleanup_complete,
                )

            await session.commit()
            return {
                "documents_requeued": len(documents),
                "qdrant_cleanup_complete": qdrant_cleanup_complete,
            }

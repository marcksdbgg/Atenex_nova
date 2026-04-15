"""Job handlers for memory building (chunking, embedding, indexing)."""

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.value_objects.identifiers import JobType, new_id
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.repositories.sql_node_repo import SqlDocumentNodeRepository
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import SqlPropositionRepository
from atenex_nova.infrastructure.db.repositories.sql_relation_repo import SqlRelationRepository
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository
from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter, QdrantDocument
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService
from atenex_nova.workers.runner import BaseJobHandler

logger = logging.getLogger(__name__)


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

            nodes = await node_repo.get_by_document(document_id)

            async with audit.step(
                run_id=job.id,
                entity_type="document",
                entity_id=document_id,
                pipeline="memory_building",
                stage="segment",
                context={"node_count": len(nodes)},
            ) as step:
                chunks: list[Chunk] = []
                current_text = ""
                current_nodes: list[str] = []
                max_chars = 1000

                for node in nodes:
                    text = node.normalized_text or node.raw_text
                    if not text.strip():
                        continue

                    if len(current_text) + len(text) > max_chars and current_nodes:
                        chunks.append(Chunk(
                            id=new_id(),
                            document_id=document_id,
                            text=current_text,
                            token_count=len(current_text) // 4,
                            node_ids=current_nodes,
                        ))
                        current_text = text
                        current_nodes = [node.id]
                    else:
                        current_text += ("\n\n" if current_text else "") + text
                        current_nodes.append(node.id)

                if current_nodes:
                    chunks.append(Chunk(
                        id=new_id(),
                        document_id=document_id,
                        text=current_text,
                        token_count=len(current_text) // 4,
                        node_ids=current_nodes,
                    ))

                await chunk_repo.create_many(chunks)
                doc.mark_segmented()
                await doc_repo.update(doc)
                step.metrics(chunks_created=len(chunks), nodes_consumed=len(nodes))

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
            audit = PipelineAuditService(session=session)

            doc = await doc_repo.get_by_id(document_id)
            if not doc:
                raise ValueError(f"Document {document_id} not found")

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
                    texts = [c.text for c in chunks_to_embed]
                    vectors = await embedder.embed(texts)

                    import uuid

                    qdrant = QdrantAdapter(
                        host=qdrant_host,
                        port=qdrant_port,
                        required=settings.qdrant_required,
                    )
                    collection_name = f"collection_{doc.collection_id}"
                    await qdrant.init_collection(collection_name, embedder.embedding_dim)

                    vector_docs: list[QdrantDocument] = []
                    for chunk, vector in zip(chunks_to_embed, vectors, strict=False):
                        point_id = str(uuid.uuid4())
                        chunk.embedding_ref = point_id
                        await chunk_repo.update(chunk)

                        vector_docs.append(QdrantDocument(
                            id=point_id,
                            vector=vector,
                            payload={
                                "document_id": document_id,
                                "collection_id": doc.collection_id,
                                "chunk_id": chunk.id,
                                "text": chunk.text,
                            },
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
            # In strict mode the document becomes READY only after enrichment jobs complete.
            if not get_settings().strict_mode_enabled:
                doc.mark_ready()
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

            documents = await doc_repo.list_by_collection(collection_id)
            target_ids = [collection_id, *[document.id for document in documents]]
            async with audit.step(
                run_id=job.id,
                entity_type="collection",
                entity_id=collection_id,
                pipeline="memory_building",
                stage="rebuild_collection",
                context={"document_count": len(documents)},
            ) as step:
                removed_jobs = await job_repo.delete_pending_by_targets(target_ids, exclude_job_id=job.id)

                for document in documents:
                    document.mark_registered()
                    await doc_repo.update(document)

                    chunks = await chunk_repo.get_by_document(document.id)
                    propositions = await proposition_repo.list_by_document(document.id)
                    await proposition_repo.delete_by_document(document.id)
                    await summary_repo.delete_by_scope("document", document.id)
                    await summary_repo.delete_by_scope("collection", collection_id)
                    for chunk in chunks:
                        await summary_repo.delete_by_scope("section", chunk.id)
                    await relation_repo.delete_by_source_ids([prop.id for prop in propositions])
                    await chunk_repo.delete_by_document(document.id)
                    await node_repo.delete_by_document(document.id)
                    await job_repo.create(Job(id=new_id(), job_type=JobType.PARSE_DOCUMENT, target_id=document.id))

                visual_cache = get_settings().visual_pages_path / f"{collection_id}.json"
                if visual_cache.exists():
                    visual_cache.unlink()

                step.metrics(
                    documents_requeued=len(documents),
                    parse_jobs_created=len(documents),
                    stale_jobs_removed=removed_jobs,
                )

            await session.commit()
            return {"documents_requeued": len(documents)}

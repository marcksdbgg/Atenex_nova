"""Job handlers for memory building (chunking, embedding, indexing)."""

import logging

from atenex_nova.domain.entities.chunk import Chunk
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.value_objects.identifiers import JobType, new_id
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.repositories.sql_node_repo import SqlDocumentNodeRepository
from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter, QdrantDocument
from atenex_nova.workers.runner import BaseJobHandler

logger = logging.getLogger(__name__)


class SegmentDocumentJobHandler(BaseJobHandler):
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict | None:
        document_id = job.target_id

        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            node_repo = SqlDocumentNodeRepository(session)
            chunk_repo = SqlChunkRepository(session)

            doc = await doc_repo.get_by_id(document_id)
            if not doc:
                raise ValueError(f"Document {document_id} not found")

            nodes = await node_repo.get_by_document(document_id)

            # Simple chunker: group by token limit or just 1:1 if nodes are small
            # For this MVP, we will bundle text nodes up to 500 chars (approx. tokens for simplicity)
            chunks: list[Chunk] = []
            current_text = ""
            current_nodes = []
            max_chars = 1000

            for node in nodes:
                # skip empty
                text = node.normalized_text or node.raw_text
                if not text.strip():
                    continue

                if len(current_text) + len(text) > max_chars and current_nodes:
                    # flush current
                    chunks.append(Chunk(
                        id=new_id(),
                        document_id=document_id,
                        text=current_text,
                        token_count=len(current_text) // 4, # rough estimation
                        node_ids=current_nodes
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
                    node_ids=current_nodes
                ))

            await chunk_repo.create_many(chunks)

            doc.mark_segmented()
            await doc_repo.update(doc)

            # Enqueue Embed Job
            job_repo = SqlJobRepository(session)
            next_job = Job(id=new_id(), job_type=JobType.EMBED_DOCUMENT, target_id=document_id)
            await job_repo.create(next_job)
            await session.commit()
            return {"chunks_created": len(chunks)}


class EmbedDocumentJobHandler(BaseJobHandler):
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict | None:
        document_id = job.target_id

        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            chunk_repo = SqlChunkRepository(session)

            doc = await doc_repo.get_by_id(document_id)
            if not doc:
                raise ValueError(f"Document {document_id} not found")

            chunks = await chunk_repo.get_by_document(document_id)
            if not chunks:
                return {"embedded": 0}

            # Filter chunks that need embedding
            chunks_to_embed = [c for c in chunks if not c.embedding_ref]

            if chunks_to_embed:
                embedder = EmbeddingGemmaAdapter(dim=384)
                texts = [c.text for c in chunks_to_embed]
                vectors = await embedder.embed(texts)

                # We could save the actual vectors somewhere, but in this architecture,
                # we just pass them directly to the index step, or temporarily attach them.
                # However, our protocol design separated embed and index as 2 jobs.
                # To keep it simple, we can combine Embed and Index into a single transactional job
                # or store it in memory/db. Since SqlChunkRepo expects `embedding_ref`, we can
                # generate UUIDs for embedding_refs and theoretically save vectors to disk,
                # but let's index immediately in Qdrant and store the Qdrant point IDs.

                import uuid

                from atenex_nova.shared.config.settings import get_settings
                get_settings()

                qdrant = QdrantAdapter(host="localhost", port=6333) # TODO read from config

                # Init collection just in case
                collection_name = f"collection_{doc.collection_id}"
                await qdrant.init_collection(collection_name, 384) # Stable dimension=384 for EmbeddingGemma

                vector_docs = []
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
                            "text": chunk.text
                        }
                    ))

                await qdrant.upsert(collection_name, vector_docs)

            doc.mark_embedded()
            doc.mark_indexed()
            doc.mark_ready() # End of Phase 3 pipeline
            await doc_repo.update(doc)

            await session.commit()
            return {"embedded_and_indexed": len(chunks_to_embed)}

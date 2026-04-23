
file_path = 'g:/Atenex/Atenex_nova/backend/atenex_nova/workers/jobs/memory_enrichment_job.py'
with open(file_path, encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository\nfrom atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter',
    'from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository\nfrom atenex_nova.infrastructure.embeddings.bm25_encoder import StableSparseEncoder\nfrom atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter'
)

# Handle CRLF if needed
content = content.replace(
    'from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository\r\nfrom atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter',
    'from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository\r\nfrom atenex_nova.infrastructure.embeddings.bm25_encoder import StableSparseEncoder\r\nfrom atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter'
)

content = content.replace(
    'vectors = await embedder.embed([prop.text for prop in propositions])\n                qdrant = None\n                try:\n                    qdrant = QdrantAdapter(',
    'vectors = await embedder.embed([prop.text for prop in propositions])\n                sparse_encoder = StableSparseEncoder()\n                sparse_encodings = [sparse_encoder.encode_document(prop.text) for prop in propositions]\n                qdrant = None\n                try:\n                    qdrant = QdrantAdapter('
)
content = content.replace(
    'vectors = await embedder.embed([prop.text for prop in propositions])\r\n                qdrant = None\r\n                try:\r\n                    qdrant = QdrantAdapter(',
    'vectors = await embedder.embed([prop.text for prop in propositions])\r\n                sparse_encoder = StableSparseEncoder()\r\n                sparse_encodings = [sparse_encoder.encode_document(prop.text) for prop in propositions]\r\n                qdrant = None\r\n                try:\r\n                    qdrant = QdrantAdapter('
)

content = content.replace(
    '"source_chunk_id": prop.source_chunk_id,\n                                },\n                            )\n                            for prop, vector in zip(propositions, vectors, strict=False)',
    '"source_chunk_id": prop.source_chunk_id,\n                                },\n                                sparse_indices=sparse[0],\n                                sparse_values=sparse[1],\n                            )\n                            for prop, vector, sparse in zip(propositions, vectors, sparse_encodings, strict=False)'
)
content = content.replace(
    '"source_chunk_id": prop.source_chunk_id,\r\n                                },\r\n                            )\r\n                            for prop, vector in zip(propositions, vectors, strict=False)',
    '"source_chunk_id": prop.source_chunk_id,\r\n                                },\r\n                                sparse_indices=sparse[0],\r\n                                sparse_values=sparse[1],\r\n                            )\r\n                            for prop, vector, sparse in zip(propositions, vectors, sparse_encodings, strict=False)'
)


content = content.replace(
    'vectors = await embedder.embed([summary.text for summary in summaries])\n                qdrant_unavailable = False\n\n                try:\n                    qdrant = QdrantAdapter(',
    'vectors = await embedder.embed([summary.text for summary in summaries])\n                sparse_encoder = StableSparseEncoder()\n                sparse_encodings = [sparse_encoder.encode_document(summary.text) for summary in summaries]\n                qdrant_unavailable = False\n\n                try:\n                    qdrant = QdrantAdapter('
)
content = content.replace(
    'vectors = await embedder.embed([summary.text for summary in summaries])\r\n                qdrant_unavailable = False\r\n\r\n                try:\r\n                    qdrant = QdrantAdapter(',
    'vectors = await embedder.embed([summary.text for summary in summaries])\r\n                sparse_encoder = StableSparseEncoder()\r\n                sparse_encodings = [sparse_encoder.encode_document(summary.text) for summary in summaries]\r\n                qdrant_unavailable = False\r\n\r\n                try:\r\n                    qdrant = QdrantAdapter('
)

content = content.replace(
    '"text": summary.text,\n                                },\n                            )\n                            for summary, vector in zip(summaries, vectors, strict=False)',
    '"text": summary.text,\n                                },\n                                sparse_indices=sparse[0],\n                                sparse_values=sparse[1],\n                            )\n                            for summary, vector, sparse in zip(summaries, vectors, sparse_encodings, strict=False)'
)
content = content.replace(
    '"text": summary.text,\r\n                                },\r\n                            )\r\n                            for summary, vector in zip(summaries, vectors, strict=False)',
    '"text": summary.text,\r\n                                },\r\n                                sparse_indices=sparse[0],\r\n                                sparse_values=sparse[1],\r\n                            )\r\n                            for summary, vector, sparse in zip(summaries, vectors, sparse_encodings, strict=False)'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

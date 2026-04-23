
file_path = "g:/Atenex/Atenex_nova/backend/atenex_nova/application/orchestrators/retrieval_orchestrator.py"

with open(file_path, encoding="utf-8") as f:
    content = f.read()

# Replace the BM25SparseEncoder import
content = content.replace(
    "from atenex_nova.infrastructure.embeddings.bm25_encoder import BM25SparseEncoder, tokenize",
    "from atenex_nova.infrastructure.embeddings.bm25_encoder import BM25SparseEncoder, StableSparseEncoder, tokenize"
)

# Replace _score_chunks sparse scoring
old_score_chunks = """        sparse_hits = self._score_sparse_candidates(
            query.normalized_text or query.text,
            chunks,
            lambda chunk, score: self._build_chunk_hit(chunk, document_titles, score, "sparse_local"),
            text_getter=lambda chunk: chunk.text,
            limit=40,
        )"""

new_score_chunks = """        sparse_encoder = StableSparseEncoder()
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
        )"""

content = content.replace(old_score_chunks, new_score_chunks)

# Do the same for \r\n just in case
old_score_chunks_crlf = old_score_chunks.replace('\n', '\r\n')
new_score_chunks_crlf = new_score_chunks.replace('\n', '\r\n')
content = content.replace(old_score_chunks_crlf, new_score_chunks_crlf)


# Replace _score_propositions sparse scoring
old_score_props = """        sparse_hits = self._score_sparse_candidates(
            query.normalized_text or query.text,
            propositions,
            lambda prop, score: self._build_proposition_hit(prop, document_titles, score, "sparse_local"),
            text_getter=lambda prop: prop.text,
            limit=40,
        )"""

new_score_props = """        sparse_encoder = StableSparseEncoder()
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
        )"""

content = content.replace(old_score_props, new_score_props)
content = content.replace(old_score_props.replace('\n', '\r\n'), new_score_props.replace('\n', '\r\n'))


# Replace _score_summaries sparse scoring
old_score_sums = """        sparse_hits = self._score_sparse_candidates(
            query.normalized_text or query.text,
            summaries,
            lambda summary, score: self._build_summary_hit(summary, document_titles, score, "sparse_local"),
            text_getter=lambda summary: summary.text,
            limit=30,
        )"""

new_score_sums = """        sparse_encoder = StableSparseEncoder()
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
        )"""

content = content.replace(old_score_sums, new_score_sums)
content = content.replace(old_score_sums.replace('\n', '\r\n'), new_score_sums.replace('\n', '\r\n'))


with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

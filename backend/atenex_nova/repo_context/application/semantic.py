"""Optional semantic generation and hybrid retrieval.

The deterministic SQLite index remains authoritative. This coordinator is only
constructed when explicitly enabled.
"""

from __future__ import annotations

from collections.abc import Sequence

from atenex_nova.repo_context.domain.models import GenerationInfo, SearchHit
from atenex_nova.repo_context.domain.ports import (
    ContextIndex,
    EmbeddingProvider,
    ResultReranker,
    SemanticIndex,
)
from atenex_nova.repo_context.infrastructure.semantic.fusion import (
    reciprocal_rank_fusion,
)


class OptionalSemanticCoordinator:
    def __init__(
        self,
        *,
        embedder: EmbeddingProvider,
        semantic_index: SemanticIndex,
        reranker: ResultReranker | None = None,
        batch_size: int = 32,
    ) -> None:
        self._embedder = embedder
        self._semantic_index = semantic_index
        self._reranker = reranker
        self._batch_size = max(1, batch_size)
        self._ready_generations: set[tuple[str, int]] = set()

    @property
    def identity(self) -> str:
        return self._embedder.identity

    def available(self) -> bool:
        return self._embedder.available() and self._semantic_index.available()

    def ready_for(self, generation: GenerationInfo) -> bool:
        key = (
            generation.snapshot.repository_id,
            generation.id,
        )
        if key in self._ready_generations:
            return True
        persistent_ready = getattr(self._semantic_index, "ready", None)
        return bool(
            callable(persistent_ready)
            and persistent_ready(
                repository_id=generation.snapshot.repository_id,
                generation_id=generation.id,
                embedding_identity=self.identity,
            )
        )

    def build(self, generation: GenerationInfo, index: ContextIndex) -> int:
        if not self.available():
            raise RuntimeError("optional semantic services are unavailable")
        chunks = index.all_chunks()
        inserted = 0
        for offset in range(0, len(chunks), self._batch_size):
            batch = chunks[offset : offset + self._batch_size]
            contextual = [
                (
                    f"Repository: {generation.snapshot.repository_id}\n"
                    f"File: {chunk.file_path}\n"
                    f"Language: {chunk.language}\n"
                    f"Lines: {chunk.line_start}-{chunk.line_end}\n"
                    f"Kind: {chunk.kind}\n\n{chunk.content}"
                )
                for chunk in batch
            ]
            vectors = self._embedder.embed(contextual)
            if len(vectors) != len(batch):
                raise RuntimeError("embedding batch size mismatch")
            payload = [
                (
                    chunk.id,
                    vector,
                    {
                        "path": chunk.file_path,
                        "line_start": chunk.line_start,
                        "line_end": chunk.line_end,
                        "content_hash": generation.snapshot.content_fingerprint,
                        "embedding_identity": self.identity,
                    },
                )
                for chunk, vector in zip(batch, vectors, strict=True)
            ]
            self._semantic_index.upsert(
                repository_id=generation.snapshot.repository_id,
                generation_id=generation.id,
                chunks=payload,
            )
            inserted += len(payload)
        finalize = getattr(self._semantic_index, "finalize", None)
        if callable(finalize):
            finalize(
                repository_id=generation.snapshot.repository_id,
                generation_id=generation.id,
                embedding_identity=self.identity,
                chunk_count=inserted,
                vector_size=(len(vectors[0]) if chunks and vectors else 0),
            )
        self._ready_generations.add(
            (generation.snapshot.repository_id, generation.id)
        )
        return inserted

    def hybrid_search(
        self,
        *,
        query: str,
        generation: GenerationInfo,
        index: ContextIndex,
        lexical_hits: Sequence[SearchHit],
        top_k: int,
    ) -> list[SearchHit]:
        if not self.available() or not self.ready_for(generation):
            raise RuntimeError(
                "optional semantic generation is unavailable or incomplete"
            )
        query_vectors = self._embedder.embed([query])
        if len(query_vectors) != 1:
            raise RuntimeError("query embedding response is invalid")
        semantic = self._semantic_index.search(
            repository_id=generation.snapshot.repository_id,
            generation_id=generation.id,
            vector=query_vectors[0],
            limit=max(top_k * 3, top_k),
        )
        semantic_ids = [chunk_id for chunk_id, _ in semantic]
        chunks = index.chunks_by_ids(semantic_ids)
        hashes = index.chunk_content_hashes(semantic_ids)
        semantic_hits: list[SearchHit] = []
        for chunk_id, score in semantic:
            chunk = chunks.get(chunk_id)
            if chunk is None:
                continue
            semantic_hits.append(
                SearchHit(
                    kind="chunk",
                    path=chunk.file_path,
                    line_start=chunk.line_start,
                    line_end=chunk.line_end,
                    score=float(score),
                    reason="semantic",
                    content_hash=hashes.get(chunk_id, ""),
                    snippet=chunk.content,
                    score_components={"semantic": float(score)},
                )
            )

        lexical_keys = [_hit_key(item) for item in lexical_hits]
        semantic_keys = [_hit_key(item) for item in semantic_hits]
        fused = reciprocal_rank_fusion(
            [lexical_keys, semantic_keys],
            weights=[1.0, 1.0],
        )
        by_key = {
            **{_hit_key(item): item for item in semantic_hits},
            **{_hit_key(item): item for item in lexical_hits},
        }
        semantic_scores = {_hit_key(item): item.score for item in semantic_hits}
        lexical_scores = {_hit_key(item): item.score for item in lexical_hits}
        combined: list[SearchHit] = []
        for key, rrf_score in fused:
            original = by_key[key]
            components = dict(original.score_components)
            components["rrf"] = rrf_score
            if key in semantic_scores:
                components["semantic"] = semantic_scores[key]
            if key in lexical_scores:
                components["lexical"] = lexical_scores[key]
            combined.append(
                SearchHit(
                    kind=original.kind,
                    path=original.path,
                    line_start=original.line_start,
                    line_end=original.line_end,
                    score=rrf_score,
                    reason="hybrid_rrf",
                    content_hash=original.content_hash,
                    snippet=original.snippet,
                    symbol=original.symbol,
                    score_components=components,
                )
            )

        if self._reranker is not None and self._reranker.available() and combined:
            shortlist = combined[: min(len(combined), max(top_k * 2, top_k))]
            scores = self._reranker.rerank(
                query,
                [item.snippet for item in shortlist],
            )
            if len(scores) == len(shortlist):
                reranked: list[SearchHit] = []
                for item, score in zip(shortlist, scores, strict=True):
                    components = dict(item.score_components)
                    components["reranker"] = float(score)
                    reranked.append(
                        SearchHit(
                            kind=item.kind,
                            path=item.path,
                            line_start=item.line_start,
                            line_end=item.line_end,
                            score=float(score),
                            reason="hybrid_reranked",
                            content_hash=item.content_hash,
                            snippet=item.snippet,
                            symbol=item.symbol,
                            score_components=components,
                        )
                    )
                combined = sorted(
                    reranked,
                    key=lambda item: (-item.score, item.path, item.line_start),
                )
        return combined[:top_k]


def _hit_key(hit: SearchHit) -> str:
    symbol_id = hit.symbol.id if hit.symbol else ""
    return (
        f"{hit.kind}\0{hit.path}\0{hit.line_start}\0{hit.line_end}\0{symbol_id}"
    )

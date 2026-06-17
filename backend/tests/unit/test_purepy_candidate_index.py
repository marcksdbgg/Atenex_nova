"""Unit tests for PurePyTurboQuantCandidateIndex."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from scipy.stats import spearmanr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.models.tables import QuantizationProfileModel
from atenex_nova.infrastructure.indexes.purepy_candidate_index import (
    PurePyTurboQuantCandidateIndex,
)
from atenex_nova.infrastructure.indexes.quantized_code_store import QuantizedCodeStore
from atenex_nova.infrastructure.indexes.turboquant_candidate_index import string_to_uint64
from atenex_nova.infrastructure.vector_quantization.turboquant_adapter import TurboQuantAdapter


def _make_profile(profile_id: str = "test-profile") -> QuantizationProfileModel:
    return QuantizationProfileModel(
        id=profile_id,
        algorithm="turboquant_prod",
        embedding_model="embeddinggemma",
        dimension=384,
        bit_width=4,
        rotation_seed=42,
        qjl_seed=1337,
        codebook_version="v1",
    )


@pytest.fixture()
async def session_factory(tmp_path: Path):
    db_path = tmp_path / "purepy-index.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_vectors(
    session: AsyncSession,
    *,
    collection_id: str,
    memory_layer: str,
    vectors: list[list[float]],
    profile: QuantizationProfileModel,
) -> list[str]:
    store = QuantizedCodeStore(session)
    adapter = TurboQuantAdapter()
    await store.save_profile(profile)

    node_ids: list[str] = []
    for vector in vectors:
        node_id = new_id()
        code = adapter.quantize(vector, profile)
        await store.save_vector(
            node_id=node_id,
            uint64_id=string_to_uint64(node_id),
            collection_id=collection_id,
            memory_layer=memory_layer,
            profile_id=profile.id,
            idx_blob=code["idx_blob"],
            qjl_blob=code["qjl_blob"],
            residual_norm=code["residual_norm"],
            vector_norm=code["vector_norm"],
        )
        node_ids.append(node_id)
    await session.commit()
    return node_ids


@pytest.mark.asyncio
async def test_search_recall_vs_exact_inner_product(session_factory) -> None:
    profile = _make_profile()
    collection_id = "col-recall"
    memory_layer = "chunk"
    rng = np.random.default_rng(5)
    n_vectors = 1000
    d = 384

    database = rng.standard_normal((n_vectors, d)).astype(np.float32)
    database /= np.linalg.norm(database, axis=1, keepdims=True)
    query = rng.standard_normal(d).astype(np.float32)
    query /= np.linalg.norm(query)

    async with session_factory() as session:
        node_ids = await _seed_vectors(
            session,
            collection_id=collection_id,
            memory_layer=memory_layer,
            vectors=database.tolist(),
            profile=profile,
        )
        index = PurePyTurboQuantCandidateIndex(session)
        top_results = await index.search(
            collection_id=collection_id,
            memory_layers=[memory_layer],
            query_vector=query.tolist(),
            top_n=10,
        )
        all_results = await index.search(
            collection_id=collection_id,
            memory_layers=[memory_layer],
            query_vector=query.tolist(),
            top_n=n_vectors,
        )

    exact_ips = database @ query
    exact_top10 = set(np.argsort(-exact_ips)[:10].tolist())
    node_to_db_idx = {node_id: idx for idx, node_id in enumerate(node_ids)}

    est_top10 = {node_to_db_idx[r["node_id"]] for r in top_results if r["node_id"] in node_to_db_idx}
    recall_at_10 = len(exact_top10 & est_top10) / 10.0
    assert recall_at_10 >= 0.90

    est_by_node = {r["node_id"]: r["score"] for r in all_results}
    paired_exact = [exact_ips[node_to_db_idx[nid]] for nid in node_ids]
    paired_est = [est_by_node[nid] for nid in node_ids]
    spearman_corr = float(spearmanr(paired_exact, paired_est).correlation)
    assert spearman_corr >= 0.95


@pytest.mark.asyncio
async def test_crud_lifecycle(session_factory) -> None:
    profile = _make_profile("crud-profile")
    collection_id = "col-crud"
    memory_layer = "chunk"
    rng = np.random.default_rng(99)
    vectors = rng.standard_normal((5, 384)).astype(np.float32).tolist()

    async with session_factory() as session:
        node_ids = await _seed_vectors(
            session,
            collection_id=collection_id,
            memory_layer=memory_layer,
            vectors=vectors,
            profile=profile,
        )
        index = PurePyTurboQuantCandidateIndex(session)
        query = rng.standard_normal(384).astype(np.float32).tolist()

        found = await index.search(collection_id, [memory_layer], query, top_n=10)
        assert len(found) == 5
        assert {r["node_id"] for r in found} == set(node_ids)

        await index.remove_vectors(collection_id, node_ids[:2])
        await session.commit()
        remaining = await index.search(collection_id, [memory_layer], query, top_n=10)
        assert len(remaining) == 3
        assert {r["node_id"] for r in remaining} == set(node_ids[2:])

        await index.delete_collection_indexes(collection_id)
        await session.commit()
        empty = await index.search(collection_id, [memory_layer], query, top_n=10)
        assert empty == []


@pytest.mark.asyncio
async def test_add_vectors_invalidates_cache(session_factory) -> None:
    profile = _make_profile("cache-profile")
    collection_id = "col-cache"
    memory_layer = "chunk"
    rng = np.random.default_rng(7)
    vector_a = rng.standard_normal(384).astype(np.float32).tolist()

    async with session_factory() as session:
        store = QuantizedCodeStore(session)
        await store.save_profile(profile)
        query = rng.standard_normal(384).astype(np.float32).tolist()

        node_a = new_id()
        code_a = TurboQuantAdapter().quantize(vector_a, profile)
        await store.save_vector(
            node_id=node_a,
            uint64_id=string_to_uint64(node_a),
            collection_id=collection_id,
            memory_layer=memory_layer,
            profile_id=profile.id,
            idx_blob=code_a["idx_blob"],
            qjl_blob=code_a["qjl_blob"],
            residual_norm=code_a["residual_norm"],
            vector_norm=code_a["vector_norm"],
        )
        await session.commit()

        index = PurePyTurboQuantCandidateIndex(session)
        index._store = store

        with patch.object(
            store,
            "get_vectors_by_layer",
            wraps=store.get_vectors_by_layer,
        ) as mock_get:
            await index.search(collection_id, [memory_layer], query, top_n=5)
            await index.search(collection_id, [memory_layer], query, top_n=5)
            assert mock_get.call_count == 1

            vector_b = rng.standard_normal(384).astype(np.float32).tolist()
            node_b = new_id()
            code_b = TurboQuantAdapter().quantize(vector_b, profile)
            await store.save_vector(
                node_id=node_b,
                uint64_id=string_to_uint64(node_b),
                collection_id=collection_id,
                memory_layer=memory_layer,
                profile_id=profile.id,
                idx_blob=code_b["idx_blob"],
                qjl_blob=code_b["qjl_blob"],
                residual_norm=code_b["residual_norm"],
                vector_norm=code_b["vector_norm"],
            )
            await session.commit()
            await index.add_vectors(collection_id, memory_layer, [node_b], [vector_b])

            found = await index.search(collection_id, [memory_layer], query, top_n=5)
            assert mock_get.call_count == 2
            assert len(found) == 2
            assert {r["node_id"] for r in found} == {node_a, node_b}


@pytest.mark.asyncio
async def test_search_across_multiple_layers(session_factory) -> None:
    profile = _make_profile("multi-layer")
    collection_id = "col-layers"
    rng = np.random.default_rng(11)
    vec_chunk = rng.standard_normal(384).astype(np.float32).tolist()
    vec_prop = rng.standard_normal(384).astype(np.float32).tolist()

    async with session_factory() as session:
        chunk_ids = await _seed_vectors(
            session,
            collection_id=collection_id,
            memory_layer="chunk",
            vectors=[vec_chunk],
            profile=profile,
        )
        prop_ids = await _seed_vectors(
            session,
            collection_id=collection_id,
            memory_layer="proposition",
            vectors=[vec_prop],
            profile=profile,
        )
        index = PurePyTurboQuantCandidateIndex(session)
        query = vec_chunk
        results = await index.search(
            collection_id,
            ["chunk", "proposition"],
            query,
            top_n=10,
        )
        assert len(results) == 2
        layers = {r["memory_layer"] for r in results}
        assert layers == {"chunk", "proposition"}
        node_ids = {r["node_id"] for r in results}
        assert node_ids == {chunk_ids[0], prop_ids[0]}

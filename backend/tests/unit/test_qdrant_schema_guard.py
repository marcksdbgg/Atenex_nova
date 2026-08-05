"""Qdrant schema compatibility and failure semantics."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter
from atenex_nova.shared.exceptions.base import ServiceUnavailableError


def _collection_info(*, dense_size: int | None, sparse: bool = True) -> SimpleNamespace:
    vectors = {} if dense_size is None else {"dense": {"size": dense_size}}
    sparse_vectors = {"sparse": {}} if sparse else {}
    return SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors=vectors, sparse_vectors=sparse_vectors)
        )
    )


def test_schema_guard_accepts_named_dense_and_sparse_vectors() -> None:
    QdrantAdapter._validate_collection_schema(
        _collection_info(dense_size=384),
        vector_size=384,
        dense_enabled=True,
    )


@pytest.mark.parametrize(
    ("info", "message"),
    [
        (_collection_info(dense_size=None), "dense vector 'dense' is missing"),
        (_collection_info(dense_size=768), "expected 384"),
        (_collection_info(dense_size=384, sparse=False), "sparse vector 'sparse' is missing"),
    ],
)
def test_schema_guard_rejects_incompatible_existing_collection(
    info: SimpleNamespace,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        QdrantAdapter._validate_collection_schema(
            info,
            vector_size=384,
            dense_enabled=True,
        )


@pytest.mark.asyncio
async def test_optional_adapter_becomes_unavailable_on_schema_mismatch() -> None:
    adapter = QdrantAdapter(required=False, retry_cooldown_seconds=1)
    adapter.client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=_collection_info(dense_size=None)),
    )

    await adapter.init_collection("collection-test", 384, dense_enabled=True)

    assert adapter.is_available is False


@pytest.mark.asyncio
async def test_required_adapter_raises_on_schema_mismatch() -> None:
    adapter = QdrantAdapter(required=True, retry_cooldown_seconds=1)
    adapter.client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=_collection_info(dense_size=None)),
    )

    with pytest.raises(ServiceUnavailableError):
        await adapter.init_collection("collection-test", 384, dense_enabled=True)

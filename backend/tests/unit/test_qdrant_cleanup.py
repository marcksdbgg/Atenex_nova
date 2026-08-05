"""Safety and idempotence checks for destructive Qdrant operations."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter, QdrantDocument
from atenex_nova.shared.exceptions.base import ServiceUnavailableError


@pytest.mark.asyncio
async def test_delete_points_deduplicates_and_batches_exact_ids() -> None:
    adapter = QdrantAdapter(required=True)
    client = MagicMock()
    client.collection_exists = AsyncMock(return_value=True)
    client.delete = AsyncMock()
    adapter.client = client

    await adapter.delete_points("chunks", ["a", "a", "b", "c"], batch_size=2)

    assert client.delete.await_count == 2
    first_selector = client.delete.await_args_list[0].kwargs["points_selector"]
    second_selector = client.delete.await_args_list[1].kwargs["points_selector"]
    assert first_selector.points == ["a", "b"]
    assert second_selector.points == ["c"]
    assert all(call.kwargs["wait"] is True for call in client.delete.await_args_list)


@pytest.mark.asyncio
async def test_delete_points_and_filter_never_broaden_empty_selection() -> None:
    adapter = QdrantAdapter(required=True)
    client = MagicMock()
    client.collection_exists = AsyncMock(return_value=True)
    client.delete = AsyncMock()
    adapter.client = client

    await adapter.delete_points("chunks", [])
    await adapter.delete_by_filter("chunks", {})

    client.collection_exists.assert_not_awaited()
    client.delete.assert_not_awaited()
    with pytest.raises(ValueError, match="collection_name"):
        await adapter.delete_points("", ["one"])
    with pytest.raises(ValueError, match="filter keys"):
        await adapter.delete_by_filter("chunks", {"": "unsafe"})


@pytest.mark.asyncio
async def test_delete_by_filter_uses_exact_conjunctive_payload_match() -> None:
    adapter = QdrantAdapter(required=True)
    client = MagicMock()
    client.collection_exists = AsyncMock(return_value=True)
    client.delete = AsyncMock()
    adapter.client = client

    await adapter.delete_by_filter(
        "summaries",
        {"scope_type": "document", "scope_id": "doc-1"},
    )

    selector = client.delete.await_args.kwargs["points_selector"]
    assert [(condition.key, condition.match.value) for condition in selector.filter.must] == [
        ("scope_type", "document"),
        ("scope_id", "doc-1"),
    ]
    assert client.delete.await_args.kwargs["wait"] is True


@pytest.mark.asyncio
async def test_cleanup_failure_is_visible_optional_and_raises_when_required() -> None:
    failure = RuntimeError("connection refused")

    optional = QdrantAdapter(required=False, retry_cooldown_seconds=1)
    optional.client = MagicMock()
    optional.client.collection_exists = AsyncMock(side_effect=failure)
    await optional.delete_points("chunks", ["one"])
    assert optional.is_available is False

    required = QdrantAdapter(required=True, retry_cooldown_seconds=1)
    required.client = MagicMock()
    required.client.collection_exists = AsyncMock(side_effect=failure)
    with pytest.raises(ServiceUnavailableError, match="delete points"):
        await required.delete_points("chunks", ["one"])


def _qdrant_document(point_id: str) -> QdrantDocument:
    return QdrantDocument(
        id=point_id,
        vector=[1.0, 0.0],
        payload={"document_id": "doc-1", "text": point_id},
        sparse_indices=[1],
        sparse_values=[1.0],
    )


@pytest.mark.asyncio
async def test_upsert_preserves_order_across_bounded_batches() -> None:
    adapter = QdrantAdapter(required=True)
    client = MagicMock()
    client.upsert = AsyncMock()
    adapter.client = client
    documents = [_qdrant_document(str(index)) for index in range(5)]

    await adapter.upsert("chunks", documents, batch_size=2)

    assert client.upsert.await_count == 3
    batches = [
        [point.id for point in call.kwargs["points"]]
        for call in client.upsert.await_args_list
    ]
    assert batches == [["0", "1"], ["2", "3"], ["4"]]
    assert all(call.kwargs["wait"] is True for call in client.upsert.await_args_list)
    assert adapter.is_available is True


@pytest.mark.asyncio
async def test_required_upsert_failure_does_not_report_partial_batches_as_success() -> None:
    adapter = QdrantAdapter(required=True, retry_cooldown_seconds=1)
    client = MagicMock()
    client.upsert = AsyncMock(side_effect=[None, RuntimeError("disk full")])
    adapter.client = client
    documents = [_qdrant_document(str(index)) for index in range(5)]

    with pytest.raises(ServiceUnavailableError, match="upsert batch 2"):
        await adapter.upsert("chunks", documents, batch_size=2)

    assert client.upsert.await_count == 2
    assert adapter.is_available is False


@pytest.mark.asyncio
async def test_optional_upsert_still_raises_after_a_partial_remote_write() -> None:
    adapter = QdrantAdapter(required=False, retry_cooldown_seconds=1)
    client = MagicMock()
    client.upsert = AsyncMock(side_effect=[None, RuntimeError("connection reset")])
    adapter.client = client

    with pytest.raises(ServiceUnavailableError, match="after 1 completed batch"):
        await adapter.upsert(
            "chunks",
            [_qdrant_document(str(index)) for index in range(3)],
            batch_size=2,
        )

    assert adapter.is_available is False

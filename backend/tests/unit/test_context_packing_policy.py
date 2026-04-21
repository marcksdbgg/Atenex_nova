"""Unit tests for evidence context packing."""

from __future__ import annotations

from atenex_nova.application.policies.context_packing_policy import ContextPackingPolicy
from atenex_nova.domain.entities.evidence_item import EvidenceItem
from atenex_nova.domain.value_objects.identifiers import new_id


def _make_item(index: int, text: str, source_type: str = "chunk", document_id: str = "document-1") -> EvidenceItem:
    return EvidenceItem(
        id=new_id(),
        query_id="query-1",
        source_type=source_type,
        source_id=f"source-{index}",
        score=1.0 - (index * 0.01),
        rank=index + 1,
        document_id=document_id,
        title=f"Item {index}",
        snippet=text,
    )


def test_context_packing_uses_token_budget_instead_of_fixed_cap() -> None:
    policy = ContextPackingPolicy()
    items = [
        _make_item(
            index,
            f"Evidence item {index} supports the response with unique marker {index}.",
            document_id=f"document-{index % 4}",
        )
        for index in range(15)
    ]

    pack = policy.build("query-1", "factual_local", items, token_budget=500)

    assert 1 <= len(pack.items) <= 8
    assert pack.selected_count == len(pack.items)
    assert pack.estimated_tokens > 0
    assert 0 < pack.budget_utilization <= 1
    assert len({item.document_id for item in pack.items}) >= 2


def test_context_packing_trims_when_budget_is_exhausted() -> None:
    policy = ContextPackingPolicy()
    items = [
        _make_item(index, " ".join([f"long-{index}"] * 120))
        for index in range(4)
    ]

    pack = policy.build("query-1", "factual_local", items, token_budget=220)

    assert 1 <= len(pack.items) < len(items)
    assert pack.estimated_tokens >= len(pack.items)
    assert pack.budget_utilization <= 1


def test_context_packing_limits_document_saturation_for_multi_hop() -> None:
    policy = ContextPackingPolicy()
    items = [
        _make_item(index, f"Multi hop evidence marker {index}", source_type="proposition", document_id="document-a")
        for index in range(6)
    ] + [
        _make_item(index + 10, f"Supporting evidence marker {index}", source_type="chunk", document_id="document-b")
        for index in range(4)
    ]

    pack = policy.build("query-1", "multi_hop", items, token_budget=600)

    per_document = {}
    for item in pack.items:
        per_document[item.document_id] = per_document.get(item.document_id, 0) + 1

    assert per_document["document-a"] <= 2
    assert per_document["document-b"] <= 2

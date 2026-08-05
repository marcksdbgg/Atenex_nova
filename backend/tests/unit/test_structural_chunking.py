"""Focused tests for hard-bounded structural chunk construction."""

from itertools import pairwise
from typing import cast

from atenex_nova.application.policies.token_budget_policy import TokenBudgetPolicy
from atenex_nova.domain.entities.document_node import DocumentNode
from atenex_nova.domain.value_objects.identifiers import NodeType
from atenex_nova.workers.jobs.mem_builder_job import build_document_chunks


def test_oversized_node_becomes_bounded_chunks_with_source_spans_and_overlap() -> None:
    source = " ".join(
        f"Paragraph sentence {index} carries source evidence in its original order."
        for index in range(30)
    )
    node = DocumentNode(
        id="node-1",
        document_id="doc-1",
        node_type=NodeType.PARAGRAPH,
        raw_text=source,
        normalized_text=source,
        page_number=7,
        order_index=0,
        metadata={"heading_path": ["Chapter", "Section"]},
    )
    policy = TokenBudgetPolicy()

    chunks = build_document_chunks(
        "doc-1",
        [node],
        policy=policy,
        min_tokens=20,
        max_tokens=50,
        overlap_tokens=8,
    )

    assert len(chunks) > 1
    assert all(chunk.token_count <= 50 for chunk in chunks)
    spans = [
        cast(list[dict[str, object]], chunk.metadata["source_spans"])[0]
        for chunk in chunks
    ]
    assert [span["segment_index"] for span in spans] == list(range(len(spans)))
    assert spans[0]["char_start"] == 0
    assert spans[-1]["char_end"] == len(source)

    for chunk, span in zip(chunks, spans, strict=True):
        start = cast(int, span["char_start"])
        end = cast(int, span["char_end"])
        assert chunk.text == source[start:end]
        assert chunk.node_ids == [node.id]
        assert chunk.metadata["page_numbers"] == [7]
        assert chunk.metadata["heading_path"] == ["Chapter", "Section"]
        assert span["source_field"] == "normalized_text"

    for previous, current in pairwise(spans):
        assert cast(int, previous["char_start"]) < cast(int, current["char_start"])
        assert cast(int, current["char_start"]) < cast(int, previous["char_end"])


def test_multiple_nodes_preserve_source_order_without_exceeding_budget() -> None:
    nodes = [
        DocumentNode(
            id=f"node-{index}",
            document_id="doc-1",
            node_type=NodeType.PARAGRAPH,
            raw_text=text,
            normalized_text=text,
            order_index=index,
        )
        for index, text in enumerate(
            [
                "First source paragraph remains first.",
                "Second source paragraph remains second.",
                "Third source paragraph remains third.",
            ]
        )
    ]

    chunks = build_document_chunks(
        "doc-1",
        nodes,
        policy=TokenBudgetPolicy(),
        min_tokens=20,
        max_tokens=22,
        overlap_tokens=4,
    )

    assert all(chunk.token_count <= 22 for chunk in chunks)
    flattened_node_ids = [node_id for chunk in chunks for node_id in chunk.node_ids]
    assert flattened_node_ids == [node.id for node in nodes]
    assert "\n\n".join(chunk.text for chunk in chunks) == "\n\n".join(
        node.normalized_text for node in nodes
    )


def test_metadata_envelope_is_not_indexed_and_caption_provenance_is_propagated() -> None:
    metadata_node = DocumentNode(
        id="metadata-1",
        document_id="doc-1",
        node_type=NodeType.PARAGRAPH,
        raw_text="Title: Debate\nKind: captions",
        normalized_text="Title: Debate\nKind: captions",
        order_index=0,
        metadata={"content_role": "metadata", "source_char_start": 0, "source_char_end": 30},
    )
    caption_node = DocumentNode(
        id="caption-1",
        document_id="doc-1",
        node_type=NodeType.CAPTION,
        raw_text="La tesis sustantiva pertenece al corpus.",
        normalized_text="La tesis sustantiva pertenece al corpus.",
        order_index=1,
        metadata={
            "content_role": "transcript",
            "source_char_start": 64,
            "source_char_end": 105,
            "timestamp_start": "00:00:01,000",
            "timestamp_end": "00:00:05,000",
        },
    )

    chunks = build_document_chunks(
        "doc-1",
        [metadata_node, caption_node],
        policy=TokenBudgetPolicy(),
        min_tokens=20,
        max_tokens=50,
        overlap_tokens=4,
    )

    assert len(chunks) == 1
    assert chunks[0].text == caption_node.normalized_text
    assert chunks[0].node_ids == [caption_node.id]
    span = cast(list[dict[str, object]], chunks[0].metadata["source_spans"])[0]
    assert span["source_char_start"] == 64
    assert span["source_char_end"] == 105
    assert span["content_role"] == "transcript"
    assert span["timestamp_start"] == "00:00:01,000"
    assert span["timestamp_end"] == "00:00:05,000"

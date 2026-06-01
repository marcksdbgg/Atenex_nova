"""Unit tests for the Docling parser adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from atenex_nova.infrastructure.parsing.docling_adapter import DoclingParserAdapter


@pytest.mark.asyncio
async def test_plain_text_files_parse_without_docling(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text(
        "First paragraph.\n\nSecond paragraph with more text.",
        encoding="utf-8",
    )

    adapter = DoclingParserAdapter()
    nodes = await adapter.parse(str(source), "document-1")

    assert len(nodes) == 2
    assert [node.raw_text for node in nodes] == ["First paragraph.", "Second paragraph with more text."]
    assert all(node.document_id == "document-1" for node in nodes)
    assert all(node.node_type.value == "paragraph" for node in nodes)
    assert all(node.metadata.get("source_format") == "text/plain" for node in nodes)


@pytest.mark.asyncio
async def test_docling_unavailable_raises_error_for_complex_documents(tmp_path: Path) -> None:
    source = tmp_path / "document.pdf"
    source.write_bytes(b"%PDF-1.4...")

    adapter = DoclingParserAdapter()
    # Mocking docling as unavailable
    adapter.converter = None
    adapter.chunker = None

    with pytest.raises(RuntimeError, match="Docling is not available but required for complex documents"):
        await adapter.parse(str(source), "document-1")

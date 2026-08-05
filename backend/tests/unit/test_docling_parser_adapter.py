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
    assert [(node.metadata["source_char_start"], node.metadata["source_char_end"]) for node in nodes] == [
        (0, 16),
        (18, 50),
    ]
    assert adapter._docling_initialized is False


@pytest.mark.asyncio
async def test_caption_export_preserves_envelope_timestamps_and_source_offsets(tmp_path: Path) -> None:
    source = tmp_path / "captions.txt"
    source_text = (
        "Title: Libertad y eutanasia\r\n"
        "Kind: captions\r\n"
        "Language: es\r\n"
        "-----\r\n"
        "1\r\n"
        "00:00:01,000 --> 00:00:05,000\r\n"
        "La libertad no puede anular la vida.\r\n"
        "\r\n"
        "2\r\n"
        "00:00:06,000 --> 00:00:10,000\r\n"
        "La enfermedad terminal exige otro matiz.\r\n"
    )
    source.write_text(source_text, encoding="utf-8", newline="")

    nodes = await DoclingParserAdapter().parse(str(source), "document-1")

    assert [node.metadata["content_role"] for node in nodes] == [
        "metadata",
        "transcript",
        "transcript",
    ]
    assert [node.node_type.value for node in nodes] == ["paragraph", "caption", "caption"]
    assert nodes[1].metadata["timestamp_start"] == "00:00:01,000"
    assert nodes[1].metadata["timestamp_end"] == "00:00:05,000"
    assert nodes[2].metadata["heading_path"] == ["Libertad y eutanasia"]
    assert nodes[1].raw_text == "La libertad no puede anular la vida."
    assert nodes[2].raw_text == "La enfermedad terminal exige otro matiz."
    for node in nodes:
        start = int(node.metadata["source_char_start"])
        end = int(node.metadata["source_char_end"])
        assert source_text[start:end] == node.raw_text


@pytest.mark.asyncio
async def test_line_based_caption_export_is_split_into_bounded_semantic_units(tmp_path: Path) -> None:
    source = tmp_path / "long-captions.txt"
    source.write_text(
        "\n".join(f"línea breve número {index}" for index in range(1, 22)),
        encoding="utf-8",
    )

    nodes = await DoclingParserAdapter().parse(str(source), "document-1")

    assert len(nodes) == 3
    assert all(node.node_type.value == "caption" for node in nodes)
    assert all(node.metadata["content_role"] == "transcript" for node in nodes)
    assert all(node.raw_text.count("\n") <= 7 for node in nodes)
    assert [node.order_index for node in nodes] == [0, 1, 2]


@pytest.mark.asyncio
async def test_markdown_headings_propagate_structural_path_without_transcript_heuristic(
    tmp_path: Path,
) -> None:
    source = tmp_path / "essay.md"
    source.write_text(
        "# Tesis\n\nPrimer argumento.\n\n## Excepción\n\nCaso límite.\n",
        encoding="utf-8",
    )

    nodes = await DoclingParserAdapter().parse(str(source), "document-1")

    assert [node.node_type.value for node in nodes] == [
        "heading",
        "paragraph",
        "heading",
        "paragraph",
    ]
    assert nodes[1].metadata["heading_path"] == ["Tesis"]
    assert nodes[3].metadata["heading_path"] == ["Tesis", "Excepción"]
    assert all(node.metadata["source_format"] == "text/markdown" for node in nodes)


@pytest.mark.asyncio
async def test_docling_unavailable_raises_error_for_complex_documents(tmp_path: Path) -> None:
    source = tmp_path / "document.pdf"
    source.write_bytes(b"%PDF-1.4...")

    adapter = DoclingParserAdapter()
    # Mocking docling as unavailable
    adapter._docling_initialized = True
    adapter.converter = None
    adapter.chunker = None

    with pytest.raises(RuntimeError, match="Docling is not available but required for complex documents"):
        await adapter.parse(str(source), "document-1")

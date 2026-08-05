"""Docling parser adapter."""

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atenex_nova.domain.entities.document_node import DocumentNode
from atenex_nova.domain.value_objects.identifiers import NodeType, new_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _SourceLine:
    """One source line with offsets into the unmodified file text."""

    text: str
    start: int
    end: int


_METADATA_LINE = re.compile(
    r"^\s*(?P<key>title|video\s+id|channel|kind|language|subtitle\s+language|"
    r"generated\s+at|source|url)\s*:\s*(?P<value>.*)\s*$",
    re.IGNORECASE,
)
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}(?P<marks>#{1,6})\s+(?P<title>.+?)\s*#*\s*$")
_SRT_TIMESTAMP = re.compile(
    r"^\s*(?P<start>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3})(?:\s+.*)?$"
)
_INLINE_TIMESTAMP = re.compile(
    r"^\s*(?:\[(?P<bracket>\d{1,2}:\d{2}(?::\d{2})?)\]|"
    r"(?P<plain>\d{1,2}:\d{2}(?::\d{2})?))\s*[-\u2013\u2014:]?\s*(?P<text>\S.*)$"
)
_DIVIDER_LINE = re.compile(r"^\s*[-=_*]{3,}\s*$")


def _source_lines(raw_text: str) -> list[_SourceLine]:
    """Split source text without losing CRLF-aware character offsets."""
    lines: list[_SourceLine] = []
    for match in re.finditer(r".*?(?:\r\n|\n|\r|$)", raw_text):
        value = match.group(0)
        if not value:
            continue
        text = value.rstrip("\r\n")
        lines.append(_SourceLine(text=text, start=match.start(), end=match.start() + len(text)))
    return lines


def _trimmed_source_span(raw_text: str, start: int, end: int) -> tuple[str, int, int]:
    """Return an exact non-whitespace source slice and its original offsets."""
    while start < end and raw_text[start].isspace():
        start += 1
    while end > start and raw_text[end - 1].isspace():
        end -= 1
    return raw_text[start:end], start, end


class DoclingParserAdapter:
    """Adapter for Docling document parser using HierarchicalChunker."""

    def __init__(self) -> None:
        self.converter: Any | None = None
        self.chunker: Any | None = None
        self._docling_initialized = False
        self._docling_error: Exception | None = None

    def _ensure_docling(self) -> bool:
        """Initialize the heavy parser only when a complex document needs it."""
        if self._docling_initialized:
            return self.converter is not None and self.chunker is not None

        self._docling_initialized = True
        try:
            from docling.document_converter import DocumentConverter
            from docling_core.transforms.chunker.hierarchical_chunker import HierarchicalChunker

            self.converter = DocumentConverter()
            self.chunker = HierarchicalChunker()
            logger.info("DoclingParserAdapter initialized")
        except (ImportError, RuntimeError) as exc:
            self._docling_error = exc
            logger.warning("Docling is unavailable: %s", exc)
            self.converter = None
            self.chunker = None
        return self.converter is not None and self.chunker is not None

    @staticmethod
    def _is_plain_text(file_path: str) -> bool:
        return Path(file_path).suffix.lower() in {".txt", ".text", ".md", ".markdown", ".rst"}

    @staticmethod
    def _plain_source_format(file_path: str) -> str:
        suffix = Path(file_path).suffix.lower()
        if suffix in {".md", ".markdown"}:
            return "text/markdown"
        if suffix == ".rst":
            return "text/x-rst"
        return "text/plain"

    @staticmethod
    def _looks_like_transcript(lines: list[_SourceLine]) -> bool:
        nonempty = [line.text.strip() for line in lines if line.text.strip()]
        if not nonempty:
            return False
        if any(
            match is not None
            and match.group("key").lower().replace(" ", "") == "kind"
            and match.group("value").strip().lower() in {"caption", "captions", "subtitle", "subtitles"}
            for value in nonempty
            if (match := _METADATA_LINE.match(value))
        ):
            return True
        if any(_SRT_TIMESTAMP.match(value) or _INLINE_TIMESTAMP.match(value) for value in nonempty):
            return True

        # Caption exports often contain one short utterance per line and no blank
        # separators. Wrapped prose tends to have fewer and longer lines.
        short_lines = [value for value in nonempty if len(value) <= 180]
        return len(nonempty) >= 8 and len(short_lines) / len(nonempty) >= 0.8

    @staticmethod
    def _node_metadata(
        *,
        file_path: str,
        source_format: str,
        start: int,
        end: int,
        heading_path: list[str],
        content_role: str,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {
            "source_format": source_format,
            "source_path": file_path,
            "source_char_start": start,
            "source_char_end": end,
            "heading_path": list(heading_path),
            "content_role": content_role,
        }
        if extra:
            metadata.update(extra)
        return metadata

    def _parse_structured_plain_text(
        self,
        *,
        raw_text: str,
        lines: list[_SourceLine],
        file_path: str,
        document_id: str,
        source_format: str,
    ) -> list[DocumentNode]:
        nodes: list[DocumentNode] = []
        heading_stack: list[str] = []
        block: list[_SourceLine] = []

        def add_block() -> None:
            if not block:
                return
            text, start, end = _trimmed_source_span(raw_text, block[0].start, block[-1].end)
            block.clear()
            if not text:
                return

            heading_match = _MARKDOWN_HEADING.match(text) if "\n" not in text and "\r" not in text else None
            node_type = NodeType.PARAGRAPH
            role = "body"
            node_heading_path = list(heading_stack)
            if heading_match:
                level = len(heading_match.group("marks"))
                title = heading_match.group("title").strip()
                del heading_stack[level - 1 :]
                heading_stack.append(title)
                node_heading_path = list(heading_stack)
                node_type = NodeType.HEADING
                role = "heading"

            nodes.append(
                DocumentNode(
                    id=new_id(),
                    document_id=document_id,
                    node_type=node_type,
                    raw_text=text,
                    normalized_text="",
                    page_number=1,
                    order_index=len(nodes),
                    metadata=self._node_metadata(
                        file_path=file_path,
                        source_format=source_format,
                        start=start,
                        end=end,
                        heading_path=node_heading_path,
                        content_role=role,
                    ),
                )
            )

        for line in lines:
            if not line.text.strip():
                add_block()
                continue
            if _MARKDOWN_HEADING.match(line.text):
                add_block()
                block.append(line)
                add_block()
                continue
            block.append(line)
        add_block()
        return nodes

    def _parse_transcript_text(
        self,
        *,
        raw_text: str,
        lines: list[_SourceLine],
        file_path: str,
        document_id: str,
        source_format: str,
    ) -> list[DocumentNode]:
        """Parse common caption/SRT exports into bounded, source-addressable units."""
        nodes: list[DocumentNode] = []
        title = ""
        content_start = 0
        metadata_lines: list[_SourceLine] = []

        # Capture only the leading export envelope. A later ``Title:`` inside the
        # transcript is content and must not be reclassified.
        for index, line in enumerate(lines):
            stripped = line.text.strip()
            match = _METADATA_LINE.match(stripped)
            if match:
                metadata_lines.append(line)
                content_start = index + 1
                if match.group("key").lower().replace(" ", "") == "title":
                    title = match.group("value").strip()
                continue
            if (not stripped or _DIVIDER_LINE.match(stripped)) and metadata_lines:
                metadata_lines.append(line)
                content_start = index + 1
                continue
            break

        if metadata_lines:
            text, start, end = _trimmed_source_span(
                raw_text,
                metadata_lines[0].start,
                metadata_lines[-1].end,
            )
            if text:
                nodes.append(
                    DocumentNode(
                        id=new_id(),
                        document_id=document_id,
                        node_type=NodeType.PARAGRAPH,
                        raw_text=text,
                        normalized_text="",
                        page_number=1,
                        order_index=len(nodes),
                        metadata=self._node_metadata(
                            file_path=file_path,
                            source_format=source_format,
                            start=start,
                            end=end,
                            heading_path=[title] if title else [],
                            content_role="metadata",
                            extra={"metadata_envelope": True},
                        ),
                    )
                )

        group: list[_SourceLine] = []
        group_start_override: int | None = None
        group_timestamp_start: str | None = None
        group_timestamp_end: str | None = None
        pending_timestamp_start: str | None = None
        pending_timestamp_end: str | None = None

        def flush_group() -> None:
            nonlocal group_start_override, group_timestamp_start, group_timestamp_end
            if not group:
                return
            start = group_start_override if group_start_override is not None else group[0].start
            text, start, end = _trimmed_source_span(raw_text, start, group[-1].end)
            group.clear()
            group_start_override = None
            if not text:
                group_timestamp_start = None
                group_timestamp_end = None
                return
            timestamp_data: dict[str, object] = {"transcript_unit": "caption_group"}
            if group_timestamp_start:
                timestamp_data["timestamp_start"] = group_timestamp_start
            if group_timestamp_end:
                timestamp_data["timestamp_end"] = group_timestamp_end
            nodes.append(
                DocumentNode(
                    id=new_id(),
                    document_id=document_id,
                    node_type=NodeType.CAPTION,
                    raw_text=text,
                    normalized_text="",
                    page_number=1,
                    order_index=len(nodes),
                    metadata=self._node_metadata(
                        file_path=file_path,
                        source_format=source_format,
                        start=start,
                        end=end,
                        heading_path=[title] if title else [],
                        content_role="transcript",
                        extra=timestamp_data,
                    ),
                )
            )
            group_timestamp_start = None
            group_timestamp_end = None

        for index in range(content_start, len(lines)):
            line = lines[index]
            stripped = line.text.strip()
            if not stripped:
                flush_group()
                pending_timestamp_start = None
                pending_timestamp_end = None
                continue
            if _DIVIDER_LINE.match(stripped) or stripped.upper() == "WEBVTT":
                flush_group()
                continue
            if (
                stripped.isdigit()
                and index + 1 < len(lines)
                and _SRT_TIMESTAMP.match(lines[index + 1].text.strip())
            ):
                flush_group()
                continue

            timestamp = _SRT_TIMESTAMP.match(stripped)
            if timestamp:
                flush_group()
                pending_timestamp_start = timestamp.group("start")
                pending_timestamp_end = timestamp.group("end")
                continue

            inline = _INLINE_TIMESTAMP.match(line.text)
            if inline:
                flush_group()
                group_timestamp_start = inline.group("bracket") or inline.group("plain")
                group_timestamp_end = None
                group_start_override = line.start + inline.start("text")
                group.append(line)
            else:
                if not group:
                    group_timestamp_start = pending_timestamp_start
                    group_timestamp_end = pending_timestamp_end
                    pending_timestamp_start = None
                    pending_timestamp_end = None
                group.append(line)

            char_count = group[-1].end - (group_start_override or group[0].start)
            sentence_boundary = stripped.endswith((".", "?", "!", "…"))
            if len(group) >= 8 or char_count >= 1_200 or (
                len(group) >= 2 and char_count >= 400 and sentence_boundary
            ):
                flush_group()

        flush_group()
        return nodes

    async def _parse_plain_text(self, file_path: str, document_id: str) -> list[DocumentNode]:
        raw_bytes = await asyncio.to_thread(Path(file_path).read_bytes)
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        if not raw_text.strip():
            return []

        lines = _source_lines(raw_text)
        source_format = self._plain_source_format(file_path)
        if source_format == "text/plain" and self._looks_like_transcript(lines):
            nodes = self._parse_transcript_text(
                raw_text=raw_text,
                lines=lines,
                file_path=file_path,
                document_id=document_id,
                source_format=source_format,
            )
        else:
            nodes = self._parse_structured_plain_text(
                raw_text=raw_text,
                lines=lines,
                file_path=file_path,
                document_id=document_id,
                source_format=source_format,
            )

        logger.info("Extracted %d plain-text nodes for document %s", len(nodes), document_id)
        return nodes

    async def parse(self, file_path: str, document_id: str) -> list[DocumentNode]:
        if self._is_plain_text(file_path):
            logger.info("Parsing plain text document %s at %s", document_id, file_path)
            return await self._parse_plain_text(file_path, document_id)

        if not self._ensure_docling():
            logger.error("Cannot parse: Docling is not available")
            raise RuntimeError("Docling is not available but required for complex documents")

        converter = self.converter
        chunker = self.chunker
        if converter is None or chunker is None:
            raise RuntimeError("Docling initialization completed without parser components")

        logger.info(f"Parsing document {document_id} at {file_path} with Docling...")

        # Run synchronous Docling conversion in a worker thread
        try:
            result = await asyncio.to_thread(converter.convert, file_path)
        except Exception:
            if self._is_plain_text(file_path):
                logger.warning("Docling failed for %s, falling back to plain-text parsing", file_path)
                return await self._parse_plain_text(file_path, document_id)
            raise
        doc = result.document

        logger.info(f"Document {document_id} parsed. Chunking...")
        # Use HierarchicalChunker to get semantic chunks
        chunks = list(chunker.chunk(doc))

        nodes: list[DocumentNode] = []
        for idx, chunk in enumerate(chunks):
            # chunk is a Chunk object from docling_core
            node_type = NodeType.PARAGRAPH
            raw_text = chunk.text

            headings = []
            page_number = None
            bbox = None
            docling_label = None

            if hasattr(chunk, "meta"):
                if hasattr(chunk.meta, "headings"):
                    headings = [str(item).strip() for item in (chunk.meta.headings or []) if str(item).strip()]

                # Check for doc_items to infer strict type and get provenance
                provenance_items = getattr(chunk.meta, "doc_items", [])
                if provenance_items:
                    first_item = provenance_items[0]
                    docling_label = getattr(first_item, "label", None)
                    label_value = getattr(docling_label, "value", None)
                    if label_value is not None:
                        docling_label = label_value

                    prov = getattr(first_item, "prov", [])
                    if prov:
                        first_prov = prov[0]
                        page_number = getattr(first_prov, "page_no", None)
                        bbox_obj = getattr(first_prov, "bbox", None)
                        if bbox_obj:
                            bbox = {
                                "l": getattr(bbox_obj, "l", 0.0),
                                "t": getattr(bbox_obj, "t", 0.0),
                                "r": getattr(bbox_obj, "r", 0.0),
                                "b": getattr(bbox_obj, "b", 0.0),
                            }

                # Fallbacks for page_number if prov is missing
                if page_number is None:
                    for candidate_attr in ("page_number", "page_no"):
                        candidate = getattr(chunk.meta, candidate_attr, None)
                        if isinstance(candidate, int):
                            page_number = candidate
                            break

                # Fallback for bbox if prov is missing
                if bbox is None:
                    bbox_candidate = getattr(chunk.meta, "bbox", None)
                    if bbox_candidate is not None:
                        bbox = {
                            "l": getattr(bbox_candidate, "l", 0.0),
                            "t": getattr(bbox_candidate, "t", 0.0),
                            "r": getattr(bbox_candidate, "r", 0.0),
                            "b": getattr(bbox_candidate, "b", 0.0),
                        }

            # Mapping Docling labels to our NodeTypes
            if docling_label:
                label_lower = str(docling_label).lower()
                if label_lower in ("table",):
                    node_type = NodeType.TABLE
                elif label_lower in ("list_item", "list"):
                    node_type = NodeType.LIST_ITEM
                elif label_lower in ("caption",):
                    node_type = NodeType.CAPTION
                elif label_lower in ("footnote",):
                    node_type = NodeType.FOOTNOTE
                elif label_lower in ("picture", "image", "figure"):
                    node_type = NodeType.IMAGE
                elif label_lower in ("formula", "equation"):
                    node_type = NodeType.FORMULA
                elif label_lower in ("section_header", "page_header", "title"):
                    node_type = NodeType.HEADING
            else:
                # Heuristics if label is missing
                if "|" in raw_text and "\n|" in raw_text:
                    node_type = NodeType.TABLE
                elif raw_text.startswith("#"):
                    node_type = NodeType.HEADING

            if node_type == NodeType.IMAGE and not raw_text.strip():
                if headings:
                    raw_text = f"[Imagen en sección: {' > '.join(headings)}]"
                else:
                    raw_text = "[Imagen]"

            node = DocumentNode(
                id=new_id(),
                document_id=document_id,
                node_type=node_type,
                raw_text=raw_text,
                normalized_text="",
                page_number=page_number,
                order_index=idx,
                bbox=bbox,
                metadata={
                    "headings": headings,
                    "heading_path": headings,
                    "source_format": Path(file_path).suffix.lower().lstrip(".") or "docling",
                },
            )
            nodes.append(node)

        logger.info(f"Extracted {len(nodes)} semantic nodes for document {document_id}")
        return nodes

"""Docling parser adapter."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from atenex_nova.domain.entities.document_node import DocumentNode
from atenex_nova.domain.value_objects.identifiers import NodeType, new_id

logger = logging.getLogger(__name__)


class DoclingParserAdapter:
    """Adapter for Docling document parser using HierarchicalChunker."""

    def __init__(self) -> None:
        self.converter: Any | None = None
        self.chunker: Any | None = None
        try:
            from docling.document_converter import DocumentConverter
            from docling_core.transforms.chunker.hierarchical_chunker import HierarchicalChunker

            self.converter = DocumentConverter()
            self.chunker = HierarchicalChunker()
            logger.info("DoclingParserAdapter initialized")
        except ImportError:
            logger.error("Docling not installed.")
            self.converter = None
            self.chunker = None

    @staticmethod
    def _is_plain_text(file_path: str) -> bool:
        return Path(file_path).suffix.lower() in {".txt", ".text", ".md", ".markdown", ".rst"}

    async def _parse_plain_text(self, file_path: str, document_id: str) -> list[DocumentNode]:
        raw_text = await asyncio.to_thread(Path(file_path).read_text, encoding="utf-8", errors="replace")
        normalized_text = raw_text.replace("\r\n", "\n").strip()
        if not normalized_text:
            return []

        blocks = [block.strip() for block in normalized_text.split("\n\n") if block.strip()]
        if not blocks:
            blocks = [normalized_text]

        nodes: list[DocumentNode] = []
        for idx, block in enumerate(blocks):
            nodes.append(
                DocumentNode(
                    id=new_id(),
                    document_id=document_id,
                    node_type=NodeType.PARAGRAPH,
                    raw_text=block,
                    normalized_text="",
                    page_number=1,
                    order_index=idx,
                    metadata={
                        "source_format": "text/plain",
                        "source_path": file_path,
                        "heading_path": [],
                    },
                )
            )

        logger.info("Extracted %d plain-text nodes for document %s", len(nodes), document_id)
        return nodes

    async def parse(self, file_path: str, document_id: str) -> list[DocumentNode]:
        if self._is_plain_text(file_path):
            logger.info("Parsing plain text document %s at %s", document_id, file_path)
            return await self._parse_plain_text(file_path, document_id)

        if not self.converter or not self.chunker:
            logger.error("Cannot parse: Docling is not available")
            raise RuntimeError("Docling is not available but required for complex documents")

        logger.info(f"Parsing document {document_id} at {file_path} with Docling...")

        # Run synchronous Docling conversion in a worker thread
        try:
            result = await asyncio.to_thread(self.converter.convert, file_path)
        except Exception:
            if self._is_plain_text(file_path):
                logger.warning("Docling failed for %s, falling back to plain-text parsing", file_path)
                return await self._parse_plain_text(file_path, document_id)
            raise
        doc = result.document

        logger.info(f"Document {document_id} parsed. Chunking...")
        # Use HierarchicalChunker to get semantic chunks
        chunks = list(self.chunker.chunk(doc))

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

"""Docling parser adapter."""

import asyncio
import logging

from atenex_nova.domain.entities.document_node import DocumentNode
from atenex_nova.domain.value_objects.identifiers import NodeType, new_id

logger = logging.getLogger(__name__)


class DoclingParserAdapter:
    """Adapter for Docling document parser using HierarchicalChunker."""

    def __init__(self) -> None:
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

    async def parse(self, file_path: str, document_id: str) -> list[DocumentNode]:
        if not self.converter or not self.chunker:
            logger.error("Cannot parse: Docling is not available")
            return []

        logger.info(f"Parsing document {document_id} at {file_path} with Docling...")

        # Run synchronous Docling conversion in a worker thread
        result = await asyncio.to_thread(self.converter.convert, file_path)
        doc = result.document

        logger.info(f"Document {document_id} parsed. Chunking...")
        # Use HierarchicalChunker to get semantic chunks
        chunks = list(self.chunker.chunk(doc))

        nodes: list[DocumentNode] = []
        for idx, chunk in enumerate(chunks):
            # chunk is a Chunk object from docling_core
            # We map it to our internal DocumentNode
            node_type = NodeType.PARAGRAPH

            # Simple heuristic for tables based on text content since Chunk loses some exact types,
            # though chunk.meta might have it.
            raw_text = chunk.text
            if "|" in raw_text and "\n|" in raw_text:
                node_type = NodeType.TABLE
            elif raw_text.startswith("#"):
                node_type = NodeType.HEADING

            node = DocumentNode(
                id=new_id(),
                document_id=document_id,
                node_type=node_type,
                raw_text=raw_text,
                normalized_text="",
                order_index=idx,
                metadata={"headings": chunk.meta.headings if hasattr(chunk.meta, 'headings') else []}
            )
            nodes.append(node)

        logger.info(f"Extracted {len(nodes)} semantic nodes for document {document_id}")
        return nodes

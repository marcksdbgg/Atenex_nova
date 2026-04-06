"""Stub: Docling parser adapter. Implemented in Fase 2."""
import logging
logger = logging.getLogger(__name__)


class DoclingParserAdapter:
    """Stub adapter for Docling document parser."""
    def __init__(self) -> None:
        logger.info("DoclingParserAdapter initialized (stub)")

    async def parse(self, file_path: str) -> dict:
        logger.info("Stub: parse %s", file_path)
        return {"nodes": [], "metadata": {}}

"""Stub: ColPali visual retriever. Implemented in Fase 7."""
import logging
logger = logging.getLogger(__name__)


class ColPaliAdapter:
    """Stub adapter for ColPali visual retrieval."""
    def __init__(self) -> None:
        logger.info("ColPaliAdapter initialized (stub)")

    async def index_pages(self, pages: list[dict]) -> None:
        logger.info("Stub: index %d pages", len(pages))

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        logger.info("Stub: visual search '%s'", query[:50])
        return []

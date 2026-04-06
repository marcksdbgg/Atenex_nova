"""Worker process entrypoint."""

import asyncio
import logging

from atenex_nova.domain.value_objects.identifiers import JobType
from atenex_nova.infrastructure.db.session import async_session_factory
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.logging.logger import setup_logging
from atenex_nova.workers.jobs.ingestion_job import (
    NormalizeDocumentJobHandler,
    ParseDocumentJobHandler,
)
from atenex_nova.workers.jobs.mem_builder_job import (
    EmbedDocumentJobHandler,
    SegmentDocumentJobHandler,
)
from atenex_nova.workers.runner import JobRunner

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Starting worker process...")

    runner = JobRunner(
        session_factory=async_session_factory,
        poll_interval=2.0
    )

    runner.register_handler(
        JobType.PARSE_DOCUMENT.value,
        ParseDocumentJobHandler(async_session_factory)
    )
    runner.register_handler(
        JobType.NORMALIZE_DOCUMENT.value,
        NormalizeDocumentJobHandler(async_session_factory)
    )
    runner.register_handler(
        JobType.SEGMENT_DOCUMENT.value,
        SegmentDocumentJobHandler(async_session_factory)
    )
    runner.register_handler(
        JobType.EMBED_DOCUMENT.value,
        EmbedDocumentJobHandler(async_session_factory)
    )

    try:
        await runner.run()
    except KeyboardInterrupt:
        logger.info("Stopping worker process...")
        runner.stop()

if __name__ == "__main__":
    asyncio.run(main())

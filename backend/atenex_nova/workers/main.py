"""Worker process entrypoint."""

import asyncio
import logging

from atenex_nova.domain.value_objects.identifiers import JobType
from atenex_nova.infrastructure.db.session import get_session_factory
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.logging.logger import setup_logging
from atenex_nova.workers.jobs.ingestion_job import (
    NormalizeDocumentJobHandler,
    ParseDocumentJobHandler,
)
from atenex_nova.workers.jobs.mem_builder_job import (
    EmbedDocumentJobHandler,
    RebuildCollectionJobHandler,
    SegmentDocumentJobHandler,
)
from atenex_nova.workers.jobs.memory_enrichment_job import (
    BuildCollectionMemoryJobHandler,
    BuildGraphJobHandler,
    CheckDocumentReadinessJobHandler,
    EmbedCollectionMemoryJobHandler,
    EmbedPropositionsJobHandler,
    EmbedSummariesJobHandler,
    ExtractPropositionsJobHandler,
    GenerateSummariesJobHandler,
)
from atenex_nova.workers.jobs.visual_index_job import IndexVisualPagesJobHandler
from atenex_nova.workers.runner import JobRunner

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    from atenex_nova.workers.sqlite_lock import (
        acquire_sqlite_worker_lock,
        release_sqlite_worker_lock,
    )

    lock_handle = acquire_sqlite_worker_lock()
    logger.info("Starting worker process...")

    session_factory = get_session_factory()

    runner = JobRunner(
        session_factory=session_factory,
        poll_interval=settings.worker_poll_interval,
    )

    runner.register_handler(
        JobType.PARSE_DOCUMENT.value,
        ParseDocumentJobHandler(session_factory),
    )
    runner.register_handler(
        JobType.NORMALIZE_DOCUMENT.value,
        NormalizeDocumentJobHandler(session_factory),
    )
    runner.register_handler(
        JobType.SEGMENT_DOCUMENT.value,
        SegmentDocumentJobHandler(session_factory),
    )
    runner.register_handler(
        JobType.EMBED_CHUNKS.value,
        EmbedDocumentJobHandler(session_factory),
    )
    runner.register_handler(
        JobType.EMBED_DOCUMENT.value,
        EmbedDocumentJobHandler(session_factory),
    )
    runner.register_handler(
        JobType.REBUILD_COLLECTION.value,
        RebuildCollectionJobHandler(session_factory),
    )
    runner.register_handler(
        JobType.EXTRACT_PROPOSITIONS.value,
        ExtractPropositionsJobHandler(session_factory),
    )
    runner.register_handler(
        JobType.GENERATE_SUMMARIES.value,
        GenerateSummariesJobHandler(session_factory),
    )
    runner.register_handler(
        JobType.EMBED_PROPOSITIONS.value,
        EmbedPropositionsJobHandler(session_factory),
    )
    runner.register_handler(
        JobType.EMBED_SUMMARIES.value,
        EmbedSummariesJobHandler(session_factory),
    )
    runner.register_handler(
        JobType.BUILD_GRAPH.value,
        BuildGraphJobHandler(session_factory),
    )
    runner.register_handler(
        JobType.CHECK_DOCUMENT_READINESS.value,
        CheckDocumentReadinessJobHandler(session_factory),
    )
    runner.register_handler(
        JobType.BUILD_COLLECTION_MEMORY.value,
        BuildCollectionMemoryJobHandler(session_factory),
    )
    runner.register_handler(
        JobType.EMBED_COLLECTION_MEMORY.value,
        EmbedCollectionMemoryJobHandler(session_factory),
    )
    runner.register_handler(
        JobType.INDEX_VISUAL_PAGES.value,
        IndexVisualPagesJobHandler(session_factory),
    )

    try:
        await runner.run()
    except KeyboardInterrupt:
        logger.info("Stopping worker process...")
        runner.stop()
    finally:
        release_sqlite_worker_lock(lock_handle)

if __name__ == "__main__":
    asyncio.run(main())

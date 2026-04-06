"""Base job handler and job runner."""
import asyncio
import logging
from abc import ABC, abstractmethod
from atenex_nova.domain.entities.job import Job

logger = logging.getLogger(__name__)


class BaseJobHandler(ABC):
    """Abstract base for job handlers."""

    @abstractmethod
    async def execute(self, job: Job) -> dict | None:
        """Execute job logic. Return result dict or None."""
        ...


class JobRunner:
    """Polls for pending jobs and dispatches them to handlers."""

    def __init__(self, session_factory, handlers: dict[str, BaseJobHandler] | None = None,
                 poll_interval: float = 2.0) -> None:
        self._session_factory = session_factory
        self._handlers = handlers or {}
        self._poll_interval = poll_interval
        self._running = False

    def register_handler(self, job_type: str, handler: BaseJobHandler) -> None:
        self._handlers[job_type] = handler

    async def run(self) -> None:
        """Main loop — poll and execute pending jobs."""
        from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
        self._running = True
        logger.info("JobRunner started, polling every %.1fs", self._poll_interval)

        while self._running:
            try:
                async with self._session_factory() as session:
                    repo = SqlJobRepository(session)
                    job = await repo.get_next_pending()
                    if job is None:
                        await asyncio.sleep(self._poll_interval)
                        continue

                    handler = self._handlers.get(job.job_type.value)
                    if handler is None:
                        logger.warning("No handler for job type %s", job.job_type.value)
                        job.fail(f"No handler registered for {job.job_type.value}")
                        await repo.update(job)
                        await session.commit()
                        continue

                    logger.info("Processing job %s (%s)", job.id[:8], job.job_type.value)
                    job.start()
                    await repo.update(job)
                    await session.commit()

                    try:
                        result = await handler.execute(job)
                        async with self._session_factory() as s2:
                            repo2 = SqlJobRepository(s2)
                            j = await repo2.get_by_id(job.id)
                            if j:
                                j.succeed(result)
                                await repo2.update(j)
                            await s2.commit()
                        logger.info("Job %s succeeded", job.id[:8])
                    except Exception as e:
                        logger.error("Job %s failed: %s", job.id[:8], str(e))
                        async with self._session_factory() as s2:
                            repo2 = SqlJobRepository(s2)
                            j = await repo2.get_by_id(job.id)
                            if j:
                                j.fail(str(e))
                                await repo2.update(j)
                            await s2.commit()

            except Exception as e:
                logger.error("JobRunner error: %s", str(e))
                await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False

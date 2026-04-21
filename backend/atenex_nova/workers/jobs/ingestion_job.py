"""Job handlers for ingestion (parse & normalize)."""

import logging
from pathlib import Path

from atenex_nova.domain.entities.job import Job
from atenex_nova.application.policies.query_routing_policy import QueryRoutingPolicy
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_node_repo import SqlDocumentNodeRepository
from atenex_nova.infrastructure.parsing.docling_adapter import DoclingParserAdapter
from atenex_nova.shared.config.settings import PROJECT_ROOT
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService
from atenex_nova.workers.runner import BaseJobHandler

logger = logging.getLogger(__name__)


def _resolve_document_source_path(source_path: str, project_root: Path = PROJECT_ROOT) -> Path:
    """Resolve source paths for both current and legacy storage layouts.

    Current layout stores uploads under backend/storage. Older records may keep
    relative paths and depend on process CWD. Resolve deterministically to avoid
    worker failures when started from a different directory.
    """

    candidate = Path(source_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()

    root_candidate = (project_root / candidate).resolve()
    if root_candidate.exists():
        return root_candidate

    legacy_backend_candidate = (project_root / "backend" / candidate).resolve()
    if legacy_backend_candidate.exists():
        logger.warning(
            "Resolved legacy source_path '%s' to '%s'",
            source_path,
            legacy_backend_candidate,
        )
        return legacy_backend_candidate

    return root_candidate


class ParseDocumentJobHandler(BaseJobHandler):
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict | None:
        document_id = job.target_id

        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            doc = await doc_repo.get_by_id(document_id)
            if not doc:
                raise ValueError(f"Document {document_id} not found")

            audit = PipelineAuditService(session=session)
            resolved_source_path = _resolve_document_source_path(doc.source_path)
            if doc.source_path != str(resolved_source_path):
                doc.source_path = str(resolved_source_path)
                await doc_repo.update(doc)

            try:
                async with audit.step(
                    run_id=job.id,
                    entity_type="document",
                    entity_id=document_id,
                    pipeline="ingestion",
                    stage="parse",
                    context={"source_path": str(resolved_source_path), "mime_type": doc.mime_type},
                ) as step:
                    parser = DoclingParserAdapter()
                    nodes = await parser.parse(str(resolved_source_path), document_id)
                    node_repo = SqlDocumentNodeRepository(session)
                    await node_repo.create_many(nodes)
                    doc.mark_parsed()
                    await doc_repo.update(doc)
                    step.metrics(nodes_extracted=len(nodes), parser="docling" if parser.converter and parser.chunker else "fallback")

                # 4. Enqueue Normalize Job
                from atenex_nova.domain.entities.job import Job
                from atenex_nova.domain.value_objects.identifiers import JobType, new_id
                from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository

                job_repo = SqlJobRepository(session)
                next_job = Job(id=new_id(), job_type=JobType.NORMALIZE_DOCUMENT, target_id=document_id)
                await job_repo.create(next_job)

                await session.commit()

                return {"nodes_extracted": len(nodes)}
            except Exception as e:
                doc.fail(str(e))
                await doc_repo.update(doc)
                await session.commit()
                raise


class NormalizeDocumentJobHandler(BaseJobHandler):
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict | None:
        document_id = job.target_id

        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            node_repo = SqlDocumentNodeRepository(session)

            doc = await doc_repo.get_by_id(document_id)
            if not doc:
                raise ValueError(f"Document {document_id} not found")

            nodes = await node_repo.get_by_document(document_id)

            audit = PipelineAuditService(session=session)
            async with audit.step(
                run_id=job.id,
                entity_type="document",
                entity_id=document_id,
                pipeline="ingestion",
                stage="normalize",
                context={"node_count": len(nodes)},
            ) as step:
                language_samples: list[str] = []
                for node in nodes:
                    normalized = "\n".join(" ".join(line.split()) for line in node.raw_text.splitlines())
                    normalized = normalized.strip()
                    node.normalized_text = normalized
                    if normalized:
                        language_samples.append(normalized[:500])

                from sqlalchemy import select

                from atenex_nova.infrastructure.db.models.tables import DocumentNodeModel

                stmt = select(DocumentNodeModel).where(DocumentNodeModel.document_id == document_id)
                result = await session.execute(stmt)
                models = result.scalars().all()
                for m in models:
                    normalized = "\n".join(" ".join(line.split()) for line in m.raw_text.splitlines()).strip()
                    m.normalized_text = normalized
                    session.add(m)

                document_text = "\n".join(language_samples[:20])
                if document_text:
                    doc.language = QueryRoutingPolicy.detect_language(document_text)
                doc.mark_normalized()
                await doc_repo.update(doc)
                step.metrics(nodes_normalized=len(models), detected_language=doc.language)

            # Enqueue Segment Job
            from atenex_nova.domain.entities.job import Job
            from atenex_nova.domain.value_objects.identifiers import JobType, new_id
            from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository

            job_repo = SqlJobRepository(session)
            next_job = Job(id=new_id(), job_type=JobType.SEGMENT_DOCUMENT, target_id=document_id)
            await job_repo.create(next_job)

            await session.commit()
            return {"nodes_normalized": len(nodes)}

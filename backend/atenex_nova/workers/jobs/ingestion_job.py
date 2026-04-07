"""Job handlers for ingestion (parse & normalize)."""

import logging

from atenex_nova.domain.entities.job import Job
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_node_repo import SqlDocumentNodeRepository
from atenex_nova.infrastructure.parsing.docling_adapter import DoclingParserAdapter
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService
from atenex_nova.workers.runner import BaseJobHandler

logger = logging.getLogger(__name__)


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

            try:
                async with audit.step(
                    run_id=job.id,
                    entity_type="document",
                    entity_id=document_id,
                    pipeline="ingestion",
                    stage="parse",
                    context={"source_path": doc.source_path, "mime_type": doc.mime_type},
                ) as step:
                    parser = DoclingParserAdapter()
                    nodes = await parser.parse(doc.source_path, document_id)
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
                # Simple normalization: trim whitespace, basic language guess (optional)
                for node in nodes:
                    node.normalized_text = " ".join(node.raw_text.split())

                from sqlalchemy import select

                from atenex_nova.infrastructure.db.models.tables import DocumentNodeModel

                stmt = select(DocumentNodeModel).where(DocumentNodeModel.document_id == document_id)
                result = await session.execute(stmt)
                models = result.scalars().all()
                for m in models:
                    m.normalized_text = " ".join(m.raw_text.split())
                    session.add(m)

                doc.mark_normalized()
                await doc_repo.update(doc)
                step.metrics(nodes_normalized=len(models))

            # Enqueue Segment Job
            from atenex_nova.domain.entities.job import Job
            from atenex_nova.domain.value_objects.identifiers import JobType, new_id
            from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository

            job_repo = SqlJobRepository(session)
            next_job = Job(id=new_id(), job_type=JobType.SEGMENT_DOCUMENT, target_id=document_id)
            await job_repo.create(next_job)

            await session.commit()
            return {"nodes_normalized": len(nodes)}

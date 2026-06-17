"""Job handler for visual page indexing."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from atenex_nova.domain.entities.document_node import DocumentNode
from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.value_objects.identifiers import DocumentStatus, NodeType, new_id
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_node_repo import SqlDocumentNodeRepository
from atenex_nova.infrastructure.visual.colpali_adapter import VisualPageRetriever
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService
from atenex_nova.workers.runner import BaseJobHandler


class IndexVisualPagesJobHandler(BaseJobHandler):
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def execute(self, job: Job) -> dict[str, object] | None:
        document_id = job.target_id
        async with self.session_factory() as session:
            doc_repo = SqlDocumentRepository(session)
            node_repo = SqlDocumentNodeRepository(session)
            audit = PipelineAuditService(session=session)
            document = await doc_repo.get_by_id(document_id)
            if document is None:
                raise ValueError(f"Document {document_id} not found")

            nodes = await node_repo.get_by_document(document_id)
            if not nodes:
                if document.status != DocumentStatus.READY:
                    document.mark_ready()
                    await doc_repo.update(document)
                    await session.commit()
                return {"visual_pages_indexed": 0}

            async with audit.step(
                run_id=job.id,
                entity_type="document",
                entity_id=document_id,
                pipeline="visual_indexing",
                stage="index_visual_pages",
                context={"node_count": len(nodes), "collection_id": document.collection_id},
            ) as step:
                pages: dict[int, list[DocumentNode]] = defaultdict(list)
                for node in nodes:
                    pages[int(node.page_number or 1)].append(node)

                payloads: list[dict[str, Any]] = []
                complex_pages = 0
                for page_number, page_nodes in sorted(pages.items()):
                    text = " ".join(node.normalized_text or node.raw_text for node in page_nodes).strip()
                    node_types = {node.node_type for node in page_nodes}
                    is_complex = any(
                        node_type in {NodeType.TABLE, NodeType.IMAGE, NodeType.CAPTION, NodeType.CODE}
                        for node_type in node_types
                    ) or len(page_nodes) > 4 or len(text) > 500
                    complex_pages += int(is_complex)
                    payloads.append(
                        {
                            "id": str(new_id()),
                            "document_id": document.id,
                            "source_page_id": f"{document.id}:{page_number}",
                            "collection_id": document.collection_id,
                            "source_path": document.source_path,
                            "page_number": page_number,
                            "title": document.title,
                            "text": text or document.title,
                            "is_complex": is_complex,
                            "metadata": {
                                "node_ids": [node.id for node in page_nodes],
                                "node_types": [node.node_type.value for node in page_nodes],
                            },
                        }
                    )

                adapter = VisualPageRetriever()
                indexed = await adapter.upsert_pages(document.collection_id, payloads, session=session)
                step.metrics(
                    visual_pages_indexed=len(indexed),
                    complex_pages=complex_pages,
                    pages=len(payloads),
                    qdrant_available=getattr(adapter._qdrant, "is_available", False),
                )
                result: dict[str, object] = {"visual_pages_indexed": len(indexed)}

            if document.status != DocumentStatus.READY:
                document.mark_ready()
                await doc_repo.update(document)

            await session.commit()
            return result

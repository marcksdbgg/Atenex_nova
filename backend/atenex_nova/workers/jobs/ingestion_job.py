"""Job handlers for ingestion (parse & normalize)."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from atenex_nova.application.policies.query_routing_policy import QueryRoutingPolicy
from atenex_nova.domain.entities.job import Job
from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_node_repo import SqlDocumentNodeRepository
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import (
    SqlPropositionRepository,
)
from atenex_nova.infrastructure.db.repositories.sql_relation_repo import SqlRelationRepository
from atenex_nova.infrastructure.db.repositories.sql_summary_repo import SqlSummaryRepository
from atenex_nova.infrastructure.indexes.candidate_index_factory import build_candidate_index
from atenex_nova.infrastructure.indexes.quantized_code_store import QuantizedCodeStore
from atenex_nova.infrastructure.parsing.docling_adapter import DoclingParserAdapter
from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter
from atenex_nova.shared.config.settings import PROJECT_ROOT, get_settings
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService
from atenex_nova.workers.runner import BaseJobHandler

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DocumentIndexArtifacts:
    """Stable IDs that must be removed before document SQL is reset."""

    chunk_ids: tuple[str, ...]
    proposition_ids: tuple[str, ...]
    summary_ids: tuple[str, ...]
    visual_ids: tuple[str, ...]

    @property
    def candidate_ids(self) -> list[str]:
        return list(
            dict.fromkeys(
                (
                    *self.chunk_ids,
                    *self.proposition_ids,
                    *self.summary_ids,
                    *self.visual_ids,
                )
            )
        )


def _load_visual_records(path: Path) -> list[dict[str, object]] | None:
    if not path.exists():
        return []
    if path.is_symlink():
        logger.warning("Refusing to read visual cache symlink %s", path)
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read visual cache %s for cleanup: %s", path, exc)
        return None
    if not isinstance(loaded, list):
        logger.warning("Ignoring malformed visual cache %s: root is not a list", path)
        return None
    return [item for item in loaded if isinstance(item, dict)]


def _visual_ids_for_document(records: list[dict[str, object]], document_id: str) -> list[str]:
    return [
        str(item["id"])
        for item in records
        if str(item.get("document_id") or "") == document_id and item.get("id") is not None
    ]


def _visual_cache_path(root: Path, collection_id: str) -> Path:
    """Resolve the one allowed direct-child JSON cache path."""
    root = root.resolve()
    candidate = root / f"{collection_id}.json"
    if candidate.parent.resolve() != root:
        raise ValueError("collection_id cannot escape the visual cache root")
    return candidate


def _remove_visual_asset_dir(root: Path, document_id: str) -> None:
    """Remove only a real direct-child generated directory, never a symlink."""
    root = root.resolve()
    candidate = root / document_id
    if candidate.parent.resolve() != root:
        raise ValueError("document_id cannot escape the visual cache root")
    if candidate.is_symlink():
        logger.warning("Refusing to follow visual cache symlink %s", candidate)
        return
    if candidate.is_dir():
        shutil.rmtree(candidate)


def _build_qdrant_adapter() -> QdrantAdapter:
    settings = get_settings()
    endpoint = urlparse(settings.qdrant_url)
    return QdrantAdapter(
        host=endpoint.hostname or "localhost",
        port=endpoint.port or 6333,
        required=settings.qdrant_required,
    )


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
                    # Capture stable IDs before SQL is touched. They are the only
                    # reliable bridge to every external/vector representation.
                    chunk_repo = SqlChunkRepository(session)
                    proposition_repo = SqlPropositionRepository(session)
                    summary_repo = SqlSummaryRepository(session)
                    relation_repo = SqlRelationRepository(session)
                    node_repo = SqlDocumentNodeRepository(session)

                    chunks = await chunk_repo.get_by_document(document_id)
                    propositions = await proposition_repo.list_by_document(document_id)
                    summary_ids = await summary_repo.list_ids_for_document_cleanup(
                        document_id,
                        collection_id=doc.collection_id,
                    )
                    visual_root = get_settings().visual_pages_path
                    visual_cache = _visual_cache_path(
                        visual_root,
                        doc.collection_id,
                    )
                    visual_records = _load_visual_records(visual_cache)
                    visual_ids = _visual_ids_for_document(
                        visual_records or [],
                        document_id,
                    )
                    artifacts = DocumentIndexArtifacts(
                        chunk_ids=tuple(chunk.id for chunk in chunks),
                        proposition_ids=tuple(prop.id for prop in propositions),
                        summary_ids=tuple(summary_ids),
                        visual_ids=tuple(visual_ids),
                    )

                    # Remove all candidate layers while IDs still exist. The
                    # explicit code-store delete also covers the turbovec backend.
                    candidate_idx = build_candidate_index(session)
                    if artifacts.candidate_ids:
                        await candidate_idx.remove_vectors(
                            doc.collection_id,
                            artifacts.candidate_ids,
                        )
                        await QuantizedCodeStore(session).delete_by_node_ids(
                            artifacts.candidate_ids
                        )

                    # Delete exact IDs and defensive payload matches in each Qdrant
                    # namespace. Stable IDs make repeats safe; filters catch legacy
                    # random chunk/page IDs from earlier Atenex revisions.
                    qdrant = _build_qdrant_adapter()
                    chunk_namespace = f"collection_{doc.collection_id}"
                    proposition_namespace = f"{chunk_namespace}_propositions"
                    summary_namespace = f"{chunk_namespace}_summaries"
                    await qdrant.delete_points(chunk_namespace, artifacts.chunk_ids)
                    await qdrant.delete_by_filter(
                        chunk_namespace,
                        {"document_id": document_id},
                    )
                    await qdrant.delete_points(
                        proposition_namespace,
                        artifacts.proposition_ids,
                    )
                    await qdrant.delete_by_filter(
                        proposition_namespace,
                        {"document_id": document_id},
                    )
                    await qdrant.delete_points(summary_namespace, artifacts.summary_ids)
                    await qdrant.delete_by_filter(
                        summary_namespace,
                        {"scope_type": "document", "scope_id": document_id},
                    )
                    await qdrant.delete_by_filter(
                        summary_namespace,
                        {"scope_type": "collection", "scope_id": doc.collection_id},
                    )
                    await qdrant.delete_points("pages_visual", artifacts.visual_ids)
                    await qdrant.delete_by_filter(
                        "pages_visual",
                        {"document_id": document_id},
                    )
                    qdrant_cleanup_complete = qdrant.is_available

                    # Only now remove relational artifacts. Collection memory is
                    # derived from document summaries and is invalidated too.
                    await relation_repo.delete_by_node_ids(
                        list(artifacts.proposition_ids)
                    )
                    await summary_repo.delete_by_ids(list(artifacts.summary_ids))
                    await proposition_repo.delete_by_document(document_id)
                    await chunk_repo.delete_by_document(document_id)
                    await node_repo.delete_by_document(document_id)

                    # Generated visual fallback records/assets follow the same
                    # document boundary. Never touch the original source file.
                    if visual_records is not None and visual_cache.exists():
                        filtered = [
                            item
                            for item in visual_records
                            if str(item.get("document_id") or "") != document_id
                        ]
                        visual_cache.write_text(
                            json.dumps(filtered, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    _remove_visual_asset_dir(visual_root, document_id)

                    step.metrics(
                        stale_chunk_vectors=len(artifacts.chunk_ids),
                        stale_proposition_vectors=len(artifacts.proposition_ids),
                        stale_summary_vectors=len(artifacts.summary_ids),
                        stale_visual_vectors=len(artifacts.visual_ids),
                        candidate_layers=("chunk", "proposition", "summary", "visual"),
                        qdrant_cleanup_complete=qdrant_cleanup_complete,
                    )

                    parser = DoclingParserAdapter()
                    nodes = await parser.parse(str(resolved_source_path), document_id)
                    if not nodes:
                        raise ValueError("No extractable nodes found in document")
                    await node_repo.create_many(nodes)
                    doc.mark_parsed()
                    await doc_repo.update(doc)
                    step.metrics(
                        nodes_extracted=len(nodes),
                        parser="docling" if parser.converter and parser.chunker else "fallback",
                    )

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

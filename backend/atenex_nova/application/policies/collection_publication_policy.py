"""Collection-level publication guard for retrieval."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.value_objects.identifiers import DocumentStatus
from atenex_nova.shared.exceptions.base import CollectionPublicationError


@dataclass(frozen=True)
class CollectionPublicationReport:
    """A bounded, auditable view of which documents retrieval may expose."""

    collection_id: str
    status_counts: dict[str, int]
    ready_document_ids: frozenset[str]
    failed_document_ids: tuple[str, ...]

    @property
    def failed_count(self) -> int:
        return len(self.failed_document_ids)

    @property
    def gaps(self) -> tuple[str, ...]:
        if self.failed_count:
            return (f"failed_documents:{self.failed_count}",)
        return ()

    def audit_dict(self) -> dict[str, object]:
        return {
            "status_counts": dict(self.status_counts),
            "ready_documents": len(self.ready_document_ids),
            "failed_documents": self.failed_count,
            "gaps": list(self.gaps),
        }


class CollectionPublicationPolicy:
    """Fail closed while a collection can expose a partially rebuilt corpus.

    Failed documents are terminal and therefore do not make the remaining, READY
    subset unstable.  They remain visible as an explicit corpus gap.  Every other
    non-READY state is transitional and blocks retrieval.
    """

    def evaluate(
        self,
        *,
        collection_id: str,
        documents: list[Document],
        rebuild_active: bool,
    ) -> CollectionPublicationReport:
        status_counts = Counter(document.status.value for document in documents)
        serialized_counts = dict(sorted(status_counts.items()))

        if rebuild_active:
            raise CollectionPublicationError(
                collection_id=collection_id,
                code="COLLECTION_REBUILD_ACTIVE",
                message=(
                    "The collection is being rebuilt; retry after the rebuild and "
                    "document readiness checks finish."
                ),
                document_statuses=serialized_counts,
            )

        if not documents:
            raise CollectionPublicationError(
                collection_id=collection_id,
                code="COLLECTION_EMPTY",
                message="The collection has no documents to query.",
                document_statuses={},
            )

        transient = {
            status: count
            for status, count in serialized_counts.items()
            if status not in {DocumentStatus.READY.value, DocumentStatus.FAILED.value}
        }
        if transient:
            details = ", ".join(f"{status}={count}" for status, count in transient.items())
            raise CollectionPublicationError(
                collection_id=collection_id,
                code="COLLECTION_INDEXING",
                message=(
                    "The collection has documents in transitional ingestion states "
                    f"({details}); retry when they are READY or FAILED."
                ),
                document_statuses=serialized_counts,
            )

        ready_ids = frozenset(
            document.id for document in documents if document.status == DocumentStatus.READY
        )
        failed_ids = tuple(
            sorted(
                document.id
                for document in documents
                if document.status == DocumentStatus.FAILED
            )
        )
        if not ready_ids:
            raise CollectionPublicationError(
                collection_id=collection_id,
                code="COLLECTION_NO_READY_DOCUMENTS",
                message=(
                    "The collection has no READY documents to query; inspect the "
                    "reported failed documents before retrying."
                ),
                document_statuses=serialized_counts,
            )
        return CollectionPublicationReport(
            collection_id=collection_id,
            status_counts=serialized_counts,
            ready_document_ids=ready_ids,
            failed_document_ids=failed_ids,
        )

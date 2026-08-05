"""Atenex Nova — Domain repository interface: DocumentRepository."""

from collections.abc import AsyncIterator
from typing import Protocol

from atenex_nova.domain.entities.document import Document
from atenex_nova.domain.value_objects.identifiers import DocumentStatus


class DocumentRepository(Protocol):
    """Interface for document persistence operations."""

    async def create(self, document: Document) -> Document:
        """Persist a new document."""
        ...

    async def get_by_id(self, document_id: str) -> Document | None:
        """Get a document by its ID."""
        ...

    async def get_by_collection_and_checksum(self, collection_id: str, checksum: str) -> Document | None:
        """Get an existing document in a collection by content checksum."""
        ...

    async def list_by_collection(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 50,
        status: DocumentStatus | None = None,
    ) -> list[Document]:
        """List documents in a collection with optional status filter."""
        ...

    def iter_by_collection_pages(
        self,
        collection_id: str,
        page_size: int = 250,
        status: DocumentStatus | None = None,
    ) -> AsyncIterator[list[Document]]:
        """Iterate over all documents using bounded pages."""
        ...

    async def update(self, document: Document) -> Document:
        """Update an existing document."""
        ...

    async def delete(self, document_id: str) -> bool:
        """Delete a document."""
        ...

    async def count_by_collection(self, collection_id: str) -> int:
        """Count documents in a collection."""
        ...

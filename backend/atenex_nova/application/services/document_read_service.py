"""Application service for document inspection surfaces."""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.infrastructure.db.repositories.sql_chunk_repo import SqlChunkRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_node_repo import SqlDocumentNodeRepository
from atenex_nova.infrastructure.db.repositories.sql_proposition_repo import SqlPropositionRepository
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import EntityNotFoundError


class DocumentReadService:
    """Read model for structure, chunks, propositions and visual pages."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._doc_repo = SqlDocumentRepository(session)
        self._node_repo = SqlDocumentNodeRepository(session)
        self._chunk_repo = SqlChunkRepository(session)
        self._prop_repo = SqlPropositionRepository(session)

    async def get_document(self, document_id: str):
        document = await self._doc_repo.get_by_id(document_id)
        if document is None:
            raise EntityNotFoundError("Document", document_id)
        return document

    async def get_structure(self, document_id: str):
        await self.get_document(document_id)
        return await self._node_repo.get_by_document(document_id)

    async def get_chunks(self, document_id: str):
        await self.get_document(document_id)
        return await self._chunk_repo.get_by_document(document_id)

    async def get_propositions(self, document_id: str):
        await self.get_document(document_id)
        return await self._prop_repo.list_by_document(document_id)

    async def get_page(self, document_id: str, page_number: int) -> dict[str, object]:
        document = await self.get_document(document_id)
        nodes = await self._node_repo.get_by_document(document_id)
        page_nodes = [node for node in nodes if int(node.page_number or 1) == page_number]
        page_text = " ".join(node.normalized_text or node.raw_text for node in page_nodes).strip()
        metadata: dict[str, object] = {
            "node_ids": [node.id for node in page_nodes],
            "node_types": [node.node_type.value for node in page_nodes],
        }

        for page in await self._load_visual_pages(document.collection_id):
            if str(page.get("document_id") or "") != document_id:
                continue
            if int(page.get("page_number") or 1) != page_number:
                continue
            return {
                "id": str(page.get("id") or f"{document_id}:{page_number}"),
                "document_id": document_id,
                "collection_id": document.collection_id,
                "page_number": page_number,
                "title": str(page.get("title") or document.title),
                "text": str(page.get("text") or page_text or document.title),
                "is_complex": bool(page.get("is_complex", False)),
                "image_path": page.get("image_path"),
                "metadata": page.get("metadata") or metadata,
            }

        return {
            "id": f"{document_id}:{page_number}",
            "document_id": document_id,
            "collection_id": document.collection_id,
            "page_number": page_number,
            "title": document.title,
            "text": page_text or document.title,
            "is_complex": False,
            "image_path": None,
            "metadata": metadata,
        }

    async def _load_visual_pages(self, collection_id: str) -> list[dict[str, object]]:
        path = get_settings().visual_pages_path / f"{collection_id}.json"
        if not path.exists():
            return []
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(loaded, list):
            return []
        return [item for item in loaded if isinstance(item, dict)]

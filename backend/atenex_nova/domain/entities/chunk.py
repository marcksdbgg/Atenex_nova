"""Chunk entity."""

import json
from dataclasses import dataclass, field


@dataclass
class Chunk:
    """A segment of text for semantic retrieval, derived from one or more DocumentNodes."""
    id: str
    document_id: str
    text: str
    summary: str = ""
    token_count: int = 0
    node_ids: list[str] = field(default_factory=list)
    embedding_ref: str | None = None
    sparse_ref: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "text": self.text,
            "summary": self.summary,
            "token_count": self.token_count,
            "node_ids_json": json.dumps(self.node_ids),
            "embedding_ref": self.embedding_ref,
            "sparse_ref": self.sparse_ref,
            "metadata_json": json.dumps(self.metadata) if self.metadata else None,
        }

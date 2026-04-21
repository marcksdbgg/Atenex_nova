"""Document node entity."""
import json
from dataclasses import dataclass, field

from atenex_nova.domain.value_objects.identifiers import NodeType


@dataclass
class DocumentNode:
    """A minimal semantic unit from a document (e.g. paragraph, table, heading)."""
    id: str
    document_id: str
    node_type: NodeType
    raw_text: str
    normalized_text: str = ""
    parent_id: str | None = None
    page_number: int | None = None
    order_index: int = 0
    bbox: dict[str, object] | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "parent_id": self.parent_id,
            "node_type": self.node_type.value,
            "page_number": self.page_number,
            "order_index": self.order_index,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "bbox_json": json.dumps(self.bbox) if self.bbox else None,
            "metadata_json": json.dumps(self.metadata) if self.metadata else None,
        }

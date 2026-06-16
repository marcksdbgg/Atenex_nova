"""Infrastructure: Qdrant Dense Adapter."""

from atenex_nova.domain.ports.dense_index import DenseIndexPort
from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter


class QdrantDenseAdapter(QdrantAdapter, DenseIndexPort):
    """Adapter for full/exact dense search in Qdrant."""

    pass

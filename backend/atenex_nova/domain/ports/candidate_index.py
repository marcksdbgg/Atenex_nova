"""Domain Port: CandidateIndexPort protocol."""

from typing import Any, Protocol


class CandidateIndexPort(Protocol):
    """Protocol for candidate-generation stage vector indexing and search."""

    async def add_vectors(
        self,
        collection_id: str,
        memory_layer: str,
        node_ids: list[str],
        vectors: list[list[float]],
    ) -> None:
        """Add a batch of vectors with their node IDs to the index.

        Args:
            collection_id: The collection namespace.
            memory_layer: The memory layer ("chunk" | "proposition" | "summary" | "visual").
            node_ids: String UUIDs of the nodes.
            vectors: Float vectors corresponding to the nodes.
        """
        ...

    async def search(
        self,
        collection_id: str,
        memory_layers: list[str],
        query_vector: list[float],
        top_n: int = 200,
    ) -> list[dict[str, Any]]:
        """Search the compressed index for query candidates.

        Args:
            collection_id: The collection namespace.
            memory_layers: The layers to search across.
            query_vector: The query embedding.
            top_n: Maximum number of candidates to return.

        Returns:
            A list of dicts containing 'node_id', 'score', and 'memory_layer'.
        """
        ...

    async def remove_vectors(self, collection_id: str, node_ids: list[str]) -> None:
        """Remove a batch of vectors by node IDs.

        Args:
            collection_id: The collection namespace.
            node_ids: String UUIDs to remove.
        """
        ...

    async def delete_collection_indexes(self, collection_id: str) -> None:
        """Delete all indexes associated with the collection.

        Args:
            collection_id: The collection namespace.
        """
        ...

"""Optional Qdrant generation index with lazy dependency loading."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any


class QdrantSemanticIndex:
    def __init__(self, *, url: str = "http://127.0.0.1:6333") -> None:
        self._url = url
        self._client: Any | None = None

    def _load(self) -> tuple[Any, Any]:
        try:
            from qdrant_client import QdrantClient, models
        except ImportError as exc:
            raise RuntimeError("qdrant-client is not installed") from exc
        if self._client is None:
            self._client = QdrantClient(url=self._url, timeout=3)
        return self._client, models

    def available(self) -> bool:
        try:
            client, _ = self._load()
            client.get_collections()
            return True
        except Exception:
            return False

    @staticmethod
    def _collection(repository_id: str, generation_id: int) -> str:
        digest = hashlib.sha256(repository_id.encode()).hexdigest()[:16]
        return f"atenex_repo_{digest}_g{generation_id}"

    @staticmethod
    def _manifest_point_id(repository_id: str, generation_id: int) -> int:
        value = f"{repository_id}\0{generation_id}\0semantic-manifest"
        return int(hashlib.sha256(value.encode()).hexdigest()[:15], 16)

    def upsert(
        self,
        *,
        repository_id: str,
        generation_id: int,
        chunks: Sequence[tuple[str, list[float], dict[str, object]]],
    ) -> None:
        if not chunks:
            return
        client, models = self._load()
        collection = self._collection(repository_id, generation_id)
        dimension = len(chunks[0][1])
        if dimension == 0:
            raise ValueError("semantic vectors cannot be empty")
        existing = {item.name for item in client.get_collections().collections}
        if collection not in existing:
            client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(
                    size=dimension,
                    distance=models.Distance.COSINE,
                ),
            )
        points = []
        for chunk_id, vector, metadata in chunks:
            point_id = int(hashlib.sha256(chunk_id.encode()).hexdigest()[:15], 16)
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={"chunk_id": chunk_id, **metadata},
                )
            )
        client.upsert(collection_name=collection, points=points, wait=True)

    def finalize(
        self,
        *,
        repository_id: str,
        generation_id: int,
        embedding_identity: str,
        chunk_count: int,
        vector_size: int,
    ) -> None:
        if vector_size < 1:
            return
        client, models = self._load()
        collection = self._collection(repository_id, generation_id)
        manifest = models.PointStruct(
            id=self._manifest_point_id(repository_id, generation_id),
            vector=[0.0] * vector_size,
            payload={
                "kind": "atenex_semantic_manifest",
                "complete": True,
                "embedding_identity": embedding_identity,
                "chunk_count": chunk_count,
            },
        )
        client.upsert(collection_name=collection, points=[manifest], wait=True)

    def ready(
        self,
        *,
        repository_id: str,
        generation_id: int,
        embedding_identity: str,
    ) -> bool:
        try:
            client, _ = self._load()
            collection = self._collection(repository_id, generation_id)
            points = client.retrieve(
                collection_name=collection,
                ids=[self._manifest_point_id(repository_id, generation_id)],
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            return False
        if len(points) != 1:
            return False
        payload = points[0].payload or {}
        return bool(
            payload.get("kind") == "atenex_semantic_manifest"
            and payload.get("complete") is True
            and payload.get("embedding_identity") == embedding_identity
        )

    def search(
        self,
        *,
        repository_id: str,
        generation_id: int,
        vector: Sequence[float],
        limit: int,
    ) -> list[tuple[str, float]]:
        client, _ = self._load()
        collection = self._collection(repository_id, generation_id)
        if hasattr(client, "query_points"):
            response = client.query_points(
                collection_name=collection,
                query=list(vector),
                limit=limit,
                with_payload=True,
            )
            points = response.points
        else:  # Compatibility with older qdrant-client releases.
            points = client.search(
                collection_name=collection,
                query_vector=list(vector),
                limit=limit,
                with_payload=True,
            )
        results: list[tuple[str, float]] = []
        for point in points:
            payload = point.payload or {}
            chunk_id = payload.get("chunk_id")
            if isinstance(chunk_id, str):
                results.append((chunk_id, float(point.score)))
        return results

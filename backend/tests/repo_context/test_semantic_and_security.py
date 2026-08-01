from __future__ import annotations

import subprocess
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

from atenex_nova.repo_context.application.semantic import OptionalSemanticCoordinator
from atenex_nova.repo_context.application.services import RepoContextServices
from atenex_nova.repo_context.composition import build_runtime
from atenex_nova.repo_context.domain.policies import resolve_inside, safe_relative_path
from atenex_nova.repo_context.infrastructure.semantic.fusion import reciprocal_rank_fusion
from atenex_nova.repo_context.infrastructure.semantic.qdrant_index import (
    QdrantSemanticIndex,
)


class PathPolicyTests(unittest.TestCase):
    def test_rejects_traversal_and_absolute_paths(self) -> None:
        for value in ("../secret", "a/../../secret", "/etc/passwd", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                safe_relative_path(value)

    def test_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            outside = Path(directory) / "outside"
            outside.mkdir()
            (root / "escape").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                resolve_inside(root, "escape/secret.txt")


class SemanticAdapterTests(unittest.TestCase):
    def test_rrf_is_deterministic_and_combines_rankings(self) -> None:
        first = reciprocal_rank_fusion(
            [["lexical", "shared"], ["semantic", "shared"]],
            weights=[1.0, 1.0],
        )
        second = reciprocal_rank_fusion(
            [["lexical", "shared"], ["semantic", "shared"]],
            weights=[1.0, 1.0],
        )
        self.assertEqual(first, second)
        self.assertEqual(first[0][0], "shared")

    def test_qdrant_namespace_separates_generations(self) -> None:
        index = QdrantSemanticIndex()
        first = index._collection("repo", 1)
        second = index._collection("repo", 2)
        other = index._collection("other", 1)
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertTrue(first.startswith("atenex_repo_"))

    def test_optional_semantic_build_and_hybrid_search(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "app.py").write_text(
                "def semantic_target():\n    return 'context'\n",
                encoding="utf-8",
            )
            runtime = build_runtime(repo=root)
            runtime.index_repository()
            generation = runtime.index.active_generation()
            self.assertIsNotNone(generation)

            vector_index = _FakeSemanticIndex()
            coordinator = OptionalSemanticCoordinator(
                embedder=_FakeEmbedder(),
                semantic_index=vector_index,
            )
            inserted = coordinator.build(generation, runtime.index)  # type: ignore[arg-type]
            self.assertGreater(inserted, 0)
            restarted = OptionalSemanticCoordinator(
                embedder=_FakeEmbedder(),
                semantic_index=vector_index,
            )
            self.assertTrue(restarted.ready_for(generation))  # type: ignore[arg-type]
            services = RepoContextServices(
                runtime.scanner,
                runtime.index,
                runtime.extractors,
                semantic=coordinator,
            )
            response = services.search_repo(
                "conceptual context",
                modes=["lexical", "semantic"],
                top_k=5,
            )
            self.assertIn("semantic", response["data"]["modes"])
            self.assertTrue(response["data"]["results"])
            self.assertFalse(
                any(
                    item["code"] == "SEMANTIC_UNAVAILABLE"
                    for item in response["diagnostics"]
                )
            )


class _FakeEmbedder:
    identity = "fake:embedding"

    def available(self) -> bool:
        return True

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0] for text in texts]


class _FakeSemanticIndex:
    def __init__(self) -> None:
        self._ids: list[str] = []
        self._ready: set[tuple[str, int, str]] = set()

    def available(self) -> bool:
        return True

    def upsert(
        self,
        *,
        repository_id: str,
        generation_id: int,
        chunks: Sequence[tuple[str, list[float], dict[str, object]]],
    ) -> None:
        del repository_id, generation_id
        self._ids.extend(chunk_id for chunk_id, _, _ in chunks)

    def finalize(
        self,
        *,
        repository_id: str,
        generation_id: int,
        embedding_identity: str,
        chunk_count: int,
        vector_size: int,
    ) -> None:
        del chunk_count, vector_size
        self._ready.add((repository_id, generation_id, embedding_identity))

    def ready(
        self,
        *,
        repository_id: str,
        generation_id: int,
        embedding_identity: str,
    ) -> bool:
        return (repository_id, generation_id, embedding_identity) in self._ready

    def search(
        self,
        *,
        repository_id: str,
        generation_id: int,
        vector: Sequence[float],
        limit: int,
    ) -> list[tuple[str, float]]:
        del repository_id, generation_id, vector
        return [(chunk_id, 0.9) for chunk_id in self._ids[:limit]]


if __name__ == "__main__":
    unittest.main()

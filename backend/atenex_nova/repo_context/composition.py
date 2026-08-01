"""Composition root for the standalone Repo Context bounded context."""

from __future__ import annotations

import inspect
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atenex_nova.repo_context.application.semantic import OptionalSemanticCoordinator
from atenex_nova.repo_context.application.services import RepoContextServices
from atenex_nova.repo_context.domain.models import GenerationInfo
from atenex_nova.repo_context.domain.ports import (
    ContextIndex,
    LanguageExtractor,
    RepositoryScanner,
)


@dataclass(slots=True)
class RepoContextRuntime:
    """Fully composed runtime for exactly one canonical repository root."""

    root: Path
    data_dir: Path
    scanner: RepositoryScanner
    index: ContextIndex
    extractors: tuple[LanguageExtractor, ...]
    indexer: Any
    services: RepoContextServices
    semantic: OptionalSemanticCoordinator | None = None

    def index_repository(self, *, full: bool = False) -> dict[str, Any]:
        execute = self.indexer.execute
        parameters = inspect.signature(execute).parameters
        result = execute(full=full) if "full" in parameters else execute()
        if isinstance(result, dict):
            payload = result
            generation = self.index.active_generation()
        else:
            payload = None
            generation = result
        if not isinstance(generation, GenerationInfo):
            raise TypeError("index service returned an unsupported result")
        if payload is None:
            payload = {
                "repository_id": generation.snapshot.repository_id,
                "generation": str(generation.id),
                "head": generation.snapshot.head,
                "worktree_fingerprint": generation.snapshot.worktree_fingerprint,
                "files": generation.file_count,
                "symbols": generation.symbol_count,
                "chunks": generation.chunk_count,
                "edges": generation.edge_count,
                "diagnostics": generation.diagnostics_count,
                "state": generation.state,
                "database": str(self.index.database_path),
                "full": full,
            }
        if self.semantic is not None:
            try:
                payload["semantic"] = {
                    "state": "ready",
                    "identity": self.semantic.identity,
                    "chunks": self.semantic.build(generation, self.index),
                }
            except Exception as exc:
                payload["semantic"] = {
                    "state": "degraded",
                    "identity": self.semantic.identity,
                    "error": f"{type(exc).__name__}: {exc}",
                }
        else:
            payload["semantic"] = {"state": "disabled"}
        return payload

    def tool_handler(self) -> Any:
        # Avoid importing the presentation adapter while composing core-only
        # index/status commands.
        from atenex_nova.repo_context.presentation.mcp_server import (
            RepoContextToolHandler,
        )

        return RepoContextToolHandler(self.services)


def build_runtime(
    *,
    repo: Path | str,
    data_dir: Path | str | None = None,
) -> RepoContextRuntime:
    """Compose core adapters without importing FastAPI or optional MCP/ML SDKs."""

    root = Path(repo).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"repository root is not a readable directory: {root}")
    resolved_data_dir = (
        Path(data_dir).expanduser().resolve()
        if data_dir is not None
        else root / ".atenex" / "context"
    )
    database_path = resolved_data_dir / "index.sqlite3"

    # Infrastructure imports stay inside the factory so importing domain,
    # services, CLI help, or the package does not create a sidecar or require
    # optional parser/MCP dependencies.
    from atenex_nova.repo_context.application.indexing import (
        IndexRepositoryService,
    )
    from atenex_nova.repo_context.infrastructure.git_scanner import (
        GitRepositoryScanner,
    )
    from atenex_nova.repo_context.infrastructure.parsers import (
        DefaultLanguageExtractor,
    )
    from atenex_nova.repo_context.infrastructure.sqlite_index import (
        SQLiteContextIndex,
    )

    index = SQLiteContextIndex(database_path)
    default_extractor = DefaultLanguageExtractor()
    scanner = GitRepositoryScanner(
        root,
        parser_version=default_extractor.parser_version,
    )
    extractors: tuple[LanguageExtractor, ...] = (default_extractor,)
    indexer = IndexRepositoryService(scanner, index, extractors)
    semantic: OptionalSemanticCoordinator | None = None
    if _env_enabled("ATENEX_REPO_CONTEXT_SEMANTIC"):
        from atenex_nova.repo_context.infrastructure.semantic import (
            OllamaEmbeddingProvider,
            QdrantSemanticIndex,
        )

        semantic = OptionalSemanticCoordinator(
            embedder=OllamaEmbeddingProvider(
                base_url=os.getenv(
                    "ATENEX_REPO_CONTEXT_OLLAMA_URL",
                    "http://127.0.0.1:11434",
                ),
                model=os.getenv(
                    "ATENEX_REPO_CONTEXT_EMBEDDING_MODEL",
                    "embeddinggemma",
                ),
            ),
            semantic_index=QdrantSemanticIndex(
                url=os.getenv(
                    "ATENEX_REPO_CONTEXT_QDRANT_URL",
                    "http://127.0.0.1:6333",
                )
            ),
        )
    services = RepoContextServices(
        scanner,
        index,
        extractors,
        semantic=semantic,
    )
    return RepoContextRuntime(
        root=root,
        data_dir=resolved_data_dir,
        scanner=scanner,
        index=index,
        extractors=extractors,
        indexer=indexer,
        services=services,
        semantic=semantic,
    )


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}

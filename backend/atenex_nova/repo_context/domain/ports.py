"""Ports owned by the Repo Context bounded context."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from atenex_nova.repo_context.domain.models import (
    CodeChunk,
    CodeEdge,
    CodeSymbol,
    ExtractionResult,
    FileRecord,
    GenerationInfo,
    ScanResult,
    SearchHit,
)


class RepositoryScanner(Protocol):
    @property
    def root(self) -> Path: ...

    def scan(self) -> ScanResult: ...


class LanguageExtractor(Protocol):
    def supports(self, language: str) -> bool: ...

    def extract(self, file: FileRecord) -> ExtractionResult: ...


class ContextIndex(Protocol):
    @property
    def database_path(self) -> Path: ...

    def initialize(self) -> None: ...

    def build_generation(
        self,
        scan: ScanResult,
        extracted: dict[str, ExtractionResult],
        *,
        validate_snapshot: Callable[[], bool] | None = None,
    ) -> GenerationInfo: ...

    def active_generation(self) -> GenerationInfo | None: ...

    def search(
        self,
        query: str,
        *,
        top_k: int,
        path_prefix: str | None = None,
        languages: Sequence[str] = (),
        symbol_kinds: Sequence[str] = (),
    ) -> list[SearchHit]: ...

    def symbols(self, query: str, *, limit: int = 20) -> list[CodeSymbol]: ...

    def symbols_for_path(self, path: str, *, limit: int = 200) -> list[CodeSymbol]: ...

    def symbol_by_id(self, symbol_id: str) -> CodeSymbol | None: ...

    def edges(
        self,
        symbol_id: str,
        *,
        direction: str,
        relations: Sequence[str] = (),
        limit: int = 100,
    ) -> list[CodeEdge]: ...

    def file_text(self, path: str) -> tuple[str, str] | None: ...

    def file_inventory(self) -> list[dict[str, object]]: ...

    def diagnostics(self, *, limit: int = 100) -> list[dict[str, object]]: ...

    def all_chunks(self) -> list[CodeChunk]: ...

    def chunks_by_ids(self, ids: Sequence[str]) -> dict[str, CodeChunk]: ...

    def chunk_content_hashes(self, ids: Sequence[str]) -> dict[str, str]: ...

    def all_edges(self, *, limit: int = 100_000) -> list[CodeEdge]: ...


class EmbeddingProvider(Protocol):
    @property
    def identity(self) -> str: ...

    def available(self) -> bool: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class SemanticIndex(Protocol):
    def available(self) -> bool: ...

    def upsert(
        self,
        *,
        repository_id: str,
        generation_id: int,
        chunks: Sequence[tuple[str, list[float], dict[str, object]]],
    ) -> None: ...

    def search(
        self,
        *,
        repository_id: str,
        generation_id: int,
        vector: Sequence[float],
        limit: int,
    ) -> list[tuple[str, float]]: ...


class ResultReranker(Protocol):
    def available(self) -> bool: ...

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
    ) -> list[float]: ...

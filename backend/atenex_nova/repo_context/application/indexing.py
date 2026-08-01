"""Indexing use case for the deterministic repository context core."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from atenex_nova.repo_context.domain.models import (
    CodeChunk,
    Diagnostic,
    ExtractionResult,
    FileRecord,
    GenerationInfo,
    ScanResult,
)
from atenex_nova.repo_context.domain.ports import (
    ContextIndex,
    LanguageExtractor,
    RepositoryScanner,
)


class IndexRepositoryService:
    """Scan, extract and atomically publish a complete index generation."""

    def __init__(
        self,
        scanner: RepositoryScanner,
        index: ContextIndex,
        extractors: Sequence[LanguageExtractor] = (),
        *,
        max_chunk_lines: int = 80,
        max_chunk_chars: int = 12_000,
    ) -> None:
        self._scanner = scanner
        self._index = index
        self._extractors = tuple(extractors)
        self._max_chunk_lines = max(1, max_chunk_lines)
        self._max_chunk_chars = max(256, max_chunk_chars)

    def execute(self, *, full: bool = False) -> GenerationInfo:
        self._index.initialize()
        scan = self._scanner.scan()
        active = self._index.active_generation()
        if not full and active is not None and _same_snapshot(active, scan):
            return active
        reuse = getattr(self._index, "reusable_extraction", None)
        extracted: dict[str, ExtractionResult] = {}
        for file in scan.files:
            cached: object | None = None
            if not full and callable(reuse):
                cached = reuse(
                    file,
                    parser_version=scan.snapshot.parser_version,
                )
            extracted[file.path] = (
                cached if isinstance(cached, ExtractionResult) else self._extract(file)
            )
        return self._index.build_generation(
            scan,
            extracted,
            validate_snapshot=lambda: self._snapshot_is_current(scan),
        )

    def run(self, *, full: bool = False) -> GenerationInfo:
        """Compatibility alias for command and worker-style callers."""
        return self.execute(full=full)

    def _extract(self, file: FileRecord) -> ExtractionResult:
        extractor = next(
            (
                candidate
                for candidate in self._extractors
                if candidate.supports(file.language)
            ),
            None,
        )
        if extractor is None:
            return ExtractionResult(
                chunks=self._lexical_chunks(file),
                parse_state="lexical",
            )
        try:
            result = extractor.extract(file)
        except Exception as exc:
            diagnostic = Diagnostic(
                code="parse_fallback",
                message=f"{type(exc).__name__}: parser failed; lexical fallback used",
                path=file.path,
            )
            return ExtractionResult(
                chunks=self._lexical_chunks(file),
                diagnostics=(diagnostic,),
                parse_state="failed",
            )
        if result.chunks:
            return result
        return ExtractionResult(
            chunks=self._lexical_chunks(file),
            symbols=result.symbols,
            edges=result.edges,
            diagnostics=result.diagnostics,
            parse_state=result.parse_state,
        )

    def _snapshot_is_current(self, expected: ScanResult) -> bool:
        current = self._scanner.scan()
        return (
            current.snapshot.repository_id == expected.snapshot.repository_id
            and current.snapshot.head == expected.snapshot.head
            and current.snapshot.worktree_fingerprint
            == expected.snapshot.worktree_fingerprint
        )

    def _lexical_chunks(self, file: FileRecord) -> tuple[CodeChunk, ...]:
        lines = file.text.splitlines(keepends=True)
        if not lines and file.text:
            lines = [file.text]
        chunks: list[CodeChunk] = []
        cursor = 0
        while cursor < len(lines):
            end = min(cursor + self._max_chunk_lines, len(lines))
            while end > cursor + 1 and len("".join(lines[cursor:end])) > self._max_chunk_chars:
                end -= 1
            content = "".join(lines[cursor:end])
            if len(content) > self._max_chunk_chars:
                content = content[: self._max_chunk_chars]
            line_start = cursor + 1
            line_end = max(line_start, end)
            identity = (
                f"{file.path}\0{file.content_hash}\0{line_start}\0{line_end}\0"
                f"{hashlib.sha256(content.encode()).hexdigest()}"
            )
            chunks.append(
                CodeChunk(
                    id=hashlib.sha256(identity.encode()).hexdigest(),
                    file_path=file.path,
                    language=file.language,
                    line_start=line_start,
                    line_end=line_end,
                    content=content,
                    kind="lexical",
                )
            )
            cursor = end
        return tuple(chunks)


def _same_snapshot(active: GenerationInfo, scan: ScanResult) -> bool:
    """Return true only when the active generation already represents this scan."""

    indexed = active.snapshot
    current = scan.snapshot
    return (
        indexed.repository_id == current.repository_id
        and indexed.head == current.head
        and indexed.worktree_fingerprint == current.worktree_fingerprint
        and indexed.content_fingerprint == current.content_fingerprint
        and indexed.schema_version == current.schema_version
        and indexed.parser_version == current.parser_version
    )

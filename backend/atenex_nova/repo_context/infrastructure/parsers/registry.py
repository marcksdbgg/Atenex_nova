"""Language extractor registry with dependency-free defaults."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace

from atenex_nova.repo_context.domain.models import (
    Diagnostic,
    ExtractionResult,
    FileRecord,
)
from atenex_nova.repo_context.infrastructure.parsers.common import bounded_chunks
from atenex_nova.repo_context.infrastructure.parsers.patterns import (
    JavaExtractor,
    JavaScriptFamilyExtractor,
    SqlExtractor,
    StructuralTextExtractor,
)
from atenex_nova.repo_context.infrastructure.parsers.python import PythonExtractor
from atenex_nova.repo_context.infrastructure.parsers.treesitter import (
    OptionalTreeSitterExtractor,
)

_ALIASES = {
    "py": "python",
    "python3": "python",
    "ts": "typescript",
    "typescriptreact": "tsx",
    "javascriptreact": "jsx",
    "js": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "md": "markdown",
    "mdx": "markdown",
    "yml": "yaml",
    "jsonc": "jsonc",
    "bash": "shell",
    "sh": "shell",
    "zsh": "shell",
}
_JS_LANGUAGES = frozenset({"typescript", "tsx", "javascript", "jsx"})
_STRUCTURAL_LANGUAGES = frozenset(
    {
        "markdown",
        "json",
        "jsonc",
        "yaml",
        "toml",
        "css",
        "scss",
        "less",
        "shell",
        "text",
        "plaintext",
    }
)
_EXTRACTOR_SCHEMA_VERSION = "repo-context-parser-v1.1.0"


class DefaultLanguageExtractor:
    """Route a file to a conservative language adapter.

    No optional parser is imported at module load. This is the service-free v1
    implementation of the ``LanguageExtractor`` port.
    """

    def __init__(
        self,
        *,
        max_chunk_lines: int = 80,
        max_chunk_chars: int = 12_000,
    ) -> None:
        if max_chunk_lines < 1:
            raise ValueError("max_chunk_lines must be positive")
        if max_chunk_chars < 64:
            raise ValueError("max_chunk_chars must be at least 64")
        self._max_chunk_lines = max_chunk_lines
        self._max_chunk_chars = max_chunk_chars
        kwargs = {
            "max_chunk_lines": max_chunk_lines,
            "max_chunk_chars": max_chunk_chars,
        }
        self._python = PythonExtractor(**kwargs)
        self._javascript = JavaScriptFamilyExtractor(**kwargs)
        self._sql = SqlExtractor(**kwargs)
        self._java = JavaExtractor(**kwargs)
        self._structural = StructuralTextExtractor(**kwargs)
        self._tree_sitter = OptionalTreeSitterExtractor(
            max_chunk_lines=max_chunk_lines,
            max_chunk_chars=max_chunk_chars,
        )

    @property
    def parser_version(self) -> str:
        """Return a stable cache key for every extraction-affecting input."""

        identity = {
            "schema": _EXTRACTOR_SCHEMA_VERSION,
            "max_chunk_lines": self._max_chunk_lines,
            "max_chunk_chars": self._max_chunk_chars,
            "tree_sitter": self._tree_sitter.implementation_identity(),
        }
        digest = hashlib.sha256(
            json.dumps(
                identity,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return f"{_EXTRACTOR_SCHEMA_VERSION}:{digest[:20]}"

    def supports(self, language: str) -> bool:
        normalized = self._normalize(language)
        return normalized in (
            {"python", "sql", "java"}
            | _JS_LANGUAGES
            | _STRUCTURAL_LANGUAGES
        )

    def extract(self, file: FileRecord) -> ExtractionResult:
        language = self._normalize(file.language)
        try:
            if language == "python":
                result = self._python.extract(file)
            elif language in _JS_LANGUAGES:
                result = self._tree_sitter_or_fallback(
                    file,
                    language,
                    self._javascript.extract,
                )
            elif language == "sql":
                result = self._tree_sitter_or_fallback(
                    file,
                    language,
                    self._sql.extract,
                )
            elif language == "java":
                result = self._tree_sitter_or_fallback(
                    file,
                    language,
                    self._java.extract,
                )
            elif language in _STRUCTURAL_LANGUAGES:
                result = self._structural.extract(file)
            else:
                return self._fallback(
                    file,
                    Diagnostic(
                        code="unsupported_language",
                        message=(
                            f"No structural extractor for {file.language!r}; "
                            "lexical fallback used"
                        ),
                        severity="info",
                        path=file.path,
                        details={"language": language},
                    ),
                )
            return self._without_duplicate_ids(file, result)
        except Exception as exc:  # parsers must remain file-local
            return self._fallback(
                file,
                Diagnostic(
                    code="extractor_failed",
                    message=f"{type(exc).__name__}: {exc}",
                    severity="error",
                    path=file.path,
                    details={"language": language},
                ),
            )

    @staticmethod
    def _normalize(language: str) -> str:
        normalized = language.strip().lower().lstrip(".")
        return _ALIASES.get(normalized, normalized)

    def _fallback(
        self,
        file: FileRecord,
        diagnostic: Diagnostic,
    ) -> ExtractionResult:
        return ExtractionResult(
            chunks=bounded_chunks(
                file,
                max_lines=self._max_chunk_lines,
                max_chars=self._max_chunk_chars,
                kind="text",
            ),
            diagnostics=(diagnostic,),
            parse_state="lexical",
        )

    def _tree_sitter_or_fallback(
        self,
        file: FileRecord,
        language: str,
        fallback: Callable[[FileRecord], ExtractionResult],
    ) -> ExtractionResult:
        attempt = self._tree_sitter.try_extract(file, language)
        if attempt.result is not None:
            fallback_result = fallback(file)
            symbols = {symbol.id: symbol for symbol in attempt.result.symbols}
            for symbol in fallback_result.symbols:
                symbols.setdefault(symbol.id, symbol)
            edges = {edge.id: edge for edge in attempt.result.edges}
            for edge in fallback_result.edges:
                promoted = replace(edge, method="tree_sitter")
                edges.setdefault(promoted.id, promoted)
            return ExtractionResult(
                chunks=attempt.result.chunks,
                symbols=tuple(
                    sorted(
                        symbols.values(),
                        key=lambda symbol: (
                            symbol.line_start,
                            symbol.line_end,
                            symbol.qualified_name,
                            symbol.kind,
                        ),
                    )
                ),
                edges=tuple(
                    sorted(
                        edges.values(),
                        key=lambda edge: (
                            edge.source_path,
                            edge.evidence_line,
                            edge.relation,
                            edge.target_name,
                            edge.id,
                        ),
                    )
                ),
                parse_state="parsed",
            )
        fallback_result = fallback(file)
        if attempt.diagnostic is None:
            return fallback_result
        return ExtractionResult(
            chunks=fallback_result.chunks,
            symbols=fallback_result.symbols,
            edges=fallback_result.edges,
            diagnostics=(attempt.diagnostic, *fallback_result.diagnostics),
            parse_state=fallback_result.parse_state,
        )

    @staticmethod
    def _without_duplicate_ids(
        file: FileRecord,
        result: ExtractionResult,
    ) -> ExtractionResult:
        symbol_ids: set[str] = set()
        symbols = []
        duplicate_symbols = 0
        for symbol in result.symbols:
            if symbol.id in symbol_ids:
                duplicate_symbols += 1
                continue
            symbol_ids.add(symbol.id)
            symbols.append(symbol)
        chunk_ids: set[str] = set()
        chunks = []
        duplicate_chunks = 0
        for chunk in result.chunks:
            if chunk.id in chunk_ids:
                duplicate_chunks += 1
                continue
            chunk_ids.add(chunk.id)
            chunks.append(chunk)
        edge_ids: set[str] = set()
        edges = []
        duplicate_edges = 0
        for edge in result.edges:
            if edge.id in edge_ids:
                duplicate_edges += 1
                continue
            edge_ids.add(edge.id)
            edges.append(edge)
        duplicate_count = duplicate_symbols + duplicate_chunks + duplicate_edges
        if not duplicate_count:
            return result
        diagnostic = Diagnostic(
            code="duplicate_extraction_id",
            message="Duplicate derived ids were discarded before persistence",
            path=file.path,
            details={
                "symbols": duplicate_symbols,
                "chunks": duplicate_chunks,
                "edges": duplicate_edges,
            },
        )
        return ExtractionResult(
            chunks=tuple(chunks),
            symbols=tuple(symbols),
            edges=tuple(edges),
            diagnostics=(*result.diagnostics, diagnostic),
            parse_state=result.parse_state,
        )


ParserRegistry = DefaultLanguageExtractor

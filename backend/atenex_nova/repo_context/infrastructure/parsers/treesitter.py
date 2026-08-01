"""Optional Tree-sitter extraction without an import-time dependency.

The language pack is loaded lazily and only preloaded grammars are used. Recent
versions can download grammars on demand; repository indexing never triggers
that network behavior.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from atenex_nova.repo_context.domain.models import (
    CodeEdge,
    CodeSymbol,
    Diagnostic,
    ExtractionResult,
    FileRecord,
)
from atenex_nova.repo_context.infrastructure.parsers.common import (
    bounded_chunks,
    make_edge,
    make_symbol,
)


class _ProcessConfigFactory(Protocol):
    def __call__(
        self,
        *,
        language: str,
        structure: bool,
        imports: bool,
        exports: bool,
        symbols: bool,
        diagnostics: bool,
        chunk_max_size: int,
    ) -> object: ...


class _Pack(Protocol):
    ProcessConfig: _ProcessConfigFactory

    def process(self, source: str, config: object | None = None) -> object: ...


@dataclass(frozen=True, slots=True)
class TreeSitterAttempt:
    result: ExtractionResult | None
    diagnostic: Diagnostic | None


_LANGUAGES = {
    "typescript": "typescript",
    "tsx": "tsx",
    "javascript": "javascript",
    "jsx": "javascript",
    "java": "java",
    "sql": "sql",
}
_KIND_MAP = {
    "annotation": "annotation",
    "class": "class",
    "constant": "constant",
    "constructor": "constructor",
    "enum": "enum",
    "function": "function",
    "interface": "interface",
    "method": "method",
    "module": "module",
    "namespace": "namespace",
    "record": "record",
    "struct": "struct",
    "trait": "interface",
    "type": "type",
    "variable": "variable",
}


class OptionalTreeSitterExtractor:
    """Use the language pack's native processing API when safely available."""

    def __init__(
        self,
        *,
        max_chunk_lines: int,
        max_chunk_chars: int,
        module_loader: Callable[[str], object] | None = None,
    ) -> None:
        self._max_chunk_lines = max_chunk_lines
        self._max_chunk_chars = max_chunk_chars
        self._module_loader = module_loader or importlib.import_module
        self._module: _Pack | None = None
        self._module_attempted = False
        self._module_error: str | None = None
        self._configured = False
        self._language_errors: dict[str, str] = {}

    def supports(self, language: str) -> bool:
        return language in _LANGUAGES

    def availability(self, language: str) -> tuple[bool, str | None]:
        module, error = self._get_module(language)
        return module is not None, error

    def implementation_identity(self) -> dict[str, object]:
        """Describe the parser implementation without downloading grammars.

        The result is suitable for inclusion in the persistent parser-version
        fingerprint.  Availability matters as much as the installed package
        version: a newly preloaded grammar must invalidate cached conservative
        extraction results.
        """

        languages = sorted(set(_LANGUAGES.values()))
        availability = {
            language: self.availability(language)[0] for language in languages
        }
        try:
            package_version = importlib.metadata.version(
                "tree-sitter-language-pack"
            )
        except importlib.metadata.PackageNotFoundError:
            package_version = "not-installed"
        return {
            "adapter": "tree-sitter-language-pack",
            "package_version": package_version,
            "grammars": availability,
        }

    def try_extract(self, file: FileRecord, language: str) -> TreeSitterAttempt:
        module, error = self._get_module(language)
        if module is None:
            return TreeSitterAttempt(
                result=None,
                diagnostic=_fallback_diagnostic(
                    file,
                    code="tree_sitter_unavailable",
                    message=error or "Tree-sitter grammar is unavailable",
                    language=language,
                ),
            )
        grammar = _LANGUAGES[language]
        try:
            config = module.ProcessConfig(
                language=grammar,
                structure=True,
                imports=True,
                exports=True,
                symbols=True,
                diagnostics=True,
                chunk_max_size=self._max_chunk_chars,
            )
            processed = module.process(file.text, config)
        except Exception as exc:
            return TreeSitterAttempt(
                result=None,
                diagnostic=_fallback_diagnostic(
                    file,
                    code="tree_sitter_failed",
                    message=f"{type(exc).__name__}: {exc}",
                    language=language,
                ),
            )

        diagnostics = list(cast(Iterable[object], getattr(processed, "diagnostics", ())))
        metrics = getattr(processed, "metrics", None)
        error_count = int(getattr(metrics, "error_count", 0)) if metrics else 0
        if diagnostics or error_count:
            lines = sorted(
                {
                    int(getattr(span, "start_line", 0)) + 1
                    for item in diagnostics
                    if (span := getattr(item, "span", None)) is not None
                }
            )[:20]
            return TreeSitterAttempt(
                result=None,
                diagnostic=Diagnostic(
                    code="tree_sitter_parse_error",
                    message=(
                        "Tree-sitter reported syntax errors; "
                        "conservative fallback used"
                    ),
                    path=file.path,
                    details={
                        "language": language,
                        "error_count": max(error_count, len(diagnostics), 1),
                        "lines": lines,
                        "fallback": _fallback_name(language),
                    },
                ),
            )

        try:
            symbols, edges = _convert_structure(
                file,
                cast(
                    Sequence[object],
                    getattr(processed, "structure", ()),
                ),
            )
        except Exception as exc:
            return TreeSitterAttempt(
                result=None,
                diagnostic=_fallback_diagnostic(
                    file,
                    code="tree_sitter_extraction_failed",
                    message=f"{type(exc).__name__}: {exc}",
                    language=language,
                ),
            )
        chunk_kind = (
            "tree_sitter_sql_statement"
            if language == "sql"
            else "tree_sitter_code"
        )
        return TreeSitterAttempt(
            result=ExtractionResult(
                chunks=bounded_chunks(
                    file,
                    max_lines=self._max_chunk_lines,
                    max_chars=self._max_chunk_chars,
                    kind=chunk_kind,
                ),
                symbols=symbols,
                edges=edges,
                parse_state="parsed",
            ),
            diagnostic=None,
        )

    def _get_module(self, language: str) -> tuple[_Pack | None, str | None]:
        grammar = _LANGUAGES.get(language)
        if grammar is None:
            return None, f"unsupported Tree-sitter language: {language}"
        if grammar in self._language_errors:
            return None, self._language_errors[grammar]
        module = self._load_module()
        if module is None:
            return None, self._module_error
        try:
            self._configure_cache(module)
            downloaded = getattr(module, "downloaded_languages", None)
            if callable(downloaded):
                available = {
                    str(item)
                    for item in cast(Iterable[object], downloaded())
                }
                if grammar not in available:
                    error = (
                        f"grammar {grammar!r} is not preloaded; "
                        "runtime downloads are disabled"
                    )
                    self._language_errors[grammar] = error
                    return None, error
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._language_errors[grammar] = error
            return None, error
        return module, None

    def _load_module(self) -> _Pack | None:
        if self._module_attempted:
            return self._module
        self._module_attempted = True
        try:
            self._module = cast(
                _Pack,
                self._module_loader("tree_sitter_language_pack"),
            )
        except Exception as exc:
            self._module_error = f"{type(exc).__name__}: {exc}"
        return self._module

    def _configure_cache(self, module: _Pack) -> None:
        if self._configured:
            return
        self._configured = True
        cache_dir = os.environ.get("ATENEX_TREE_SITTER_CACHE_DIR", "").strip()
        if not cache_dir:
            return
        configure = getattr(module, "configure", None)
        pack_config = getattr(module, "PackConfig", None)
        if callable(configure) and callable(pack_config):
            configure(pack_config(cache_dir=cache_dir))


def _convert_structure(
    file: FileRecord,
    items: Sequence[object],
) -> tuple[tuple[CodeSymbol, ...], tuple[CodeEdge, ...]]:
    symbols: list[CodeSymbol] = []
    edges: list[CodeEdge] = []
    package = _java_package(file.text) if file.language == "java" else ""
    for item in items:
        kind = _kind(item)
        name = _optional_string(getattr(item, "name", None))
        if kind == "module" and file.language == "java":
            package = name or package
            continue
        _append_structure_item(
            file,
            item,
            symbols,
            edges,
            parent=None,
            prefix=package,
        )
    return (
        tuple(
            sorted(
                symbols,
                key=lambda symbol: (
                    symbol.line_start,
                    symbol.line_end,
                    symbol.qualified_name,
                    symbol.kind,
                ),
            )
        ),
        tuple(
            sorted(
                edges,
                key=lambda edge: (
                    edge.source_path,
                    edge.evidence_line,
                    edge.relation,
                    edge.target_name,
                    edge.id,
                ),
            )
        ),
    )


def _append_structure_item(
    file: FileRecord,
    item: object,
    symbols: list[CodeSymbol],
    edges: list[CodeEdge],
    *,
    parent: CodeSymbol | None,
    prefix: str,
) -> None:
    name = _optional_string(getattr(item, "name", None))
    kind = _kind(item)
    span = getattr(item, "span", None)
    symbol = parent
    if name and span is not None:
        qualified = f"{parent.qualified_name}.{name}" if parent else name
        if not parent and prefix:
            qualified = f"{prefix}.{qualified}"
        source = _span_text(file.text, span)
        signature = _optional_string(getattr(item, "signature", None))
        signature = signature or _first_line(source)
        if kind in {"method", "constructor"}:
            parameters = _parameter_text(source)
            if parameters:
                qualified = f"{qualified}{parameters}"
        qualified = _unique_qualified(
            symbols,
            qualified,
            kind,
            _span_line(span),
        )
        symbol = make_symbol(
            file,
            name=name,
            qualified_name=qualified,
            kind=kind,
            line_start=_span_line(span),
            line_end=_span_end_line(span),
            signature=signature,
            parent_id=parent.id if parent else None,
            role=_role(name, file.path),
        )
        symbols.append(symbol)
        if parent:
            edges.append(
                make_edge(
                    file,
                    relation="contains",
                    source_symbol_id=parent.id,
                    target_symbol_id=symbol.id,
                    target_name=symbol.qualified_name,
                    evidence_line=symbol.line_start,
                    confidence=1.0,
                    method="tree_sitter",
                    unresolved=False,
                )
            )
    children = cast(
        Sequence[object],
        getattr(item, "children", ()),
    )
    for child in children:
        _append_structure_item(
            file,
            child,
            symbols,
            edges,
            parent=symbol,
            prefix=prefix,
        )


def _kind(item: object) -> str:
    raw = str(getattr(item, "kind", "symbol")).lower()
    raw = raw.rsplit(".", 1)[-1]
    return _KIND_MAP.get(raw, raw or "symbol")


def _span_text(text: str, span: object) -> str:
    encoded = text.encode("utf-8")
    start = int(getattr(span, "start_byte", 0))
    end = int(getattr(span, "end_byte", start))
    return encoded[start:end].decode("utf-8", errors="replace")


def _span_line(span: object) -> int:
    return int(getattr(span, "start_line", 0)) + 1


def _span_end_line(span: object) -> int:
    return max(
        _span_line(span),
        int(getattr(span, "end_line", 0)) + 1,
    )


def _parameter_text(value: str) -> str:
    header = value.split("{", 1)[0]
    opening = header.find("(")
    if opening < 0:
        return ""
    depth = 0
    for index in range(opening, len(header)):
        if header[index] == "(":
            depth += 1
        elif header[index] == ")":
            depth -= 1
            if depth == 0:
                return header[opening : index + 1]
    return ""


def _first_line(value: str) -> str:
    if not value.strip():
        return ""
    first = " ".join(value.strip().splitlines()[0].split())
    return first.split("{", 1)[0].rstrip()[:500]


def _optional_string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _unique_qualified(
    symbols: Iterable[CodeSymbol],
    qualified_name: str,
    kind: str,
    line: int,
) -> str:
    if any(
        symbol.qualified_name == qualified_name and symbol.kind == kind
        for symbol in symbols
    ):
        return f"{qualified_name}@L{line}"
    return qualified_name


def _java_package(text: str) -> str:
    match = re.search(r"(?m)^\s*package\s+([\w.]+)\s*;", text)
    return match.group(1) if match else ""


def _role(name: str, path: str) -> str | None:
    lowered = path.lower()
    if (
        name.lower().startswith("test")
        or "/tests/" in f"/{lowered}"
        or ".test." in lowered
        or ".spec." in lowered
    ):
        return "test"
    return None


def _fallback_name(language: str) -> str:
    if language in {"typescript", "tsx", "javascript", "jsx"}:
        return "js_pattern"
    if language == "java":
        return "java_pattern"
    return "sql_pattern"


def _fallback_diagnostic(
    file: FileRecord,
    *,
    code: str,
    message: str,
    language: str,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        message=message,
        severity="info" if code == "tree_sitter_unavailable" else "warning",
        path=file.path,
        details={
            "language": language,
            "fallback": _fallback_name(language),
        },
    )

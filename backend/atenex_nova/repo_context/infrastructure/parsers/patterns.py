"""Conservative source extractors for languages without mandatory parsers.

These adapters deliberately report evidence rather than compiler-level
resolution. Tree-sitter can replace individual adapters later without changing
the common domain representation.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable
from typing import Any

from atenex_nova.repo_context.domain.models import (
    CodeEdge,
    CodeSymbol,
    Diagnostic,
    ExtractionResult,
    FileRecord,
)
from atenex_nova.repo_context.infrastructure.parsers.common import (
    bounded_chunks,
    chunks_for_spans,
    containing_symbol,
    deduplicate_edges,
    line_at_offset,
    make_edge,
    make_symbol,
)

_JS_CLASS_RE = re.compile(
    r"(?m)^[ \t]*(?:export\s+(?:default\s+)?)?"
    r"(?:abstract\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)"
    r"(?:\s+extends\s+(?P<extends>[A-Za-z_$][\w$.-]*))?"
    r"(?:\s+implements\s+(?P<implements>[^{]+))?"
)
_JS_NAMED_RE = re.compile(
    r"(?m)^[ \t]*(?:export\s+(?:default\s+)?)?"
    r"(?:(?P<async>async)\s+)?function\s+\*?\s*"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*(?P<args>\([^)]*\))"
)
_JS_ARROW_RE = re.compile(
    r"(?m)^[ \t]*(?:export\s+)?(?:const|let|var)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)"
    r"(?:\s*:[^=\n]+)?\s*=\s*(?:async\s*)?"
    r"(?P<args>\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
)
_JS_TYPE_RE = re.compile(
    r"(?m)^[ \t]*(?:export\s+)?"
    r"(?P<kind>interface|type|enum|namespace)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)"
    r"(?:\s+extends\s+(?P<extends>[^{=\n]+))?"
)
_JS_VARIABLE_RE = re.compile(
    r"(?m)^[ \t]*(?P<export>export\s+)?(?P<kind>const|let|var)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)(?:\s*:[^=\n]+)?\s*=\s*(?P<value>[^\n]*)"
)
_JS_IMPORT_RE = re.compile(
    r"""(?mx)
    ^[ \t]*import(?:[\s\S]*?\sfrom\s*)?["'](?P<module>[^"']+)["']
    |^[ \t]*(?:const|let|var)\s+[\w${}, *]+\s*=\s*require\(["'](?P<require>[^"']+)["']\)
    """
)
_JS_EXPORT_FROM_RE = re.compile(
    r"""(?m)^[ \t]*export\s+(?:\*|\{[^}]*\})\s+from\s+["'](?P<module>[^"']+)["']"""
)
_JS_CALL_RE = re.compile(
    r"(?<![\w$])(?P<name>[A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*)*)\s*\("
)
_JS_CALL_EXCLUSIONS = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "function",
        "return",
        "typeof",
        "new",
        "super",
    }
)


class JavaScriptFamilyExtractor:
    def __init__(self, *, max_chunk_lines: int, max_chunk_chars: int) -> None:
        self._max_chunk_lines = max_chunk_lines
        self._max_chunk_chars = max_chunk_chars

    def extract(self, file: FileRecord) -> ExtractionResult:
        chunks = bounded_chunks(
            file,
            max_lines=self._max_chunk_lines,
            max_chars=self._max_chunk_chars,
            kind="code",
        )
        symbols: list[CodeSymbol] = []
        edges: list[CodeEdge] = []
        diagnostics = _brace_diagnostics(file, method="js_pattern")

        for match in _JS_CLASS_RE.finditer(file.text):
            start = line_at_offset(file.text, match.start())
            end = _brace_block_end(file.text, match.end(), start)
            symbol = make_symbol(
                file,
                name=match.group("name"),
                qualified_name=match.group("name"),
                kind="class",
                line_start=start,
                line_end=end,
                signature=_line_signature(file.text, match.start()),
                role=_role_for_name(match.group("name"), file.path),
            )
            symbols.append(symbol)
            if _is_exported_declaration(match.group(0)):
                edges.append(_export_edge(file, symbol, start, "js_pattern"))
            extended = match.group("extends")
            if extended:
                edges.append(
                    make_edge(
                        file,
                        relation="extends",
                        source_symbol_id=symbol.id,
                        target_name=extended.strip(),
                        evidence_line=start,
                        confidence=0.84,
                        method="js_pattern",
                    )
                )
            implemented = match.group("implements") or ""
            for index, target in enumerate(_split_names(implemented)):
                edges.append(
                    make_edge(
                        file,
                        relation="implements",
                        source_symbol_id=symbol.id,
                        target_name=target,
                        evidence_line=start,
                        confidence=0.82,
                        method="js_pattern",
                        discriminator=index,
                    )
                )

        definitions: tuple[tuple[re.Pattern[str], str], ...] = (
            (_JS_NAMED_RE, "function"),
            (_JS_ARROW_RE, "function"),
            (_JS_TYPE_RE, "type"),
        )
        for pattern, default_kind in definitions:
            for match in pattern.finditer(file.text):
                start = line_at_offset(file.text, match.start())
                end = _brace_block_end(file.text, match.end(), start)
                name = match.group("name")
                kind_match = match.groupdict().get("kind")
                kind = kind_match or default_kind
                parent = containing_symbol(symbols, start)
                qualified = f"{parent.qualified_name}.{name}" if parent else name
                qualified = _unique_qualified(symbols, qualified, kind, start)
                symbol = make_symbol(
                    file,
                    name=name,
                    qualified_name=qualified,
                    kind=kind,
                    line_start=start,
                    line_end=end,
                    signature=_line_signature(file.text, match.start()),
                    parent_id=parent.id if parent else None,
                    role=_role_for_name(name, file.path),
                )
                symbols.append(symbol)
                if _is_exported_declaration(match.group(0)):
                    edges.append(_export_edge(file, symbol, start, "js_pattern"))
                if parent:
                    edges.append(
                        make_edge(
                            file,
                            relation="contains",
                            source_symbol_id=parent.id,
                            target_symbol_id=symbol.id,
                            target_name=qualified,
                            evidence_line=start,
                            confidence=0.9,
                            method="js_pattern",
                            unresolved=False,
                        )
                    )
                inherited = match.groupdict().get("extends") or ""
                for index, target in enumerate(_split_names(inherited)):
                    edges.append(
                        make_edge(
                            file,
                            relation="extends",
                            source_symbol_id=symbol.id,
                            target_name=target,
                            evidence_line=start,
                            confidence=0.78,
                            method="js_pattern",
                            discriminator=index,
                        )
                    )

        for match in _JS_VARIABLE_RE.finditer(file.text):
            if "=>" in match.group("value") or re.match(
                r"\s*(?:async\s+)?function\b",
                match.group("value"),
            ):
                continue
            start = line_at_offset(file.text, match.start())
            name = match.group("name")
            kind = "constant" if match.group("kind") == "const" else "variable"
            qualified = _unique_qualified(symbols, name, kind, start)
            symbol = make_symbol(
                file,
                name=name,
                qualified_name=qualified,
                kind=kind,
                line_start=start,
                line_end=start,
                signature=_line_signature(file.text, match.start()),
                role=_role_for_name(name, file.path),
            )
            symbols.append(symbol)
            if match.group("export"):
                edges.append(_export_edge(file, symbol, start, "js_pattern"))

        for match in _JS_IMPORT_RE.finditer(file.text):
            target = match.group("module") or match.group("require")
            if target:
                edges.append(
                    make_edge(
                        file,
                        relation="imports",
                        target_name=target,
                        evidence_line=line_at_offset(file.text, match.start()),
                        confidence=0.95,
                        method="js_pattern",
                        discriminator=match.start(),
                    )
                )
        for match in _JS_EXPORT_FROM_RE.finditer(file.text):
            edges.append(
                make_edge(
                    file,
                    relation="exports",
                    target_name=match.group("module"),
                    evidence_line=line_at_offset(file.text, match.start()),
                    confidence=0.95,
                    method="js_pattern",
                    discriminator=match.start(),
                )
            )
        for match in _JS_CALL_RE.finditer(_mask_js_comments_and_strings(file.text)):
            target = match.group("name").replace("?.", ".")
            if target in _JS_CALL_EXCLUSIONS or _looks_like_declaration(
                file.text, match.start()
            ):
                continue
            line = line_at_offset(file.text, match.start())
            source = containing_symbol(symbols, line)
            edges.append(
                make_edge(
                    file,
                    relation="calls",
                    source_symbol_id=source.id if source else None,
                    target_name=target,
                    evidence_line=line,
                    confidence=0.55 if "." not in target else 0.65,
                    method="js_pattern",
                    discriminator=match.start(),
                )
            )

        return ExtractionResult(
            chunks=chunks,
            symbols=tuple(_sorted_symbols(symbols)),
            edges=deduplicate_edges(edges),
            diagnostics=tuple(diagnostics),
            parse_state="parsed" if not diagnostics else "lexical",
        )


_SQL_CREATE_RE = re.compile(
    r"(?is)\bCREATE\s+(?:OR\s+REPLACE\s+)?"
    r"(?P<kind>TABLE|VIEW|MATERIALIZED\s+VIEW|FUNCTION|PROCEDURE|INDEX)"
    r"\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[`\"\[\]\w.]+)"
)
_SQL_ALTER_RE = re.compile(
    r"(?is)\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?P<name>[`\"\[\]\w.]+)"
)
_SQL_READ_RE = re.compile(r"(?is)\b(?:FROM|JOIN)\s+(?P<name>[`\"\[\]\w.]+)")
_SQL_WRITE_RE = re.compile(
    r"(?is)\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO)"
    r"\s+(?P<name>[`\"\[\]\w.]+)"
)
_SQL_REFERENCE_RE = re.compile(
    r"(?is)\bREFERENCES\s+(?P<name>[`\"\[\]\w.]+)"
)


class SqlExtractor:
    def __init__(self, *, max_chunk_lines: int, max_chunk_chars: int) -> None:
        self._max_chunk_lines = max_chunk_lines
        self._max_chunk_chars = max_chunk_chars

    def extract(self, file: FileRecord) -> ExtractionResult:
        statements = _sql_statements(file.text)
        spans = [
            (start, end, "sql_statement", _sql_heading(statement))
            for start, end, statement in statements
        ]
        chunks = chunks_for_spans(
            file,
            spans or [(1, max(1, file.line_count), "sql", None)],
            max_lines=self._max_chunk_lines,
            max_chars=self._max_chunk_chars,
        )
        symbols: list[CodeSymbol] = []
        edges: list[CodeEdge] = []
        for match in _SQL_CREATE_RE.finditer(file.text):
            name = _clean_sql_name(match.group("name"))
            kind = match.group("kind").lower().replace(" ", "_")
            line = line_at_offset(file.text, match.start())
            symbol = make_symbol(
                file,
                name=name.rsplit(".", 1)[-1],
                qualified_name=_unique_qualified(symbols, name, kind, line),
                kind=kind,
                line_start=line,
                line_end=_statement_end_line(file.text, match.end()),
                signature=_line_signature(file.text, match.start()),
            )
            symbols.append(symbol)
            edges.append(
                make_edge(
                    file,
                    relation=f"declares_{kind}",
                    source_symbol_id=symbol.id,
                    target_symbol_id=symbol.id,
                    target_name=name,
                    evidence_line=line,
                    confidence=0.96,
                    method="sql_pattern",
                    unresolved=False,
                )
            )
        _append_sql_edges(
            file,
            edges,
            symbols,
            _SQL_ALTER_RE,
            relation="alters_table",
            confidence=0.94,
        )
        _append_sql_edges(
            file,
            edges,
            symbols,
            _SQL_READ_RE,
            relation="reads_table",
            confidence=0.72,
        )
        _append_sql_edges(
            file,
            edges,
            symbols,
            _SQL_WRITE_RE,
            relation="writes_table",
            confidence=0.85,
        )
        _append_sql_edges(
            file,
            edges,
            symbols,
            _SQL_REFERENCE_RE,
            relation="references",
            confidence=0.9,
        )
        diagnostics: list[Diagnostic] = []
        if _sql_unterminated(file.text):
            diagnostics.append(
                Diagnostic(
                    code="sql_unterminated_literal_or_comment",
                    message="SQL contains an unterminated quoted literal or block comment",
                    path=file.path,
                )
            )
        return ExtractionResult(
            chunks=chunks,
            symbols=tuple(_sorted_symbols(symbols)),
            edges=deduplicate_edges(edges),
            diagnostics=tuple(diagnostics),
            parse_state="parsed" if not diagnostics else "lexical",
        )


_JAVA_TYPE_RE = re.compile(
    r"(?m)^[ \t]*(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed)"
    r"[ \t]+)*"
    r"(?P<kind>class|interface|enum|record)\s+(?P<name>[A-Za-z_$][\w$]*)"
    r"(?:\s+extends\s+(?P<extends>[A-Za-z_$][\w$., <>?]*?))?"
    r"(?:\s+implements\s+(?P<implements>[A-Za-z_$][\w$., <>?]*?))?"
    r"(?=\s*\{|\s*$)"
)
_JAVA_METHOD_RE = re.compile(
    r"(?m)^[ \t]*(?:@[A-Za-z_$][\w$]*(?:\([^)]*\))?\s*)*"
    r"(?:(?:public|protected|private|abstract|final|static|synchronized|native|default)\s+)*"
    r"(?:<[^>\n]+>\s+)?(?P<return>[A-Za-z_$][\w$<>, ?.\[\]]*\s+)"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*(?P<args>\([^;{}]*\))"
    r"\s*(?:throws\s+[^{;]+)?(?P<end>[{;])"
)
_JAVA_IMPORT_RE = re.compile(
    r"(?m)^[ \t]*import\s+(?:static\s+)?(?P<name>[\w.*]+)\s*;"
)
_JAVA_PACKAGE_RE = re.compile(r"(?m)^[ \t]*package\s+(?P<name>[\w.]+)\s*;")
_JAVA_CALL_RE = re.compile(
    r"(?<![\w$])(?P<name>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\("
)
_JAVA_CALL_EXCLUSIONS = _JS_CALL_EXCLUSIONS | frozenset({"this", "synchronized"})


class JavaExtractor:
    def __init__(self, *, max_chunk_lines: int, max_chunk_chars: int) -> None:
        self._max_chunk_lines = max_chunk_lines
        self._max_chunk_chars = max_chunk_chars

    def extract(self, file: FileRecord) -> ExtractionResult:
        chunks = bounded_chunks(
            file,
            max_lines=self._max_chunk_lines,
            max_chars=self._max_chunk_chars,
            kind="code",
        )
        symbols: list[CodeSymbol] = []
        edges: list[CodeEdge] = []
        declaration_offsets: set[int] = set()
        diagnostics = _brace_diagnostics(file, method="java_pattern")
        package = _JAVA_PACKAGE_RE.search(file.text)
        package_name = package.group("name") if package else ""

        for match in _JAVA_TYPE_RE.finditer(file.text):
            line = line_at_offset(file.text, match.start())
            end = _brace_block_end(file.text, match.end(), line)
            name = match.group("name")
            qualified = f"{package_name}.{name}" if package_name else name
            symbol = make_symbol(
                file,
                name=name,
                qualified_name=qualified,
                kind=match.group("kind"),
                line_start=line,
                line_end=end,
                signature=_line_signature(file.text, match.start()),
                role=_role_for_name(name, file.path),
            )
            symbols.append(symbol)
            for relation, raw, confidence in (
                ("extends", match.group("extends"), 0.85),
                ("implements", match.group("implements"), 0.84),
            ):
                for index, target in enumerate(_split_names(raw or "")):
                    edges.append(
                        make_edge(
                            file,
                            relation=relation,
                            source_symbol_id=symbol.id,
                            target_name=target,
                            evidence_line=line,
                            confidence=confidence,
                            method="java_pattern",
                            discriminator=index,
                        )
                    )

        for match in _JAVA_METHOD_RE.finditer(file.text):
            name = match.group("name")
            if name in {"if", "for", "while", "switch", "catch"}:
                continue
            line = line_at_offset(file.text, match.start())
            parent = containing_symbol(symbols, line)
            if not parent:
                continue
            declaration_offsets.add(match.start("name"))
            end = (
                _brace_block_end(file.text, match.start(), line)
                if match.group("end") == "{"
                else line
            )
            args = " ".join(match.group("args").split())
            qualified = f"{parent.qualified_name}.{name}{args}"
            qualified = _unique_qualified(symbols, qualified, "method", line)
            method_kind = (
                "constructor"
                if match.group("return").strip()
                in {
                    "public",
                    "protected",
                    "private",
                }
                and name == parent.name
                else "method"
            )
            symbol = make_symbol(
                file,
                name=name,
                qualified_name=qualified,
                kind=method_kind,
                line_start=line,
                line_end=min(end, parent.line_end),
                signature=_line_signature(file.text, match.start()),
                parent_id=parent.id,
                role=_role_for_name(name, file.path),
            )
            symbols.append(symbol)
            edges.append(
                make_edge(
                    file,
                    relation="contains",
                    source_symbol_id=parent.id,
                    target_symbol_id=symbol.id,
                    target_name=qualified,
                    evidence_line=line,
                    confidence=0.9,
                    method="java_pattern",
                    unresolved=False,
                )
            )
        for match in _JAVA_IMPORT_RE.finditer(file.text):
            edges.append(
                make_edge(
                    file,
                    relation="imports",
                    target_name=match.group("name"),
                    evidence_line=line_at_offset(file.text, match.start()),
                    confidence=1.0,
                    method="java_pattern",
                    discriminator=match.start(),
                )
            )
        masked = _mask_js_comments_and_strings(file.text)
        for match in _JAVA_CALL_RE.finditer(masked):
            target = match.group("name")
            if (
                match.start("name") in declaration_offsets
                or target in _JAVA_CALL_EXCLUSIONS
                or _looks_like_declaration(
                    file.text,
                    match.start(),
                )
            ):
                continue
            line = line_at_offset(file.text, match.start())
            source = containing_symbol(symbols, line)
            edges.append(
                make_edge(
                    file,
                    relation="calls",
                    source_symbol_id=source.id if source else None,
                    target_name=target,
                    evidence_line=line,
                    confidence=0.58 if "." not in target else 0.67,
                    method="java_pattern",
                    discriminator=match.start(),
                )
            )
        return ExtractionResult(
            chunks=chunks,
            symbols=tuple(_sorted_symbols(symbols)),
            edges=deduplicate_edges(edges),
            diagnostics=tuple(diagnostics),
            parse_state="parsed" if not diagnostics else "lexical",
        )


_MD_HEADING_RE = re.compile(r"(?m)^(?P<marks>#{1,6})[ \t]+(?P<name>.+?)\s*$")
_MD_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\((?P<target>[^)\s]+)(?:\s+[^)]*)?\)")


class StructuralTextExtractor:
    def __init__(self, *, max_chunk_lines: int, max_chunk_chars: int) -> None:
        self._max_chunk_lines = max_chunk_lines
        self._max_chunk_chars = max_chunk_chars

    def extract(self, file: FileRecord) -> ExtractionResult:
        language = file.language.lower()
        if language in {"markdown", "md", "mdx"}:
            return self._markdown(file)
        if language in {"json", "jsonc"}:
            return self._json(file, allow_comments=language == "jsonc")
        if language in {"toml"}:
            return self._toml(file)
        if language in {"yaml", "yml"}:
            return self._line_keys(file, r"^(?P<indent>\s*)(?P<name>[\w.-]+)\s*:")
        if language in {"shell", "bash", "sh", "zsh"}:
            return self._shell(file)
        if language in {"css", "scss", "less"}:
            return self._css(file)
        return ExtractionResult(
            chunks=bounded_chunks(
                file,
                max_lines=self._max_chunk_lines,
                max_chars=self._max_chunk_chars,
                kind="text",
            ),
            parse_state="lexical",
        )

    def _markdown(self, file: FileRecord) -> ExtractionResult:
        headings = list(_MD_HEADING_RE.finditer(file.text))
        symbols: list[CodeSymbol] = []
        spans: list[tuple[int, int, str, str | None]] = []
        total_lines = max(1, len(file.text.splitlines()))
        for index, match in enumerate(headings):
            start = line_at_offset(file.text, match.start())
            end = (
                line_at_offset(file.text, headings[index + 1].start()) - 1
                if index + 1 < len(headings)
                else total_lines
            )
            name = match.group("name").strip().rstrip("#").strip()
            qualified = _unique_qualified(
                symbols,
                _markdown_slug(name),
                "heading",
                start,
            )
            symbols.append(
                make_symbol(
                    file,
                    name=name,
                    qualified_name=qualified,
                    kind="heading",
                    line_start=start,
                    line_end=end,
                    signature=f"{match.group('marks')} {name}",
                )
            )
            spans.append((start, end, "section", name))
        chunks = (
            chunks_for_spans(
                file,
                spans,
                max_lines=self._max_chunk_lines,
                max_chars=self._max_chunk_chars,
            )
            if spans
            else bounded_chunks(
                file,
                max_lines=self._max_chunk_lines,
                max_chars=self._max_chunk_chars,
                kind="markdown",
            )
        )
        edges = [
            make_edge(
                file,
                relation="references",
                target_name=match.group("target"),
                evidence_line=line_at_offset(file.text, match.start()),
                confidence=0.95,
                method="markdown_pattern",
                discriminator=match.start(),
            )
            for match in _MD_LINK_RE.finditer(file.text)
        ]
        return ExtractionResult(
            chunks=chunks,
            symbols=tuple(symbols),
            edges=deduplicate_edges(edges),
            parse_state="parsed",
        )

    def _json(self, file: FileRecord, *, allow_comments: bool) -> ExtractionResult:
        # JSON-with-comments is common even in files ending in ``.json``
        # (notably tsconfig). Accept comments and trailing commas for navigation,
        # while still diagnosing genuinely malformed content.
        del allow_comments
        source = _remove_json_trailing_commas(
            _strip_json_comments(file.text.lstrip("\ufeff"))
        )
        diagnostics: list[Diagnostic] = []
        symbols: list[CodeSymbol] = []
        try:
            value = json.loads(source)
            for path, scalar in _walk_config(value):
                symbols.append(
                    make_symbol(
                        file,
                        name=path.rsplit(".", 1)[-1],
                        qualified_name=path,
                        kind="config_key",
                        line_start=_find_key_line(file.text, path.rsplit(".", 1)[-1]),
                        line_end=_find_key_line(file.text, path.rsplit(".", 1)[-1]),
                        signature=f"{path} = {_short_value(scalar)}",
                    )
                )
        except json.JSONDecodeError as exc:
            diagnostics.append(
                Diagnostic(
                    code="json_parse_failed",
                    message=exc.msg,
                    path=file.path,
                    details={"line": exc.lineno, "column": exc.colno},
                )
            )
        return ExtractionResult(
            chunks=bounded_chunks(
                file,
                max_lines=self._max_chunk_lines,
                max_chars=self._max_chunk_chars,
                kind="config",
            ),
            symbols=tuple(_sorted_symbols(symbols)),
            diagnostics=tuple(diagnostics),
            parse_state="parsed" if not diagnostics else "lexical",
        )

    def _toml(self, file: FileRecord) -> ExtractionResult:
        diagnostics: list[Diagnostic] = []
        symbols: list[CodeSymbol] = []
        try:
            value = tomllib.loads(file.text)
            for path, scalar in _walk_config(value):
                line = _find_key_line(file.text, path.rsplit(".", 1)[-1])
                symbols.append(
                    make_symbol(
                        file,
                        name=path.rsplit(".", 1)[-1],
                        qualified_name=path,
                        kind="config_key",
                        line_start=line,
                        line_end=line,
                        signature=f"{path} = {_short_value(scalar)}",
                    )
                )
        except tomllib.TOMLDecodeError as exc:
            diagnostics.append(
                Diagnostic(
                    code="toml_parse_failed",
                    message=str(exc),
                    path=file.path,
                )
            )
        return ExtractionResult(
            chunks=bounded_chunks(
                file,
                max_lines=self._max_chunk_lines,
                max_chars=self._max_chunk_chars,
                kind="config",
            ),
            symbols=tuple(_sorted_symbols(symbols)),
            diagnostics=tuple(diagnostics),
            parse_state="parsed" if not diagnostics else "lexical",
        )

    def _line_keys(self, file: FileRecord, pattern: str) -> ExtractionResult:
        regex = re.compile(pattern)
        symbols: list[CodeSymbol] = []
        scopes: list[tuple[int, str]] = []
        for line_number, line in enumerate(file.text.splitlines(), start=1):
            match = regex.match(line)
            if not match:
                continue
            indent = len(match.group("indent").replace("\t", "  "))
            while scopes and scopes[-1][0] >= indent:
                scopes.pop()
            name = match.group("name")
            qualified = ".".join([*(item[1] for item in scopes), name])
            qualified = _unique_qualified(
                symbols,
                qualified,
                "config_key",
                line_number,
            )
            symbols.append(
                make_symbol(
                    file,
                    name=name,
                    qualified_name=qualified,
                    kind="config_key",
                    line_start=line_number,
                    line_end=line_number,
                    signature=line.strip(),
                )
            )
            scopes.append((indent, name))
        return ExtractionResult(
            chunks=bounded_chunks(
                file,
                max_lines=self._max_chunk_lines,
                max_chars=self._max_chunk_chars,
                kind="config",
            ),
            symbols=tuple(symbols),
            parse_state="parsed",
        )

    def _shell(self, file: FileRecord) -> ExtractionResult:
        function_re = re.compile(
            r"(?m)^[ \t]*(?:function\s+)?(?P<name>[A-Za-z_][\w]*)"
            r"(?:\s*\(\s*\))?\s*\{"
        )
        source_re = re.compile(
            r"(?m)^[ \t]*(?:source|\.)\s+[\"']?(?P<name>[^\"'\s;]+)"
        )
        symbols: list[CodeSymbol] = []
        edges: list[CodeEdge] = []
        for match in function_re.finditer(file.text):
            line = line_at_offset(file.text, match.start())
            qualified = _unique_qualified(
                symbols,
                match.group("name"),
                "function",
                line,
            )
            symbols.append(
                make_symbol(
                    file,
                    name=match.group("name"),
                    qualified_name=qualified,
                    kind="function",
                    line_start=line,
                    line_end=_brace_block_end(file.text, match.end(), line),
                    signature=_line_signature(file.text, match.start()),
                )
            )
        for match in source_re.finditer(file.text):
            edges.append(
                make_edge(
                    file,
                    relation="imports",
                    target_name=match.group("name"),
                    evidence_line=line_at_offset(file.text, match.start()),
                    confidence=0.95,
                    method="shell_pattern",
                    discriminator=match.start(),
                )
            )
        return ExtractionResult(
            chunks=bounded_chunks(
                file,
                max_lines=self._max_chunk_lines,
                max_chars=self._max_chunk_chars,
                kind="shell",
            ),
            symbols=tuple(symbols),
            edges=deduplicate_edges(edges),
            parse_state="parsed",
        )

    def _css(self, file: FileRecord) -> ExtractionResult:
        selector_re = re.compile(r"(?m)^(?P<name>[^@{}\n][^{}\n]*)\s*\{")
        symbols: list[CodeSymbol] = []
        for match in selector_re.finditer(file.text):
            name = match.group("name").strip()
            line = line_at_offset(file.text, match.start())
            qualified = _unique_qualified(symbols, name, "selector", line)
            symbols.append(
                make_symbol(
                    file,
                    name=name,
                    qualified_name=qualified,
                    kind="selector",
                    line_start=line,
                    line_end=_brace_block_end(file.text, match.end(), line),
                    signature=name,
                )
            )
        diagnostics = _brace_diagnostics(file, method="css_pattern")
        return ExtractionResult(
            chunks=bounded_chunks(
                file,
                max_lines=self._max_chunk_lines,
                max_chars=self._max_chunk_chars,
                kind="stylesheet",
            ),
            symbols=tuple(symbols),
            diagnostics=tuple(diagnostics),
            parse_state="parsed" if not diagnostics else "lexical",
        )


def _append_sql_edges(
    file: FileRecord,
    edges: list[CodeEdge],
    symbols: list[CodeSymbol],
    pattern: re.Pattern[str],
    *,
    relation: str,
    confidence: float,
) -> None:
    for match in pattern.finditer(file.text):
        line = line_at_offset(file.text, match.start())
        source = containing_symbol(symbols, line)
        edges.append(
            make_edge(
                file,
                relation=relation,
                source_symbol_id=source.id if source else None,
                target_name=_clean_sql_name(match.group("name")),
                evidence_line=line,
                confidence=confidence,
                method="sql_pattern",
                discriminator=match.start(),
            )
        )


def _export_edge(
    file: FileRecord,
    symbol: CodeSymbol,
    line: int,
    method: str,
) -> CodeEdge:
    return make_edge(
        file,
        relation="exports",
        source_symbol_id=symbol.id,
        target_symbol_id=symbol.id,
        target_name=symbol.qualified_name,
        evidence_line=line,
        confidence=1.0,
        method=method,
        unresolved=False,
    )


def _is_exported_declaration(value: str) -> bool:
    return bool(re.match(r"\s*export\b", value))


def _sql_statements(text: str) -> list[tuple[int, int, str]]:
    statements: list[tuple[int, int, str]] = []
    start = 0
    quote: str | None = None
    block_comment = False
    line_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        pair = text[index : index + 2]
        if line_comment:
            if char == "\n":
                line_comment = False
        elif block_comment:
            if pair == "*/":
                block_comment = False
                index += 1
        elif quote:
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif pair == "--":
            line_comment = True
            index += 1
        elif pair == "/*":
            block_comment = True
            index += 1
        elif char in {"'", '"', "`"}:
            quote = char
        elif char == ";":
            content = text[start : index + 1]
            if content.strip():
                statements.append(
                    (
                        line_at_offset(text, start),
                        line_at_offset(text, index),
                        content,
                    )
                )
            start = index + 1
        index += 1
    tail = text[start:]
    if tail.strip():
        statements.append(
            (line_at_offset(text, start), max(1, len(text.splitlines())), tail)
        )
    return statements


def _sql_heading(statement: str) -> str | None:
    match = re.search(
        r"(?is)\b(CREATE|ALTER|INSERT|UPDATE|DELETE|SELECT|DROP)\b"
        r"(?:\s+\w+)?\s+([`\"\[\]\w.]+)?",
        statement,
    )
    if not match:
        return None
    return " ".join(part for part in match.groups() if part).upper()


def _sql_unterminated(text: str) -> bool:
    single = False
    block = False
    index = 0
    while index < len(text):
        pair = text[index : index + 2]
        if block:
            if pair == "*/":
                block = False
                index += 1
        elif not single and pair == "/*":
            block = True
            index += 1
        elif not block and text[index] == "'":
            if single and index + 1 < len(text) and text[index + 1] == "'":
                index += 1
            else:
                single = not single
        index += 1
    return single or block


def _brace_diagnostics(file: FileRecord, *, method: str) -> list[Diagnostic]:
    masked = _mask_js_comments_and_strings(file.text)
    balance = 0
    first_extra_close: int | None = None
    for offset, char in enumerate(masked):
        if char == "{":
            balance += 1
        elif char == "}":
            balance -= 1
            if balance < 0 and first_extra_close is None:
                first_extra_close = line_at_offset(file.text, offset)
    if balance == 0 and first_extra_close is None:
        return []
    return [
        Diagnostic(
            code="unbalanced_braces",
            message=f"{method} found unbalanced braces",
            path=file.path,
            details={
                "balance": balance,
                "first_extra_close_line": first_extra_close,
            },
        )
    ]


def _brace_block_end(text: str, after_match: int, fallback_line: int) -> int:
    masked = _mask_js_comments_and_strings(text)
    opening = masked.find("{", after_match)
    if opening < 0:
        return fallback_line
    depth = 0
    for offset in range(opening, len(masked)):
        if masked[offset] == "{":
            depth += 1
        elif masked[offset] == "}":
            depth -= 1
            if depth == 0:
                return line_at_offset(text, offset)
    return max(fallback_line, len(text.splitlines()))


def _mask_js_comments_and_strings(text: str) -> str:
    """Preserve line/offset positions while masking comments and strings."""

    pattern = re.compile(
        r"//[^\n]*|/\*[\s\S]*?\*/|`(?:\\.|[^`\\])*`|"
        r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    )
    return pattern.sub(
        lambda match: "".join("\n" if char == "\n" else " " for char in match.group()),
        text,
    )


def _looks_like_declaration(text: str, offset: int) -> bool:
    line_start = text.rfind("\n", 0, offset) + 1
    prefix = text[line_start:offset]
    return bool(
        re.search(
            r"\b(?:function|class|interface|type|enum|record|new)\s+$", prefix
        )
    )


def _line_signature(text: str, offset: int) -> str:
    end = text.find("\n", offset)
    if end < 0:
        end = len(text)
    return " ".join(text[offset:end].strip().split())[:500]


def _split_names(value: str) -> list[str]:
    result: list[str] = []
    for item in value.split(","):
        cleaned = re.sub(r"<.*>", "", item).strip()
        if cleaned:
            result.append(cleaned)
    return result


def _sorted_symbols(symbols: Iterable[CodeSymbol]) -> list[CodeSymbol]:
    return sorted(
        symbols,
        key=lambda symbol: (
            symbol.line_start,
            symbol.line_end,
            symbol.qualified_name,
            symbol.kind,
        ),
    )


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


def _role_for_name(name: str, path: str) -> str | None:
    lowered = path.lower().split("/")
    if (
        name.lower().startswith("test")
        or any(part in {"test", "tests", "__tests__"} for part in lowered)
        or ".test." in path.lower()
        or ".spec." in path.lower()
    ):
        return "test"
    return None


def _clean_sql_name(value: str) -> str:
    return value.strip().strip("`\"[]").lower()


def _statement_end_line(text: str, offset: int) -> int:
    end = text.find(";", offset)
    return line_at_offset(text, end if end >= 0 else len(text))


def _markdown_slug(value: str) -> str:
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-")


def _strip_json_comments(value: str) -> str:
    result = list(value)
    quote = False
    escaped = False
    index = 0
    while index < len(value):
        char = value[index]
        pair = value[index : index + 2]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            index += 1
            continue
        if char == '"':
            quote = True
            index += 1
            continue
        if pair == "//":
            end = value.find("\n", index)
            end = len(value) if end < 0 else end
            for offset in range(index, end):
                result[offset] = " "
            index = end
            continue
        if pair == "/*":
            end = value.find("*/", index + 2)
            end = len(value) - 2 if end < 0 else end
            for offset in range(index, min(len(value), end + 2)):
                if result[offset] != "\n":
                    result[offset] = " "
            index = end + 2
            continue
        index += 1
    return "".join(result)


def _remove_json_trailing_commas(value: str) -> str:
    result = list(value)
    quote = False
    escaped = False
    index = 0
    while index < len(value):
        char = value[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            index += 1
            continue
        if char == '"':
            quote = True
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(value) and value[lookahead].isspace():
                lookahead += 1
            if lookahead < len(value) and value[lookahead] in {"}", "]"}:
                result[index] = " "
        index += 1
    return "".join(result)


def _walk_config(value: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key in sorted(value):
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path, value[key]
            yield from _walk_config(value[key], path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]"
            yield from _walk_config(item, path)


def _find_key_line(text: str, name: str) -> int:
    match = re.search(rf"(?m)^[^\n]*[\"']?{re.escape(name)}[\"']?\s*[:=]", text)
    return line_at_offset(text, match.start()) if match else 1


def _short_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return type(value).__name__
    rendered = repr(value)
    return rendered[:120]

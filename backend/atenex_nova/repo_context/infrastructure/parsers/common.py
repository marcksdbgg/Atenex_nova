"""Shared, dependency-free helpers for repository language extractors."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence

from atenex_nova.repo_context.domain.models import (
    CodeChunk,
    CodeEdge,
    CodeSymbol,
    FileRecord,
)

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def stable_id(kind: str, *parts: object) -> str:
    """Return a deterministic, namespaced identifier.

    A Repo Context database belongs to one repository, so a repository id is
    deliberately not part of parser inputs. Path, qualified name and kind make
    symbol ids stable across generations while keeping the domain independent
    from persistence.
    """

    digest = hashlib.sha256()
    digest.update(b"atenex-repo-context-v1\0")
    digest.update(kind.encode("utf-8", errors="replace"))
    for part in parts:
        digest.update(b"\0")
        digest.update(str(part).encode("utf-8", errors="replace"))
    return f"{kind}_{digest.hexdigest()}"


def line_at_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def bounded_chunks(
    file: FileRecord,
    *,
    max_lines: int,
    max_chars: int,
    kind: str = "text",
    heading: str | None = None,
) -> tuple[CodeChunk, ...]:
    """Split source into deterministic chunks that satisfy both hard bounds."""

    if not file.text:
        return ()
    lines = file.text.splitlines(keepends=True)
    chunks: list[CodeChunk] = []
    start = 0
    while start < len(lines):
        end = start
        char_count = 0
        while end < len(lines) and end - start < max_lines:
            candidate_size = len(lines[end])
            if end > start and char_count + candidate_size > max_chars:
                break
            if candidate_size > max_chars and end == start:
                # A single physical line can exceed the configured character
                # bound. Split it without inventing line numbers.
                raw = lines[end]
                for offset in range(0, len(raw), max_chars):
                    content = raw[offset : offset + max_chars]
                    chunks.append(
                        _chunk(
                            file,
                            start + 1,
                            start + 1,
                            content,
                            kind=kind,
                            heading=heading,
                            discriminator=offset,
                        )
                    )
                end += 1
                char_count = 0
                break
            char_count += candidate_size
            end += 1
        if end == start:
            end += 1
        content = "".join(lines[start:end])
        if content:
            chunks.append(
                _chunk(
                    file,
                    start + 1,
                    end,
                    content,
                    kind=kind,
                    heading=heading,
                )
            )
        start = end
    return tuple(chunks)


def chunks_for_spans(
    file: FileRecord,
    spans: Sequence[tuple[int, int, str, str | None]],
    *,
    max_lines: int,
    max_chars: int,
) -> tuple[CodeChunk, ...]:
    """Create bounded chunks for non-overlapping one-based source spans."""

    lines = file.text.splitlines(keepends=True)
    result: list[CodeChunk] = []
    for line_start, line_end, kind, heading in spans:
        start = max(1, line_start)
        end = min(max(start, line_end), len(lines))
        fragment = FileRecord(
            path=file.path,
            language=file.language,
            content_hash=file.content_hash,
            size=0,
            git_status=file.git_status,
            text="".join(lines[start - 1 : end]),
            line_count=end - start + 1,
        )
        for chunk in bounded_chunks(
            fragment,
            max_lines=max_lines,
            max_chars=max_chars,
            kind=kind,
            heading=heading,
        ):
            actual_start = start + chunk.line_start - 1
            actual_end = start + chunk.line_end - 1
            result.append(
                CodeChunk(
                    id=stable_id(
                        "chunk",
                        file.path,
                        actual_start,
                        actual_end,
                        kind,
                        chunk.content,
                    ),
                    file_path=file.path,
                    language=file.language,
                    line_start=actual_start,
                    line_end=actual_end,
                    content=chunk.content,
                    kind=kind,
                    heading=heading,
                )
            )
    return tuple(result)


def make_symbol(
    file: FileRecord,
    *,
    name: str,
    qualified_name: str,
    kind: str,
    line_start: int,
    line_end: int,
    signature: str = "",
    parent_id: str | None = None,
    role: str | None = None,
) -> CodeSymbol:
    return CodeSymbol(
        id=stable_id("symbol", file.path, qualified_name, kind),
        file_path=file.path,
        language=file.language,
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        line_start=max(1, line_start),
        line_end=max(line_start, line_end),
        signature=signature.strip(),
        parent_id=parent_id,
        role=role,
    )


def make_edge(
    file: FileRecord,
    *,
    relation: str,
    target_name: str,
    evidence_line: int,
    method: str,
    source_symbol_id: str | None = None,
    source_path: str | None = None,
    target_symbol_id: str | None = None,
    confidence: float = 0.7,
    unresolved: bool = True,
    discriminator: object = "",
) -> CodeEdge:
    return CodeEdge(
        id=stable_id(
            "edge",
            file.path,
            relation,
            source_symbol_id or "",
            target_symbol_id or target_name,
            evidence_line,
            discriminator,
        ),
        relation=relation,
        source_symbol_id=source_symbol_id,
        source_path=source_path or file.path,
        target_symbol_id=target_symbol_id,
        target_name=target_name,
        evidence_line=max(1, evidence_line),
        confidence=max(0.0, min(1.0, confidence)),
        method=method,
        unresolved=unresolved,
    )


def containing_symbol(
    symbols: Sequence[CodeSymbol],
    line: int,
) -> CodeSymbol | None:
    candidates = [
        symbol
        for symbol in symbols
        if symbol.line_start <= line <= symbol.line_end
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda symbol: (
            symbol.line_end - symbol.line_start,
            -symbol.line_start,
            symbol.qualified_name,
        ),
    )


def qualified_call_name(node: object) -> str | None:
    """Read a dotted name from Python ``ast.Name``/``ast.Attribute`` nodes."""

    name = getattr(node, "id", None)
    if isinstance(name, str):
        return name
    attribute = getattr(node, "attr", None)
    value = getattr(node, "value", None)
    if isinstance(attribute, str) and value is not None:
        prefix = qualified_call_name(value)
        return f"{prefix}.{attribute}" if prefix else attribute
    return None


def extract_tokens(value: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _TOKEN_RE.finditer(value))


def deduplicate_edges(edges: Iterable[CodeEdge]) -> tuple[CodeEdge, ...]:
    unique: dict[str, CodeEdge] = {}
    for edge in edges:
        unique.setdefault(edge.id, edge)
    return tuple(
        sorted(
            unique.values(),
            key=lambda edge: (
                edge.source_path,
                edge.evidence_line,
                edge.relation,
                edge.target_name,
                edge.id,
            ),
        )
    )


def _chunk(
    file: FileRecord,
    line_start: int,
    line_end: int,
    content: str,
    *,
    kind: str,
    heading: str | None,
    discriminator: object = "",
) -> CodeChunk:
    return CodeChunk(
        id=stable_id(
            "chunk",
            file.path,
            line_start,
            line_end,
            kind,
            content,
            discriminator,
        ),
        file_path=file.path,
        language=file.language,
        line_start=line_start,
        line_end=line_end,
        content=content,
        kind=kind,
        heading=heading,
    )


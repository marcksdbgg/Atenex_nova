"""Transport- and persistence-independent Repo Context models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ParseState = Literal["parsed", "lexical", "skipped", "failed"]
GenerationState = Literal["building", "complete", "active", "abandoned"]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"
    path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    repository_id: str
    root: str
    head: str | None
    branch: str | None
    dirty: bool
    worktree_fingerprint: str
    content_fingerprint: str
    schema_version: int
    parser_version: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    language: str
    content_hash: str
    size: int
    git_status: str
    text: str
    parse_state: ParseState = "lexical"
    line_count: int = 0

    def to_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        result = asdict(self)
        if not include_text:
            result.pop("text", None)
        return result


@dataclass(frozen=True, slots=True)
class CodeChunk:
    id: str
    file_path: str
    language: str
    line_start: int
    line_end: int
    content: str
    kind: str = "text"
    heading: str | None = None
    symbol_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CodeSymbol:
    id: str
    file_path: str
    language: str
    name: str
    qualified_name: str
    kind: str
    line_start: int
    line_end: int
    signature: str = ""
    parent_id: str | None = None
    role: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CodeEdge:
    id: str
    relation: str
    source_symbol_id: str | None
    source_path: str
    target_symbol_id: str | None
    target_name: str
    evidence_line: int
    confidence: float
    method: str
    unresolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    chunks: tuple[CodeChunk, ...] = ()
    symbols: tuple[CodeSymbol, ...] = ()
    edges: tuple[CodeEdge, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    parse_state: ParseState = "parsed"


@dataclass(frozen=True, slots=True)
class ScanResult:
    snapshot: RepositorySnapshot
    files: tuple[FileRecord, ...]
    diagnostics: tuple[Diagnostic, ...] = ()
    skipped: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GenerationInfo:
    id: int
    state: GenerationState
    snapshot: RepositorySnapshot
    file_count: int
    symbol_count: int
    chunk_count: int
    edge_count: int
    diagnostics_count: int
    activated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["snapshot"] = self.snapshot.to_dict()
        return data


@dataclass(frozen=True, slots=True)
class SearchHit:
    kind: Literal["chunk", "symbol", "file"]
    path: str
    line_start: int
    line_end: int
    score: float
    reason: str
    content_hash: str
    snippet: str
    symbol: CodeSymbol | None = None
    score_components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["symbol"] = self.symbol.to_dict() if self.symbol else None
        return data

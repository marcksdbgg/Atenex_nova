"""Deterministic, token-bounded repository map ranking."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from atenex_nova.repo_context.domain.models import CodeEdge, CodeSymbol, FileRecord

_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SYMBOL_WEIGHTS = {
    "class": 1.5,
    "interface": 1.45,
    "record": 1.4,
    "enum": 1.3,
    "function": 1.2,
    "method": 0.75,
    "table": 1.35,
    "view": 1.25,
    "heading": 0.45,
    "config_key": 0.18,
}


@dataclass(frozen=True, slots=True)
class RepoMapEntry:
    path: str
    score: float
    centrality: float
    focus_score: float
    symbols: tuple[CodeSymbol, ...]
    rendered: str
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class RepoMapResult:
    entries: tuple[RepoMapEntry, ...]
    rendered: str
    estimated_tokens: int
    max_tokens: int
    truncated: bool
    total_candidates: int

    def to_dict(self) -> dict[str, object]:
        return {
            "entries": [
                {
                    "path": entry.path,
                    "score": round(entry.score, 8),
                    "centrality": round(entry.centrality, 8),
                    "focus_score": round(entry.focus_score, 8),
                    "symbols": [symbol.to_dict() for symbol in entry.symbols],
                    "rendered": entry.rendered,
                    "estimated_tokens": entry.estimated_tokens,
                }
                for entry in self.entries
            ],
            "rendered": self.rendered,
            "estimated_tokens": self.estimated_tokens,
            "max_tokens": self.max_tokens,
            "truncated": self.truncated,
            "total_candidates": self.total_candidates,
        }


class RepoMapBuilder:
    """Rank repository files and render a compact map under a hard budget."""

    def build(
        self,
        symbols: Sequence[CodeSymbol],
        edges: Sequence[CodeEdge],
        *,
        files: Sequence[FileRecord | Mapping[str, object]] = (),
        focus: str | None = None,
        focus_paths: Mapping[str, float] | None = None,
        max_tokens: int = 4_000,
    ) -> RepoMapResult:
        budget = max(0, max_tokens)
        inventory = _inventory(files)
        symbols_by_path: dict[str, list[CodeSymbol]] = defaultdict(list)
        symbol_by_id: dict[str, CodeSymbol] = {}
        for symbol in symbols:
            symbols_by_path[symbol.file_path].append(symbol)
            symbol_by_id[symbol.id] = symbol

        paths = set(inventory) | set(symbols_by_path)
        paths.update(edge.source_path for edge in edges if edge.source_path)
        centrality = _page_rank(paths, edges, symbol_by_id, symbols)
        focus_terms = _terms(focus or "")
        normalized_focus_paths = _normalized_focus_paths(focus_paths or {})
        focus_weight = max(24.0, min(240.0, len(paths) * 0.3))
        raw_entries: list[RepoMapEntry] = []
        for path in sorted(paths):
            path_symbols = sorted(
                symbols_by_path.get(path, ()),
                key=_symbol_display_order,
            )
            focus_score = max(
                _focus_score(path, path_symbols, focus_terms),
                normalized_focus_paths.get(path, 0.0),
            )
            symbol_score = _bounded_symbol_score(path_symbols)
            centrality_weight = 1.5 if focus_terms else 3.0
            score = (
                1.0
                + centrality.get(path, 0.0)
                * max(1, len(paths))
                * centrality_weight
                + symbol_score
                + focus_score * focus_weight
                + _landmark_score(path)
                + _status_score(inventory.get(path, {}))
            )
            rendered, displayed_symbols = _render_entry(path, path_symbols)
            raw_entries.append(
                RepoMapEntry(
                    path=path,
                    score=score,
                    centrality=centrality.get(path, 0.0),
                    focus_score=focus_score,
                    symbols=displayed_symbols,
                    rendered=rendered,
                    estimated_tokens=estimate_tokens(rendered),
                )
            )

        selected = _select_diverse(
            raw_entries,
            budget,
            focused=bool(focus_terms or normalized_focus_paths),
        )
        rendered = "\n".join(entry.rendered for entry in selected)
        return RepoMapResult(
            entries=tuple(selected),
            rendered=rendered,
            estimated_tokens=estimate_tokens(rendered) if rendered else 0,
            max_tokens=budget,
            truncated=len(selected) < len(raw_entries),
            total_candidates=len(raw_entries),
        )


def build_repomap(
    symbols: Sequence[CodeSymbol],
    edges: Sequence[CodeEdge],
    *,
    files: Sequence[FileRecord | Mapping[str, object]] = (),
    focus: str | None = None,
    focus_paths: Mapping[str, float] | None = None,
    max_tokens: int = 4_000,
) -> RepoMapResult:
    """Functional convenience API for composition and tests."""

    return RepoMapBuilder().build(
        symbols,
        edges,
        files=files,
        focus=focus,
        focus_paths=focus_paths,
        max_tokens=max_tokens,
    )


def estimate_tokens(value: str) -> int:
    """Conservative local estimate used for deterministic output budgets."""

    if not value:
        return 0
    # Code punctuation tokenizes more densely than prose. Counting UTF-8 bytes
    # in groups of three is intentionally conservative and dependency-free.
    return max(1, math.ceil(len(value.encode("utf-8")) / 3))


def _inventory(
    files: Sequence[FileRecord | Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for file in files:
        if isinstance(file, FileRecord):
            result[file.path] = {
                "path": file.path,
                "language": file.language,
                "git_status": file.git_status,
            }
            continue
        path = str(file.get("path", ""))
        if path:
            result[path] = file
    return result


def _page_rank(
    paths: set[str],
    edges: Sequence[CodeEdge],
    symbol_by_id: Mapping[str, CodeSymbol],
    symbols: Sequence[CodeSymbol],
) -> dict[str, float]:
    if not paths:
        return {}
    by_qualified: dict[str, set[str]] = defaultdict(set)
    by_name: dict[str, set[str]] = defaultdict(set)
    for symbol in symbols:
        by_qualified[symbol.qualified_name].add(symbol.file_path)
        by_name[symbol.name].add(symbol.file_path)

    links: dict[str, set[str]] = {path: set() for path in paths}
    for edge in edges:
        source = edge.source_path
        if source not in links:
            continue
        target_path: str | None = None
        if edge.target_symbol_id and edge.target_symbol_id in symbol_by_id:
            target_path = symbol_by_id[edge.target_symbol_id].file_path
        else:
            candidates = by_qualified.get(edge.target_name, set())
            if len(candidates) != 1:
                candidates = by_name.get(edge.target_name.rsplit(".", 1)[-1], set())
            if len(candidates) == 1:
                target_path = next(iter(candidates))
        if target_path in links and target_path != source:
            links[source].add(target_path)

    ordered = sorted(paths)
    count = len(ordered)
    scores = {path: 1.0 / count for path in ordered}
    damping = 0.85
    for _ in range(30):
        dangling = sum(scores[path] for path in ordered if not links[path])
        updated = {
            path: (1.0 - damping) / count + damping * dangling / count
            for path in ordered
        }
        for source in ordered:
            targets = links[source]
            if not targets:
                continue
            contribution = damping * scores[source] / len(targets)
            for target in sorted(targets):
                updated[target] += contribution
        scores = updated
    return scores


def _focus_score(
    path: str,
    symbols: Sequence[CodeSymbol],
    focus_terms: frozenset[str],
) -> float:
    if not focus_terms:
        return 0.0
    path_terms = _terms(path)
    symbol_terms: set[str] = set()
    for symbol in symbols:
        symbol_terms.update(_terms(symbol.name))
        symbol_terms.update(_terms(symbol.qualified_name))
        symbol_terms.update(_terms(symbol.role or ""))
    path_overlap = len(focus_terms & path_terms) / len(focus_terms)
    symbol_overlap = len(focus_terms & symbol_terms) / len(focus_terms)
    exact_bonus = 0.0
    lowered_focus = " ".join(sorted(focus_terms))
    if any(
        lowered_focus == " ".join(sorted(_terms(symbol.name))) for symbol in symbols
    ):
        exact_bonus = 0.5
    return path_overlap * 0.45 + symbol_overlap * 0.75 + exact_bonus


def _terms(value: str) -> frozenset[str]:
    separated = _CAMEL_BOUNDARY_RE.sub(" ", value)
    return frozenset(match.group(0).lower() for match in _WORD_RE.finditer(separated))


def _normalized_focus_paths(values: Mapping[str, float]) -> dict[str, float]:
    positive = {path: max(0.0, float(score)) for path, score in values.items()}
    maximum = max(positive.values(), default=0.0)
    if maximum <= 0.0:
        return {}
    return {path: score / maximum for path, score in positive.items()}


def _landmark_score(path: str) -> float:
    lowered = path.lower()
    name = PurePosixPath(path).name.lower()
    score = 0.0
    if name in {
        "readme.md",
        "agents.md",
        "pyproject.toml",
        "package.json",
        "cargo.toml",
        "go.mod",
        "docker-compose.yml",
        "docker-compose.yaml",
    }:
        score += 2.2
    if name in {"main.py", "app.py", "index.ts", "index.tsx", "main.ts", "main.java"}:
        score += 1.25
    if "/tests/" in f"/{lowered}" or ".test." in lowered or ".spec." in lowered:
        score += 0.6
    if lowered.startswith("docs/"):
        score += 0.35
    return score


def _status_score(metadata: Mapping[str, object]) -> float:
    status = str(metadata.get("git_status", "")).strip()
    return 1.25 if status and status not in {"clean", " "} else 0.0


def _symbol_display_order(symbol: CodeSymbol) -> tuple[float, int, str, str]:
    role_bonus = 1.0 if symbol.role in {"entrypoint", "public", "test"} else 0.0
    weight = _SYMBOL_WEIGHTS.get(symbol.kind, 0.5) + role_bonus
    nesting = symbol.qualified_name.count(".")
    return (-weight, nesting, symbol.qualified_name, symbol.kind)


def _bounded_symbol_score(symbols: Sequence[CodeSymbol]) -> float:
    """Reward useful definitions without letting generated/config files dominate."""

    strongest = sorted(
        (_SYMBOL_WEIGHTS.get(symbol.kind, 0.5) for symbol in symbols),
        reverse=True,
    )[:8]
    definition_score = min(8.0, sum(strongest))
    density_bonus = min(1.5, math.log1p(len(symbols)) * 0.25)
    return definition_score + density_bonus


def _render_entry(
    path: str,
    symbols: Sequence[CodeSymbol],
) -> tuple[str, tuple[CodeSymbol, ...]]:
    lines = [path]
    displayed: list[CodeSymbol] = []
    # Keep per-file map entries compact. More detail remains available from
    # ``get_symbol`` and the exact source.
    for symbol in symbols[:12]:
        label = symbol.signature or f"{symbol.kind} {symbol.qualified_name}"
        label = " ".join(label.split())
        if len(label) > 180:
            label = f"{label[:177]}..."
        lines.append(f"  L{symbol.line_start} {label}")
        displayed.append(symbol)
    if len(symbols) > len(displayed):
        lines.append(f"  ... {len(symbols) - len(displayed)} more symbols")
    return "\n".join(lines), tuple(displayed)


def _select_diverse(
    entries: Sequence[RepoMapEntry],
    budget: int,
    *,
    focused: bool = False,
) -> list[RepoMapEntry]:
    if budget <= 0:
        return []
    remaining = list(entries)
    selected: list[RepoMapEntry] = []
    directory_counts: Counter[str] = Counter()
    used = 0
    while remaining:
        bucket = _focus_bucket if focused else _top_directory
        diversity_penalty = 0.1 if focused else 0.4
        candidate = min(
            remaining,
            key=lambda entry: (
                -entry.score
                / (
                    1.0
                    + diversity_penalty * directory_counts[bucket(entry.path)]
                ),
                entry.path,
            ),
        )
        remaining.remove(candidate)
        separator_tokens = estimate_tokens("\n") if selected else 0
        if used + separator_tokens + candidate.estimated_tokens > budget:
            # A path-only landmark is still useful when signatures do not fit.
            compact_text = candidate.path
            compact_tokens = estimate_tokens(compact_text)
            if used + separator_tokens + compact_tokens > budget:
                continue
            candidate = RepoMapEntry(
                path=candidate.path,
                score=candidate.score,
                centrality=candidate.centrality,
                focus_score=candidate.focus_score,
                symbols=(),
                rendered=compact_text,
                estimated_tokens=compact_tokens,
            )
        selected.append(candidate)
        used += separator_tokens + candidate.estimated_tokens
        directory_counts[bucket(candidate.path)] += 1
    return selected


def _top_directory(path: str) -> str:
    parts = PurePosixPath(path).parts
    return parts[0] if len(parts) > 1 else "."


def _focus_bucket(path: str) -> str:
    """Diversify focused maps by subsystem instead of only top-level folder."""

    parts = PurePosixPath(path).parts
    if len(parts) >= 2 and parts[0] in {"apps", "packages"}:
        depth = 5 if len(parts) >= 6 else min(4, len(parts) - 1)
        return "/".join(parts[:depth])
    return _top_directory(path)

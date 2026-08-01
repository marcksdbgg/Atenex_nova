"""Application services for indexing and querying one repository.

The services deliberately return JSON-compatible dictionaries.  This keeps the
CLI and MCP adapters thin while leaving persistence, Git, and parser details
behind domain ports.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter, deque
from collections.abc import Iterable, Sequence
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Any

from atenex_nova.repo_context.application.repomap import RepoMapBuilder
from atenex_nova.repo_context.application.semantic import OptionalSemanticCoordinator
from atenex_nova.repo_context.domain.models import (
    CodeEdge,
    CodeSymbol,
    Diagnostic,
    GenerationInfo,
    RepositorySnapshot,
    SearchHit,
)
from atenex_nova.repo_context.domain.policies import resolve_inside, safe_relative_path
from atenex_nova.repo_context.domain.ports import (
    ContextIndex,
    LanguageExtractor,
    RepositoryScanner,
)

DEFAULT_MAX_TOKENS = 4_000
MIN_TOKEN_BUDGET = 128
MAX_TOKEN_BUDGET = 32_000
ALLOWED_SEARCH_MODES = frozenset({"lexical", "symbol", "semantic"})
ALLOWED_DIRECTIONS = frozenset({"callers", "callees", "dependencies", "dependents"})
ALLOWED_RELATIONS = frozenset(
    {
        "defines",
        "references",
        "imports",
        "calls",
        "extends",
        "inherits",
        "implements",
        "contains",
        "exports",
        "tests",
        "configured_by",
        "declares_table",
        "alters_table",
        "reads_table",
        "writes_table",
    }
)
_FOCUS_QUERY_FACETS: tuple[tuple[frozenset[str], str], ...] = (
    (
        frozenset({"offline", "desconectado", "cola"}),
        "offline outbox enqueue queue pending retry sync",
    ),
    (
        frozenset({"flow", "flujo", "pipeline", "recorrido", "trace"}),
        "flow route endpoint handler service processor projector sync",
    ),
    (
        frozenset({"persistence", "persistencia", "persist", "database", "db"}),
        "persistence database repository transaction insert projector",
    ),
    (
        frozenset(
            {
                "isolation",
                "aislamiento",
                "tenant",
                "tienda",
                "store",
                "authorization",
            }
        ),
        "tenant store isolation auth authorization guard rls policy",
    ),
)


class RepoContextError(Exception):
    """Typed application error suitable for CLI and MCP adaptation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class RepoContextServices:
    """The six read-only Repo Context query services plus lifecycle inspection."""

    def __init__(
        self,
        scanner: RepositoryScanner,
        index: ContextIndex,
        extractors: Sequence[LanguageExtractor] = (),
        semantic: OptionalSemanticCoordinator | None = None,
    ) -> None:
        self._scanner = scanner
        self._index = index
        self._extractors = tuple(extractors)
        self._semantic = semantic
        self._root = scanner.root.resolve()
        self._edge_cache_generation: str | None = None
        self._edge_cache: tuple[CodeEdge, ...] = ()

    def repo_overview(
        self,
        *,
        focus: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        budget = _token_budget(max_tokens)
        generation = self._require_generation()
        inventory = sorted(
            self._index.file_inventory(), key=lambda item: str(item.get("path", ""))
        )
        language_counts = Counter(
            str(item.get("language", "unknown")) for item in inventory
        )
        directory_counts = Counter(
            _top_directory(str(item.get("path", ""))) for item in inventory
        )
        focus_hits: list[dict[str, Any]] = []
        focus_search_hits: list[SearchHit] = []
        focus_queries: tuple[str, ...] = ()
        if focus and focus.strip():
            focus_queries = _focus_queries(focus.strip())
            focus_search_hits = _fuse_focus_hits(
                [self._index.search(query, top_k=30) for query in focus_queries],
                limit=40,
            )
            focus_hits = [
                self._hit_payload(hit, include_source=True)[0]
                for hit in focus_search_hits[:20]
            ]
        focus_path_scores: dict[str, float] = {}
        for rank, hit in enumerate(focus_search_hits, start=1):
            # A task flow commonly spans several peer files. A square-root
            # decay keeps the first page authoritative without reducing the
            # sixth or seventh stage to background centrality.
            focus_path_scores.setdefault(hit.path, 1.0 / math.sqrt(rank))
        all_edges = getattr(self._index, "all_edges", None)
        repo_map = RepoMapBuilder().build(
            self._index.symbols("", limit=20_000),
            tuple(all_edges(limit=100_000)) if callable(all_edges) else (),
            files=inventory,
            focus=focus,
            focus_paths=focus_path_scores,
            max_tokens=max(128, budget // 2),
        )
        landmarks = _rank_landmark_files(inventory, limit=30)
        data: dict[str, Any] = {
            "focus": focus.strip() if focus and focus.strip() else None,
            "focus_queries": list(focus_queries),
            "summary": {
                "files": generation.file_count,
                "symbols": generation.symbol_count,
                "chunks": generation.chunk_count,
                "relations": generation.edge_count,
                "index_diagnostics": generation.diagnostics_count,
            },
            "languages": [
                {"language": language, "files": count}
                for language, count in sorted(
                    language_counts.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "principal_directories": [
                {"path": path, "files": count}
                for path, count in sorted(
                    directory_counts.items(), key=lambda item: (-item[1], item[0])
                )
            ][:20],
            "landmarks": landmarks,
            "repo_map": {
                "entries": [
                    {
                        "path": entry.path,
                        "score": round(entry.score, 8),
                        "centrality": round(entry.centrality, 8),
                        "focus_score": round(entry.focus_score, 8),
                        "evidence": _evidence(
                            entry.path,
                            1,
                            1,
                            _inventory_hash(inventory, entry.path),
                            0.8,
                            ["repomap", "symbol_rank", "focus"],
                        ),
                    }
                    for entry in repo_map.entries
                ],
                "rendered": repo_map.rendered,
                "estimated_tokens": repo_map.estimated_tokens,
                "max_tokens": repo_map.max_tokens,
                "truncated": repo_map.truncated,
                "total_candidates": repo_map.total_candidates,
            },
            "focus_results": focus_hits,
        }
        return self._envelope(
            generation,
            data,
            max_tokens=budget,
            truncated=repo_map.truncated,
            compact_list="focus_results",
        )

    def search_repo(
        self,
        query: str,
        *,
        modes: Sequence[str] | None = None,
        top_k: int = 20,
        path_prefix: str | None = None,
        languages: Sequence[str] | None = None,
        symbol_kinds: Sequence[str] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        generation = self._require_generation()
        cleaned_query = query.strip()
        if not cleaned_query:
            raise RepoContextError("INVALID_ARGUMENT", "query must not be blank")
        if not 1 <= top_k <= 200:
            raise RepoContextError(
                "INVALID_ARGUMENT", "top_k must be between 1 and 200"
            )
        budget = _token_budget(max_tokens)
        selected_modes = tuple(dict.fromkeys(modes or ("lexical", "symbol")))
        unknown_modes = sorted(set(selected_modes) - ALLOWED_SEARCH_MODES)
        if unknown_modes:
            raise RepoContextError(
                "INVALID_ARGUMENT",
                "unsupported search mode",
                details={"modes": unknown_modes},
            )
        normalized_prefix = None
        if path_prefix:
            try:
                normalized_prefix = safe_relative_path(path_prefix)
            except ValueError as exc:
                raise RepoContextError("OUTSIDE_REPOSITORY", str(exc)) from exc

        hits = self._index.search(
            cleaned_query,
            top_k=top_k,
            path_prefix=normalized_prefix,
            languages=tuple(languages or ()),
            symbol_kinds=tuple(symbol_kinds or ()),
        )
        diagnostics: list[dict[str, Any]] = []
        effective_modes = list(selected_modes)
        if "semantic" in selected_modes:
            try:
                if self._semantic is None:
                    raise RuntimeError("semantic retrieval is not configured")
                hits = self._semantic.hybrid_search(
                    query=cleaned_query,
                    generation=generation,
                    index=self._index,
                    lexical_hits=hits,
                    top_k=top_k,
                )
            except Exception as exc:
                effective_modes = [
                    mode for mode in effective_modes if mode != "semantic"
                ]
                diagnostics.append(
                    _diagnostic(
                        "SEMANTIC_UNAVAILABLE",
                        "Semantic search degraded to the deterministic core: "
                        f"{type(exc).__name__}.",
                    )
                )
        results: list[dict[str, Any]] = []
        for hit in hits:
            payload, hit_diagnostics = self._hit_payload(hit, include_source=True)
            results.append(payload)
            diagnostics.extend(hit_diagnostics)
        if not results:
            diagnostics.append(
                _diagnostic(
                    "NO_RESULTS",
                    "No indexed source matched the query after exact, all-term, "
                    "and relaxed lexical retrieval.",
                    severity="info",
                )
            )
        data = {
            "query": cleaned_query,
            "modes": effective_modes,
            "results": results,
        }
        return self._envelope(
            generation,
            data,
            max_tokens=budget,
            diagnostics=diagnostics,
            compact_list="results",
        )

    def get_symbol(
        self,
        symbol_or_path: str,
        *,
        include_source: bool = True,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        generation = self._require_generation()
        value = symbol_or_path.strip()
        if not value:
            raise RepoContextError(
                "INVALID_ARGUMENT", "symbol_or_path must not be blank"
            )
        _validate_target_value(value)
        budget = _token_budget(max_tokens)
        inventory = self._index.file_inventory()
        file_record = next(
            (item for item in inventory if str(item.get("path", "")) == value), None
        )
        if file_record is not None:
            data, diagnostics = self._file_payload(
                file_record, include_source=include_source
            )
            return self._envelope(
                generation,
                {"type": "file", **data},
                max_tokens=budget,
                diagnostics=diagnostics,
            )

        matches = self._resolve_symbol_candidates(value)
        if not matches:
            raise RepoContextError(
                "NOT_FOUND", f"symbol or path not found: {symbol_or_path}"
            )
        exact = [
            symbol
            for symbol in matches
            if symbol.qualified_name == value or symbol.name == value
        ]
        selected = exact or matches
        if len(selected) > 1:
            candidates = [
                self._symbol_payload(item, include_source=False)[0]
                for item in selected
            ]
            return self._envelope(
                generation,
                {"type": "candidates", "query": value, "candidates": candidates},
                max_tokens=budget,
                diagnostics=[
                    _diagnostic(
                        "SYMBOL_AMBIGUOUS",
                        f"{len(selected)} symbol definitions match {value!r}.",
                    )
                ],
                compact_list="candidates",
            )
        payload, diagnostics = self._symbol_payload(
            selected[0], include_source=include_source
        )
        return self._envelope(
            generation,
            {"type": "symbol", **payload},
            max_tokens=budget,
            diagnostics=diagnostics,
        )

    def trace_symbol(
        self,
        symbol: str,
        *,
        direction: str,
        depth: int = 1,
        relations: Sequence[str] | None = None,
        max_nodes: int = 50,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        generation = self._require_generation()
        root = self._resolve_unique_symbol(symbol)
        _validate_graph_bounds(direction, depth, max_nodes)
        selected_relations = tuple(dict.fromkeys(relations or ()))
        invalid_relations = sorted(set(selected_relations) - ALLOWED_RELATIONS)
        if invalid_relations:
            raise RepoContextError(
                "INVALID_ARGUMENT",
                "unsupported relation",
                details={"relations": invalid_relations},
            )
        nodes, edges, omitted_nodes, reached = self._traverse(
            root,
            direction=direction,
            depth=depth,
            relations=selected_relations,
            max_nodes=max_nodes,
        )
        diagnostics = _inferred_edge_diagnostics(edges)
        data = {
            "root": self._symbol_payload(root, include_source=False)[0],
            "nodes": [
                self._symbol_payload(item, include_source=False)[0] for item in nodes
            ],
            "edges": [self._edge_payload(item) for item in edges],
            "depth_reached": reached,
            "omitted_nodes": omitted_nodes,
            "omitted_edges": 0,
        }
        return self._envelope(
            generation,
            data,
            max_tokens=_token_budget(max_tokens),
            diagnostics=diagnostics,
            truncated=omitted_nodes > 0,
            compact_list="nodes",
        )

    def analyze_impact(
        self,
        symbol_or_path: str,
        *,
        depth: int = 2,
        max_nodes: int = 100,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        generation = self._require_generation()
        _validate_target_value(symbol_or_path.strip())
        if not 1 <= depth <= 8 or not 1 <= max_nodes <= 500:
            raise RepoContextError(
                "INVALID_ARGUMENT",
                "depth must be 1..8 and max_nodes must be 1..500",
            )
        target_symbols = self._symbols_for_target(symbol_or_path)
        if not target_symbols:
            raise RepoContextError(
                "NOT_FOUND", f"symbol or path not found: {symbol_or_path}"
            )
        all_nodes: dict[str, CodeSymbol] = {}
        all_edges: dict[str, CodeEdge] = {}
        omitted = 0
        reached = 0
        for target in target_symbols:
            remaining = max_nodes - len(all_nodes)
            if remaining <= 0:
                omitted += 1
                break
            nodes, edges, node_omitted, node_depth = self._traverse(
                target,
                direction="dependents",
                depth=depth,
                relations=(),
                max_nodes=remaining,
            )
            all_nodes.update({item.id: item for item in nodes})
            all_edges.update({item.id: item for item in edges})
            omitted += node_omitted
            reached = max(reached, node_depth)
        tests = self._related_tests_payload(symbol_or_path, top_k=20)
        affected_files = sorted(
            {item.file_path for item in all_nodes.values()}
            | {str(item["path"]) for item in tests}
        )
        data = {
            "target": {
                "query": symbol_or_path,
                "symbols": [
                    self._symbol_payload(item, include_source=False)[0]
                    for item in target_symbols
                ],
            },
            "affected_symbols": [
                self._symbol_payload(item, include_source=False)[0]
                for item in sorted(
                    all_nodes.values(),
                    key=lambda item: (item.file_path, item.line_start),
                )
            ],
            "affected_files": affected_files,
            "relations": [self._edge_payload(item) for item in all_edges.values()],
            "related_tests": tests,
            "depth_reached": reached,
            "unknowns": [
                "Static evidence does not prove runtime reachability.",
                "Dynamic dispatch and generated references may be absent.",
            ],
        }
        return self._envelope(
            generation,
            data,
            max_tokens=_token_budget(max_tokens),
            diagnostics=_inferred_edge_diagnostics(tuple(all_edges.values())),
            truncated=omitted > 0,
            compact_list="affected_symbols",
        )

    def related_tests(
        self,
        symbol_or_path: str,
        *,
        top_k: int = 20,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        generation = self._require_generation()
        _validate_target_value(symbol_or_path.strip())
        if not 1 <= top_k <= 200:
            raise RepoContextError(
                "INVALID_ARGUMENT", "top_k must be between 1 and 200"
            )
        tests = self._related_tests_payload(symbol_or_path, top_k=top_k)
        data = {
            "target": symbol_or_path,
            "results": tests,
            "coverage_note": (
                "No result means that the active static index established no relation; "
                "it does not prove that no test exists."
            ),
        }
        return self._envelope(
            generation,
            data,
            max_tokens=_token_budget(max_tokens),
            compact_list="results",
        )

    def status(self) -> dict[str, Any]:
        generation = self._index.active_generation()
        current = self._scanner.scan()
        snapshot = generation.snapshot if generation else None
        binding_ok = snapshot is not None and self._binding_matches(snapshot)
        stale = (
            generation is None
            or snapshot is None
            or not binding_ok
            or snapshot.worktree_fingerprint
            != current.snapshot.worktree_fingerprint
        )
        diagnostics = self._index.diagnostics(limit=100) if generation else []
        if generation is not None and not binding_ok:
            diagnostics.append(
                _diagnostic(
                    "REPOSITORY_BINDING_MISMATCH",
                    "The selected sidecar belongs to a different repository root.",
                    severity="error",
                )
            )
        return {
            "repo": {
                "name": self._root.name,
                "root": str(self._root),
                "repository_id": current.snapshot.repository_id,
            },
            "sidecar": str(self._index.database_path),
            "schema_version": snapshot.schema_version if snapshot else None,
            "active_generation": str(generation.id) if generation else None,
            "indexed_head": snapshot.head if snapshot else None,
            "indexed_worktree_fingerprint": (
                snapshot.worktree_fingerprint if snapshot else None
            ),
            "current_head": current.snapshot.head,
            "current_worktree_fingerprint": current.snapshot.worktree_fingerprint,
            "stale": stale,
            "core_available": generation is not None and binding_ok,
            "semantic_available": (
                self._semantic is not None
                and generation is not None
                and binding_ok
                and self._semantic.ready_for(generation)
            ),
            "counts": _generation_counts(generation),
            "diagnostics": diagnostics,
        }

    def doctor(self) -> dict[str, Any]:
        import importlib.util
        import sqlite3

        checks: list[dict[str, Any]] = []
        checks.append(
            {
                "name": "repository",
                "ok": self._root.is_dir(),
                "required": True,
                "message": str(self._root),
            }
        )
        try:
            connection = sqlite3.connect(":memory:")
            try:
                connection.execute("CREATE VIRTUAL TABLE probe USING fts5(value)")
            finally:
                connection.close()
            checks.append(
                {
                    "name": "sqlite_fts5",
                    "ok": True,
                    "required": True,
                    "message": "available",
                }
            )
        except sqlite3.Error as exc:
            checks.append(
                {
                    "name": "sqlite_fts5",
                    "ok": False,
                    "required": True,
                    "message": str(exc),
                }
            )
        try:
            generation = self._index.active_generation()
            generation_ok = (
                generation is not None and self._binding_matches(generation.snapshot)
            )
            checks.append(
                {
                    "name": "active_generation",
                    "ok": generation_ok,
                    "required": True,
                    "message": (
                        str(generation.id)
                        if generation_ok and generation is not None
                        else (
                            "sidecar belongs to another repository"
                            if generation is not None
                            else "not indexed"
                        )
                    ),
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "name": "active_generation",
                    "ok": False,
                    "required": True,
                    "message": f"{type(exc).__name__}: {exc}",
                }
            )
        checks.append(
            {
                "name": "mcp_sdk",
                "ok": importlib.util.find_spec("mcp") is not None,
                "required": False,
                "message": (
                    "available"
                    if importlib.util.find_spec("mcp") is not None
                    else "optional dependency not installed; serve is unavailable"
                ),
            }
        )
        semantic_generation = self._index.active_generation()
        semantic_ready = (
            self._semantic is not None
            and semantic_generation is not None
            and self._semantic.ready_for(semantic_generation)
        )
        checks.append(
            {
                "name": "semantic",
                "ok": semantic_ready,
                "required": False,
                "message": (
                    f"ready ({self._semantic.identity})"
                    if semantic_ready and self._semantic is not None
                    else "optional semantic generation not configured or not built"
                ),
            }
        )
        expected_languages = (
            "python",
            "typescript",
            "tsx",
            "javascript",
            "sql",
            "java",
            "markdown",
            "json",
            "yaml",
            "toml",
            "css",
            "shell",
        )
        missing_languages = [
            language
            for language in expected_languages
            if not any(
                extractor.supports(language) for extractor in self._extractors
            )
        ]
        checks.append(
            {
                "name": "language_extractors",
                "ok": not missing_languages,
                "required": False,
                "message": (
                    "available"
                    if not missing_languages
                    else "lexical fallback only for: "
                    + ", ".join(missing_languages)
                ),
            }
        )
        required_ok = all(item["ok"] for item in checks if item["required"])
        return {
            "healthy": required_ok,
            "core_healthy": required_ok,
            "serve_available": required_ok
            and any(item["name"] == "mcp_sdk" and item["ok"] for item in checks),
            "checks": checks,
        }

    def ensure_ready(self) -> GenerationInfo:
        """Validate that this repository owns a readable active generation."""

        return self._require_generation()

    def _require_generation(self) -> GenerationInfo:
        try:
            generation = self._index.active_generation()
        except Exception as exc:
            raise RepoContextError(
                "INDEX_UNAVAILABLE", f"cannot open active index: {exc}"
            ) from exc
        if generation is None:
            raise RepoContextError(
                "INDEX_UNAVAILABLE",
                "no active index generation; run `atenex-context index`",
            )
        if not self._binding_matches(generation.snapshot):
            raise RepoContextError(
                "INDEX_UNAVAILABLE",
                "the selected sidecar belongs to a different repository; "
                "choose another --data-dir or rebuild it",
            )
        return generation

    def _binding_matches(self, snapshot: RepositorySnapshot) -> bool:
        return (
            snapshot.root == str(self._root)
            and snapshot.repository_id
            == hashlib.sha256(os.fsencode(str(self._root))).hexdigest()
        )

    def _resolve_symbol_candidates(self, value: str) -> list[CodeSymbol]:
        matches = self._index.symbols(value, limit=50)
        unique = {item.id: item for item in matches}
        return sorted(
            unique.values(),
            key=lambda item: (
                item.qualified_name != value,
                item.name != value,
                item.file_path,
                item.line_start,
            ),
        )

    def _resolve_unique_symbol(self, value: str) -> CodeSymbol:
        matches = self._resolve_symbol_candidates(value.strip())
        exact = [
            item
            for item in matches
            if item.qualified_name == value.strip() or item.name == value.strip()
        ]
        selected = exact or matches
        if not selected:
            raise RepoContextError("NOT_FOUND", f"symbol not found: {value}")
        if len(selected) != 1:
            raise RepoContextError(
                "AMBIGUOUS",
                f"symbol is ambiguous: {value}",
                details={
                    "candidates": [
                        {
                            "id": item.id,
                            "qualified_name": item.qualified_name,
                            "path": item.file_path,
                            "line_start": item.line_start,
                        }
                        for item in selected[:20]
                    ]
                },
            )
        return selected[0]

    def _symbols_for_target(self, value: str) -> list[CodeSymbol]:
        cleaned = value.strip()
        inventory_paths = {
            str(item.get("path", "")) for item in self._index.file_inventory()
        }
        if cleaned in inventory_paths:
            found = self._index.symbols(cleaned, limit=200)
            return [item for item in found if item.file_path == cleaned]
        matches = self._resolve_symbol_candidates(cleaned)
        exact = [
            item
            for item in matches
            if item.qualified_name == cleaned or item.name == cleaned
        ]
        return exact or matches[:1]

    def _traverse(
        self,
        root: CodeSymbol,
        *,
        direction: str,
        depth: int,
        relations: Sequence[str],
        max_nodes: int,
    ) -> tuple[list[CodeSymbol], list[CodeEdge], int, int]:
        queue: deque[tuple[CodeSymbol, int]] = deque([(root, 0)])
        seen = {root.id}
        nodes: list[CodeSymbol] = []
        edges: list[CodeEdge] = []
        omitted = 0
        reached = 0
        while queue:
            current, level = queue.popleft()
            if level >= depth:
                continue
            current_edges = self._index.edges(
                current.id,
                direction=direction,
                relations=relations,
                limit=max_nodes * 4,
            )
            if direction in {"dependents", "callers"}:
                current_edges = _unique_edges(
                    [
                        *current_edges,
                        *self._inferred_incoming_edges(
                            current,
                            relations=relations,
                            limit=max_nodes * 4,
                        ),
                    ]
                )
            for edge in sorted(
                current_edges,
                key=lambda item: (
                    item.relation,
                    item.source_path,
                    item.evidence_line,
                    item.target_name,
                ),
            ):
                edges.append(edge)
                neighbor_id = _neighbor_id(edge, current.id)
                if neighbor_id is None or neighbor_id in seen:
                    continue
                neighbor = self._index.symbol_by_id(neighbor_id)
                if neighbor is None:
                    continue
                if len(nodes) >= max_nodes:
                    omitted += 1
                    continue
                seen.add(neighbor.id)
                nodes.append(neighbor)
                reached = max(reached, level + 1)
                queue.append((neighbor, level + 1))
        return nodes, edges, omitted, reached

    def _inferred_incoming_edges(
        self,
        target: CodeSymbol,
        *,
        relations: Sequence[str],
        limit: int,
    ) -> list[CodeEdge]:
        """Resolve conservative name-only incoming edges at query time.

        Language extractors intentionally preserve unresolved calls.  Until a
        store has materialized a unique target, this bounded fallback makes
        callers useful without pretending that ambiguous dynamic dispatch was
        resolved with certainty.
        """

        accepted_names = {
            target.name,
            target.qualified_name,
            target.qualified_name.rsplit(".", 1)[-1],
        }
        matches: list[CodeEdge] = []
        selected_relations = set(relations)
        for edge in self._all_graph_edges():
            if edge.source_symbol_id == target.id:
                continue
            if selected_relations and edge.relation not in selected_relations:
                continue
            if edge.target_symbol_id is not None:
                continue
            if edge.target_name not in accepted_names:
                continue
            matches.append(
                replace(
                    edge,
                    target_symbol_id=target.id,
                    confidence=min(edge.confidence, 0.7),
                    method=f"{edge.method}:query_resolution",
                    unresolved=True,
                )
            )
            if len(matches) >= limit:
                return matches
        return matches

    def _all_graph_edges(self) -> tuple[CodeEdge, ...]:
        """Load the active graph once per process and generation.

        The unresolved-call fallback needs a repository-wide view. Performing
        one SQLite lookup for every source symbol made impact analysis
        quadratic on medium repositories. A generation-keyed cache keeps the
        exact same conservative resolution semantics with one bounded read.
        """

        generation = self._index.active_generation()
        if generation is None:
            return ()
        generation_id = str(generation.id)
        if self._edge_cache_generation == generation_id:
            return self._edge_cache
        all_edges = getattr(self._index, "all_edges", None)
        if not callable(all_edges):
            return ()
        self._edge_cache = tuple(all_edges(limit=500_000))
        self._edge_cache_generation = generation_id
        return self._edge_cache

    def _related_tests_payload(
        self, symbol_or_path: str, *, top_k: int
    ) -> list[dict[str, Any]]:
        targets = self._symbols_for_target(symbol_or_path)
        inventory = self._index.file_inventory()
        target_paths = {item.file_path for item in targets}
        if not target_paths and any(
            str(item.get("path", "")) == symbol_or_path for item in inventory
        ):
            target_paths.add(symbol_or_path)

        ranked: dict[tuple[str, int], dict[str, Any]] = {}
        for target in targets:
            direct_edges = self._index.edges(
                target.id,
                direction="dependents",
                relations=("tests", "references", "imports", "calls"),
                limit=500,
            )
            inferred_edges = self._inferred_incoming_edges(
                target,
                relations=("tests", "references", "imports", "calls"),
                limit=500,
            )
            for edge in _unique_edges([*direct_edges, *inferred_edges]):
                if not _looks_like_test(edge.source_path):
                    continue
                score = 1.0 if edge.relation == "tests" else 0.9
                key = (edge.source_path, edge.evidence_line)
                ranked[key] = self._test_payload(
                    edge.source_path,
                    edge.evidence_line,
                    score,
                    [edge.relation, edge.method],
                    symbol_or_path,
                )
        # A literal symbol mention in test source is useful evidence even when
        # module aliases or framework registration prevent a safe graph edge.
        # Keep this below resolved relations and label it as a lexical signal.
        for hit in self._index.search(symbol_or_path, top_k=500):
            if not _looks_like_test(hit.path):
                continue
            key = (hit.path, hit.line_start)
            if key in ranked:
                continue
            ranked[key] = self._test_payload(
                hit.path,
                hit.line_start,
                0.8 if hit.score_components.get("exact", 0.0) > 0 else 0.65,
                ["lexical_reference", hit.reason],
                symbol_or_path,
            )
        target_stems = {
            PurePosixPath(path).stem.removeprefix("test_").removesuffix("_test")
            for path in target_paths
        }
        for record in inventory:
            path = str(record.get("path", ""))
            if not _looks_like_test(path):
                continue
            stem = PurePosixPath(path).stem.removeprefix("test_").removesuffix("_test")
            if target_stems and not any(
                candidate and (candidate in stem or stem in candidate)
                for candidate in target_stems
            ):
                continue
            key = (path, 1)
            ranked.setdefault(
                key,
                self._test_payload(
                    path,
                    1,
                    0.55,
                    ["naming_convention"],
                    symbol_or_path,
                ),
            )
        ordered = sorted(
            ranked.values(),
            key=lambda item: (
                -float(item["confidence"]),
                str(item["path"]),
                int(item["line_start"]),
            ),
        )
        unique: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for item in ordered:
            path = str(item["path"])
            if path in seen_paths:
                continue
            seen_paths.add(path)
            unique.append(item)
            if len(unique) >= top_k:
                break
        return unique

    def _test_payload(
        self,
        path: str,
        line: int,
        confidence: float,
        basis: list[str],
        target: str,
    ) -> dict[str, Any]:
        stored = self._index.file_text(path)
        content_hash = stored[1] if stored else ""
        return {
            "path": path,
            "test_symbol": None,
            "line_start": max(1, line),
            "line_end": max(1, line),
            "content_hash": content_hash,
            "basis": basis,
            "confidence": confidence,
            "target": target,
            "evidence": _evidence(
                path,
                max(1, line),
                max(1, line),
                content_hash,
                confidence,
                basis,
            ),
        }

    def _hit_payload(
        self, hit: SearchHit, *, include_source: bool
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        diagnostics: list[dict[str, Any]] = []
        snippet = hit.snippet
        if include_source:
            current, changed = self._verified_source(
                hit.path, hit.content_hash, hit.line_start, hit.line_end
            )
            if changed:
                snippet = ""
                diagnostics.append(_file_changed_diagnostic(hit.path))
            elif current:
                snippet = _bounded_excerpt(current)
        else:
            snippet = ""
        basis = sorted(hit.score_components) or [hit.reason]
        result_id = hit.symbol.id if hit.symbol else _result_id(hit)
        payload = {
            "id": result_id,
            "kind": hit.kind,
            "label": hit.symbol.qualified_name if hit.symbol else hit.path,
            "path": hit.path,
            "line_start": hit.line_start,
            "line_end": hit.line_end,
            "score": hit.score,
            "match_reason": hit.reason,
            "modes": basis,
            "score_components": dict(hit.score_components),
            "content_hash": hit.content_hash,
            "excerpt": snippet,
            "evidence": _evidence(
                hit.path,
                hit.line_start,
                hit.line_end,
                hit.content_hash,
                1.0,
                basis,
            ),
        }
        return payload, diagnostics

    def _symbol_payload(
        self, symbol: CodeSymbol, *, include_source: bool
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        stored = self._index.file_text(symbol.file_path)
        content_hash = stored[1] if stored else ""
        source = ""
        diagnostics: list[dict[str, Any]] = []
        if include_source and stored:
            source, changed = self._verified_source(
                symbol.file_path,
                content_hash,
                symbol.line_start,
                symbol.line_end,
            )
            if changed:
                diagnostics.append(_file_changed_diagnostic(symbol.file_path))
        payload = {
            **symbol.to_dict(),
            "content_hash": content_hash,
            "source": source if include_source else None,
            "evidence": _evidence(
                symbol.file_path,
                symbol.line_start,
                symbol.line_end,
                content_hash,
                1.0,
                ["definition"],
            ),
        }
        return payload, diagnostics

    def _file_payload(
        self, record: dict[str, object], *, include_source: bool
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        path = str(record.get("path", ""))
        stored = self._index.file_text(path)
        content_hash = str(record.get("content_hash", stored[1] if stored else ""))
        source = ""
        diagnostics: list[dict[str, Any]] = []
        raw_line_count = record.get("line_count", 1)
        line_end = int(raw_line_count) if isinstance(raw_line_count, int | str) else 1
        if include_source and stored:
            source, changed = self._verified_source(path, content_hash, 1, line_end)
            if changed:
                diagnostics.append(_file_changed_diagnostic(path))
        symbols = [
            item
            for item in self._index.symbols(path, limit=200)
            if item.file_path == path and item.parent_id is None
        ]
        payload = {
            "path": path,
            "language": record.get("language"),
            "content_hash": content_hash,
            "size": record.get("size"),
            "parse_state": record.get("parse_state"),
            "symbols": [item.to_dict() for item in symbols],
            "source": source if include_source else None,
            "evidence": _evidence(path, 1, line_end, content_hash, 1.0, ["file"]),
        }
        return payload, diagnostics

    def _edge_payload(self, edge: CodeEdge) -> dict[str, Any]:
        stored = self._index.file_text(edge.source_path)
        content_hash = stored[1] if stored else ""
        return {
            **edge.to_dict(),
            "evidence": _evidence(
                edge.source_path,
                max(1, edge.evidence_line),
                max(1, edge.evidence_line),
                content_hash,
                edge.confidence,
                [edge.relation, edge.method],
            ),
        }

    def _verified_source(
        self,
        path: str,
        expected_hash: str,
        line_start: int,
        line_end: int,
    ) -> tuple[str, bool]:
        try:
            source_path = resolve_inside(self._root, path)
            raw = source_path.read_bytes()
        except (OSError, ValueError):
            return "", True
        actual = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        if expected_hash and _hash_digest(actual) != _hash_digest(expected_hash):
            return "", True
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        start = max(1, line_start)
        end = max(start, line_end)
        return "\n".join(lines[start - 1 : end]), False

    def _envelope(
        self,
        generation: GenerationInfo,
        data: dict[str, Any],
        *,
        max_tokens: int,
        diagnostics: Sequence[dict[str, Any]] = (),
        truncated: bool = False,
        compact_list: str | None = None,
    ) -> dict[str, Any]:
        active = self._index.active_generation()
        if active is None or active.id != generation.id:
            raise RepoContextError(
                "INDEX_UNAVAILABLE",
                "the active index generation changed during the query; retry it",
            )
        # Query responses carry only diagnostics relevant to this result.
        # Persistent parser/scanner diagnostics belong to ``status``/``doctor``;
        # repeating up to 100 of them on every MCP call can consume the entire
        # context budget before any evidence is returned.
        current_diagnostics = list(diagnostics)
        try:
            current = self._scanner.scan().snapshot
            stale = (
                current.worktree_fingerprint
                != generation.snapshot.worktree_fingerprint
            )
        except Exception as exc:
            stale = True
            current_diagnostics.append(
                _diagnostic(
                    "FRESHNESS_CHECK_FAILED",
                    f"Could not verify current worktree: {type(exc).__name__}",
                    severity="error",
                )
            )
        if stale:
            current_diagnostics.append(
                _diagnostic(
                    "INDEX_STALE",
                    "The active index does not match the current worktree.",
                )
            )
        envelope: dict[str, Any] = {
            "repo": {"name": self._root.name, "root": "."},
            "snapshot": {
                "generation": str(generation.id),
                "head": generation.snapshot.head,
                "worktree_fingerprint": generation.snapshot.worktree_fingerprint,
                "stale": stale,
            },
            "data": data,
            "truncated": truncated,
            "token_estimate": 0,
            "diagnostics": _deduplicate_diagnostics(current_diagnostics),
        }
        envelope = _compact_envelope(
            envelope, max_tokens=max_tokens, list_key=compact_list
        )
        envelope["token_estimate"] = _estimate_tokens(envelope)
        return envelope


def _token_budget(value: int) -> int:
    if not MIN_TOKEN_BUDGET <= value <= MAX_TOKEN_BUDGET:
        raise RepoContextError(
            "INVALID_ARGUMENT",
            f"max_tokens must be between {MIN_TOKEN_BUDGET} and {MAX_TOKEN_BUDGET}",
        )
    return value


def _validate_graph_bounds(direction: str, depth: int, max_nodes: int) -> None:
    if direction not in ALLOWED_DIRECTIONS:
        raise RepoContextError(
            "INVALID_ARGUMENT",
            f"direction must be one of {sorted(ALLOWED_DIRECTIONS)}",
        )
    if not 1 <= depth <= 8:
        raise RepoContextError("INVALID_ARGUMENT", "depth must be between 1 and 8")
    if not 1 <= max_nodes <= 500:
        raise RepoContextError(
            "INVALID_ARGUMENT", "max_nodes must be between 1 and 500"
        )


def _validate_target_value(value: str) -> None:
    if not value:
        raise RepoContextError(
            "INVALID_ARGUMENT", "symbol_or_path must not be blank"
        )
    looks_like_path = (
        "/" in value
        or "\\" in value
        or value.startswith(".")
        or (len(value) >= 2 and value[1] == ":")
    )
    if not looks_like_path:
        return
    try:
        safe_relative_path(value)
    except ValueError as exc:
        raise RepoContextError("OUTSIDE_REPOSITORY", str(exc)) from exc


def _generation_counts(generation: GenerationInfo | None) -> dict[str, int]:
    if generation is None:
        return {"files": 0, "symbols": 0, "chunks": 0, "relations": 0}
    return {
        "files": generation.file_count,
        "symbols": generation.symbol_count,
        "chunks": generation.chunk_count,
        "relations": generation.edge_count,
    }


def _top_directory(path: str) -> str:
    parts = PurePosixPath(path).parts
    return parts[0] if len(parts) > 1 else "."


def _rank_landmark_files(
    inventory: Sequence[dict[str, object]], *, limit: int
) -> list[dict[str, Any]]:
    preferred = {
        "readme.md",
        "agents.md",
        "pyproject.toml",
        "package.json",
        "cargo.toml",
        "go.mod",
        "main.py",
        "app.py",
        "index.ts",
        "index.tsx",
        "main.ts",
    }

    def rank(item: dict[str, object]) -> tuple[int, int, str]:
        path = str(item.get("path", ""))
        name = PurePosixPath(path).name.lower()
        test = _looks_like_test(path)
        return (0 if name in preferred else 1, 1 if test else 0, path)

    result: list[dict[str, Any]] = []
    for item in sorted(inventory, key=rank)[:limit]:
        path = str(item.get("path", ""))
        content_hash = str(item.get("content_hash", ""))
        result.append(
            {
                "path": path,
                "language": item.get("language"),
                "role": (
                    "test"
                    if _looks_like_test(path)
                    else "entry_or_manifest"
                    if PurePosixPath(path).name.lower() in preferred
                    else "source"
                ),
                "evidence": _evidence(path, 1, 1, content_hash, 0.8, ["path", "index"]),
            }
        )
    return result


def _inventory_hash(
    inventory: Sequence[dict[str, object]],
    path: str,
) -> str:
    record = next(
        (item for item in inventory if str(item.get("path", "")) == path),
        None,
    )
    return str(record.get("content_hash", "")) if record else ""


def _neighbor_id(edge: CodeEdge, current_id: str) -> str | None:
    if edge.source_symbol_id == current_id:
        return edge.target_symbol_id
    if edge.target_symbol_id == current_id:
        return edge.source_symbol_id
    return edge.target_symbol_id or edge.source_symbol_id


def _unique_edges(edges: Sequence[CodeEdge]) -> list[CodeEdge]:
    unique: dict[str, CodeEdge] = {}
    for edge in edges:
        current = unique.get(edge.id)
        if current is None or edge.confidence > current.confidence:
            unique[edge.id] = edge
    return list(unique.values())


def _looks_like_test(path: str) -> bool:
    lowered = path.lower()
    parts = PurePosixPath(lowered).parts
    name = PurePosixPath(lowered).name
    return (
        "test" in parts
        or "tests" in parts
        or "__tests__" in parts
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
        or name.endswith("_test.py")
    )


def _result_id(hit: SearchHit) -> str:
    value = f"{hit.kind}\0{hit.path}\0{hit.line_start}\0{hit.line_end}"
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def _hash_digest(value: str) -> str:
    return value.split(":", 1)[-1].lower()


def _evidence(
    path: str,
    line_start: int,
    line_end: int,
    content_hash: str,
    confidence: float,
    basis: Iterable[str],
) -> dict[str, Any]:
    return {
        "path": path,
        "line_start": max(1, line_start),
        "line_end": max(max(1, line_start), line_end),
        "content_hash": content_hash,
        "confidence": max(0.0, min(1.0, confidence)),
        "basis": list(dict.fromkeys(item for item in basis if item)),
    }


def _diagnostic(
    code: str,
    message: str,
    *,
    severity: str = "warning",
    path: str | None = None,
) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "path": path}


def _file_changed_diagnostic(path: str) -> dict[str, Any]:
    return _diagnostic(
        "FILE_CHANGED_SINCE_INDEX",
        "The source file no longer matches the active generation; excerpt omitted.",
        path=path,
    )


def _normalize_diagnostic(item: object) -> dict[str, Any]:
    if isinstance(item, Diagnostic):
        raw = item.to_dict()
    elif isinstance(item, dict):
        raw = dict(item)
    else:
        raw = {"code": "INDEX_NOTICE", "message": str(item)}
    return {
        "code": str(raw.get("code", "INDEX_NOTICE")),
        "severity": str(raw.get("severity", "warning")),
        "message": str(raw.get("message", "")),
        "path": raw.get("path"),
        **({"details": raw["details"]} if raw.get("details") else {}),
    }


def _deduplicate_diagnostics(
    diagnostics: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen: set[tuple[str, str | None, str]] = set()
    result: list[dict[str, Any]] = []
    for item in diagnostics:
        normalized = _normalize_diagnostic(item)
        key = (
            str(normalized["code"]),
            normalized.get("path"),
            str(normalized["message"]),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _inferred_edge_diagnostics(edges: Sequence[CodeEdge]) -> list[dict[str, Any]]:
    if not any(edge.unresolved or edge.confidence < 1.0 for edge in edges):
        return []
    return [
        _diagnostic(
            "RELATION_INFERRED",
            "One or more graph relations are inferred or unresolved; "
            "inspect confidence.",
            severity="info",
        )
    ]


def _focus_queries(focus: str) -> tuple[str, ...]:
    """Build a small, auditable set of queries for cross-layer task overviews."""

    cleaned = " ".join(focus.split())
    if not cleaned:
        return ()
    terms = frozenset(
        token.casefold()
        for token in re.findall(r"[\w]+", cleaned, flags=re.UNICODE)
    )
    queries = [cleaned]
    for triggers, query in _FOCUS_QUERY_FACETS:
        if terms & triggers:
            queries.append(query)
    return tuple(dict.fromkeys(queries))


def _fuse_focus_hits(
    rankings: Sequence[Sequence[SearchHit]],
    *,
    limit: int,
) -> list[SearchHit]:
    """Fuse per-intent lexical rankings by path with deterministic RRF."""

    scores: dict[str, float] = {}
    appearances: Counter[str] = Counter()
    best: dict[str, SearchHit] = {}
    reasons: dict[str, set[str]] = {}
    for query_index, ranking in enumerate(rankings):
        weight = 0.85 if query_index == 0 and len(rankings) > 1 else 1.0
        seen_paths: set[str] = set()
        for rank, hit in enumerate(ranking, start=1):
            if hit.path in seen_paths:
                continue
            seen_paths.add(hit.path)
            scores[hit.path] = scores.get(hit.path, 0.0) + weight / (10.0 + rank)
            appearances[hit.path] += 1
            reasons.setdefault(hit.path, set()).add(hit.reason)
            current = best.get(hit.path)
            if current is None or hit.score > current.score:
                best[hit.path] = hit

    ordered_paths = sorted(
        best,
        key=lambda path: (
            -scores[path],
            -appearances[path],
            -best[path].score,
            path,
        ),
    )[: max(0, limit)]
    return [
        replace(
            best[path],
            score=float(scores[path]),
            reason="focus_rrf:" + "+".join(sorted(reasons[path])),
            score_components={
                **best[path].score_components,
                "focus_rrf": float(scores[path]),
                "focus_facets": float(appearances[path]),
            },
        )
        for path in ordered_paths
    ]


def _estimate_tokens(value: object) -> int:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return max(1, (len(serialized) + 3) // 4)


def _bounded_excerpt(value: str, *, limit: int = 100) -> str:
    normalized = value.strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}…"


def _compact_envelope(
    envelope: dict[str, Any],
    *,
    max_tokens: int,
    list_key: str | None,
) -> dict[str, Any]:
    envelope["token_estimate"] = _estimate_tokens(envelope)
    if envelope["token_estimate"] <= max_tokens:
        return envelope
    envelope["truncated"] = True
    envelope.setdefault("diagnostics", []).append(
        _diagnostic(
            "RESULT_TRUNCATED",
            "Result detail was omitted to honor the output budget.",
            severity="info",
        )
    )
    data = envelope.get("data")
    if isinstance(data, dict) and isinstance(data.get("repo_map"), dict):
        repo_map = data["repo_map"]
        repo_map["truncated"] = True
        # ``entries`` and ``rendered`` encode the same selection.  When the
        # envelope is already over budget, keep the structured paths/evidence
        # agents can act on and omit the duplicate rendered block atomically.
        repo_map["rendered"] = ""
        repo_map["estimated_tokens"] = 0
    bounded_lists = _bounded_output_lists(data, preferred=list_key)
    preferred_list = (
        data.get(list_key)
        if isinstance(data, dict) and list_key and isinstance(data.get(list_key), list)
        else None
    )
    lower_priority = [item for item in bounded_lists if item is not preferred_list]
    while _estimate_tokens(envelope) > max_tokens and any(lower_priority):
        largest = max(lower_priority, key=len)
        if largest:
            largest.pop()
    while (
        _estimate_tokens(envelope) > max_tokens
        and isinstance(preferred_list, list)
        and len(preferred_list) > 3
    ):
        preferred_list.pop()
    if _estimate_tokens(envelope) > max_tokens:
        _strip_large_strings(data)
    while _estimate_tokens(envelope) > max_tokens and any(bounded_lists):
        largest = max(bounded_lists, key=len)
        if largest:
            largest.pop()
    diagnostics = envelope.get("diagnostics")
    while (
        _estimate_tokens(envelope) > max_tokens
        and isinstance(diagnostics, list)
        and len(diagnostics) > 1
    ):
        diagnostics.pop()
    envelope["token_estimate"] = _estimate_tokens(envelope)
    return envelope


def _strip_large_strings(value: object) -> None:
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key in {"source", "excerpt", "snippet", "rendered"} and isinstance(
                item, str
            ):
                value[key] = ""
            else:
                _strip_large_strings(item)
    elif isinstance(value, list):
        for item in value:
            _strip_large_strings(item)


def _bounded_output_lists(
    data: object,
    *,
    preferred: str | None,
) -> list[list[Any]]:
    if not isinstance(data, dict):
        return []
    keys = [
        preferred,
        "focus_results",
        "results",
        "landmarks",
        "entries",
        "nodes",
        "edges",
        "relations",
        "affected_symbols",
        "affected_files",
        "related_tests",
        "principal_directories",
        "languages",
        "candidates",
    ]
    lists: list[list[Any]] = []
    seen: set[int] = set()

    def collect(mapping: dict[str, Any]) -> None:
        for key in keys:
            if not key:
                continue
            value = mapping.get(key)
            if isinstance(value, list) and id(value) not in seen:
                seen.add(id(value))
                lists.append(value)
        repo_map = mapping.get("repo_map")
        if isinstance(repo_map, dict):
            collect(repo_map)

    collect(data)
    return lists

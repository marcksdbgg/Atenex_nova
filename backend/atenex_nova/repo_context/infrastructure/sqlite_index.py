"""SQLite/FTS5 implementation of the deterministic Repo Context index."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path

from atenex_nova.repo_context.domain.models import (
    CodeChunk,
    CodeEdge,
    CodeSymbol,
    Diagnostic,
    ExtractionResult,
    FileRecord,
    GenerationInfo,
    RepositorySnapshot,
    ScanResult,
    SearchHit,
)

SCHEMA_VERSION = 1
_QUERY_STOPWORDS = frozenset(
    {
        "a",
        "al",
        "and",
        "como",
        "con",
        "de",
        "del",
        "desde",
        "el",
        "en",
        "for",
        "from",
        "how",
        "in",
        "is",
        "la",
        "las",
        "los",
        "of",
        "on",
        "or",
        "para",
        "por",
        "que",
        "the",
        "to",
        "un",
        "una",
        "what",
        "where",
        "with",
        "y",
    }
)
_QUERY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "api": ("route", "endpoint", "handler", "controller"),
    "caja": ("checkout",),
    "contrato": ("contract",),
    "contratos": ("contract",),
    "dependencia": ("dependency", "import"),
    "dependencias": ("dependency", "import"),
    "flow": ("route", "handler", "service", "processor", "projector"),
    "isolation": ("auth", "authorization", "guard", "rls", "policy"),
    "llamada": ("call",),
    "llamadas": ("call",),
    "multi-tienda": ("store",),
    "offline": ("outbox", "enqueue", "queue", "pending", "retry", "sync"),
    "persistencia": ("persist",),
    "persistida": ("persist",),
    "persistido": ("persist",),
    "persistence": (
        "persist",
        "database",
        "insert",
        "transaction",
        "repository",
        "projector",
    ),
    "pos": ("checkout", "register", "sale"),
    "prueba": ("test",),
    "pruebas": ("test",),
    "tienda": ("store",),
    "turno": ("shift",),
    "turnos": ("shift",),
    "venta": ("sale",),
    "ventas": ("sale",),
}


class SQLiteContextIndex:
    """A single-file index with transactional generation publication."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path.expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            os.chmod(self._database_path.parent, 0o700)
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"index schema {version} is newer than supported {SCHEMA_VERSION}"
                )
            if version == 0:
                self._create_schema(connection)
            elif version < SCHEMA_VERSION:
                self._migrate(connection, version)
        with suppress(OSError):
            os.chmod(self._database_path, 0o600)

    def build_generation(
        self,
        scan: ScanResult,
        extracted: dict[str, ExtractionResult],
        *,
        validate_snapshot: Callable[[], bool] | None = None,
    ) -> GenerationInfo:
        self.initialize()
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """
                    INSERT INTO generations (
                        state, repository_id, root, head, branch, dirty,
                        worktree_fingerprint, content_fingerprint, schema_version,
                        parser_version, created_at
                    ) VALUES ('building', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan.snapshot.repository_id,
                        scan.snapshot.root,
                        scan.snapshot.head,
                        scan.snapshot.branch,
                        int(scan.snapshot.dirty),
                        scan.snapshot.worktree_fingerprint,
                        scan.snapshot.content_fingerprint,
                        scan.snapshot.schema_version,
                        scan.snapshot.parser_version,
                        scan.snapshot.created_at,
                    ),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("generation id was not allocated")
                generation_id = cursor.lastrowid
                for file in scan.files:
                    result = extracted.get(file.path, ExtractionResult(parse_state="lexical"))
                    connection.execute(
                        """
                        INSERT INTO files (
                            generation_id, path, language, content_hash, size,
                            git_status, text, parse_state, line_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            generation_id,
                            file.path,
                            file.language,
                            file.content_hash,
                            file.size,
                            file.git_status,
                            file.text,
                            result.parse_state,
                            file.line_count,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO search_fts (
                            kind, item_id, generation_id, path, language,
                            symbol_kind, name, qualified_name, heading, content
                        ) VALUES ('file', ?, ?, ?, ?, '', '', '', '', ?)
                        """,
                        (file.path, generation_id, file.path, file.language, file.text),
                    )
                    self._insert_extraction(
                        connection, generation_id, file.path, result
                    )

                self._resolve_unique_edge_targets(connection, generation_id)
                all_diagnostics = list(scan.diagnostics)
                for result in extracted.values():
                    all_diagnostics.extend(result.diagnostics)
                for diagnostic in all_diagnostics:
                    self._insert_diagnostic(connection, generation_id, diagnostic)

                counts = self._validate_generation(connection, generation_id)
                if validate_snapshot is not None and not validate_snapshot():
                    raise RuntimeError(
                        "snapshot_changed_during_index: generation was not activated"
                    )
                connection.execute(
                    "UPDATE generations SET state = 'complete' WHERE state = 'active'"
                )
                connection.execute(
                    """
                    UPDATE generations
                    SET state = 'active', activated_at = CURRENT_TIMESTAMP,
                        file_count = ?, symbol_count = ?, chunk_count = ?,
                        edge_count = ?, diagnostics_count = ?
                    WHERE id = ? AND state = 'building'
                    """,
                    (*counts, generation_id),
                )
                connection.execute(
                    """
                    INSERT INTO metadata(key, value) VALUES ('active_generation', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (str(generation_id),),
                )
                self._prune_generations(connection, keep_inactive=1)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        active = self.active_generation()
        if active is None or active.id != generation_id:
            raise RuntimeError("generation_validation_failed")
        return active

    @staticmethod
    def _prune_generations(
        connection: sqlite3.Connection,
        *,
        keep_inactive: int,
    ) -> None:
        rows = connection.execute(
            """
            SELECT id FROM generations
            WHERE state != 'active'
            ORDER BY id DESC
            LIMIT -1 OFFSET ?
            """,
            (max(0, keep_inactive),),
        ).fetchall()
        for row in rows:
            generation_id = int(row["id"])
            connection.execute(
                "DELETE FROM search_fts WHERE generation_id = ?",
                (generation_id,),
            )
            connection.execute(
                "DELETE FROM generations WHERE id = ?",
                (generation_id,),
            )

    def active_generation(self) -> GenerationInfo | None:
        if not self._database_path.is_file():
            return None
        with self._read_connect() as connection:
            row = connection.execute(
                "SELECT * FROM generations WHERE state = 'active' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return self._generation_from_row(row) if row is not None else None

    def search(
        self,
        query: str,
        *,
        top_k: int,
        path_prefix: str | None = None,
        languages: Sequence[str] = (),
        symbol_kinds: Sequence[str] = (),
    ) -> list[SearchHit]:
        if top_k <= 0 or not query.strip():
            return []
        generation_id = self._active_id()
        if generation_id is None:
            return []
        query_tokens = _query_tokens(query)
        if not query_tokens:
            return []

        with self._read_connect() as connection:
            hits: list[SearchHit] = []
            # Natural-language repository questions rarely place every query
            # term in one chunk.  Preserve the precise all-term pass, then
            # relax to any-term retrieval and rank by term coverage.  Prefix
            # matching also bridges queries such as ``enqueue`` to identifiers
            # such as ``enqueueEvent`` without changing the stored FTS schema.
            for strategy, fts_query in _fts_query_plans(query_tokens):
                rows = self._search_fts_rows(
                    connection,
                    generation_id,
                    fts_query,
                    limit=min(2_000, max(top_k * 20, 500)),
                    path_prefix=path_prefix,
                    languages=languages,
                    symbol_kinds=symbol_kinds,
                )
                hits.extend(
                    self._search_hit_from_fts(
                        connection,
                        generation_id,
                        row,
                        query,
                        query_tokens=query_tokens,
                        strategy=strategy,
                    )
                    for row in rows
                )
            hits.extend(
                self._exact_file_hits(
                    connection,
                    generation_id,
                    query,
                    limit=max(top_k * 5, top_k),
                    path_prefix=path_prefix,
                    languages=languages,
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.path, hit.line_start, hit.kind))
        unique: list[SearchHit] = []
        seen: set[tuple[str, int, int, str]] = set()
        for hit in hits:
            key = (hit.path, hit.line_start, hit.line_end, hit.kind)
            if key in seen:
                continue
            seen.add(key)
            unique.append(hit)

        # Give the caller a useful map of the repository before returning
        # additional excerpts from the same file.  This avoids a large source
        # file monopolising the first page of a cross-module query.
        selected: list[SearchHit] = []
        path_counts: Counter[str] = Counter()
        bucket_counts: Counter[str] = Counter()
        remaining = list(unique)
        while remaining and len(selected) < top_k:
            candidates = [
                hit
                for hit in remaining
                if path_counts[hit.path] == 0
            ]
            if not candidates:
                candidates = [
                    hit for hit in remaining if path_counts[hit.path] < 3
                ]
            if not candidates:
                break
            candidate = min(
                candidates,
                key=lambda hit: (
                    -hit.score
                    / (1.0 + 0.08 * bucket_counts[_retrieval_bucket(hit.path)]),
                    hit.path,
                    hit.line_start,
                    hit.kind,
                ),
            )
            remaining.remove(candidate)
            selected.append(candidate)
            path_counts[candidate.path] += 1
            bucket_counts[_retrieval_bucket(candidate.path)] += 1
        return selected

    def _search_fts_rows(
        self,
        connection: sqlite3.Connection,
        generation_id: int,
        fts_query: str,
        *,
        limit: int,
        path_prefix: str | None,
        languages: Sequence[str],
        symbol_kinds: Sequence[str],
    ) -> list[sqlite3.Row]:
        clauses = ["generation_id = ?", "search_fts MATCH ?"]
        parameters: list[object] = [generation_id, fts_query]
        if path_prefix:
            clauses.append("path LIKE ? ESCAPE '\\'")
            parameters.append(_escape_like(path_prefix.rstrip("/")) + "%")
        if languages:
            placeholders = ",".join("?" for _ in languages)
            clauses.append(f"language IN ({placeholders})")
            parameters.extend(languages)
        if symbol_kinds:
            placeholders = ",".join("?" for _ in symbol_kinds)
            clauses.append(
                f"(kind != 'symbol' OR symbol_kind IN ({placeholders}))"
            )
            parameters.extend(symbol_kinds)
        parameters.append(limit)
        sql = f"""
            SELECT rowid, kind, item_id, path, language, symbol_kind, name,
                   qualified_name, heading, content, bm25(search_fts) AS rank
            FROM search_fts
            WHERE {" AND ".join(clauses)}
            ORDER BY rank
            LIMIT ?
        """
        return connection.execute(sql, parameters).fetchall()

    def _exact_file_hits(
        self,
        connection: sqlite3.Connection,
        generation_id: int,
        query: str,
        *,
        limit: int,
        path_prefix: str | None,
        languages: Sequence[str],
    ) -> list[SearchHit]:
        """Return case-sensitive literal matches before FTS ranking.

        BM25 is intentionally length-normalized, which can bury a migration or
        configuration file containing an exact identifier many times. Exact
        file candidates are a complementary signal, not a replacement for FTS.
        """

        clauses = ["generation_id = ?", "instr(text, ?) > 0"]
        parameters: list[object] = [generation_id, query]
        if path_prefix:
            clauses.append("path LIKE ? ESCAPE '\\'")
            parameters.append(_escape_like(path_prefix.rstrip("/")) + "%")
        if languages:
            placeholders = ",".join("?" for _ in languages)
            clauses.append(f"language IN ({placeholders})")
            parameters.extend(languages)
        parameters.append(limit)
        rows = connection.execute(
            f"""
            SELECT path, language, content_hash, text, line_count
            FROM files
            WHERE {" AND ".join(clauses)}
            ORDER BY path
            LIMIT ?
            """,
            parameters,
        ).fetchall()
        hits: list[SearchHit] = []
        for row in rows:
            text = str(row["text"])
            line = _matching_line(text, query)
            occurrences = text.count(query)
            exact_score = 5.0 + min(occurrences, 20) * 0.05
            hits.append(
                SearchHit(
                    kind="file",
                    path=str(row["path"]),
                    line_start=line,
                    line_end=line,
                    score=exact_score,
                    reason="exact",
                    content_hash=str(row["content_hash"]),
                    snippet=_bounded_snippet(_line_snippet(text, line)),
                    score_components={"exact": exact_score},
                )
            )
        return hits

    def symbols(self, query: str, *, limit: int = 20) -> list[CodeSymbol]:
        generation_id = self._active_id()
        if generation_id is None or limit <= 0:
            return []
        escaped = _escape_like(query)
        with self._read_connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM symbols
                WHERE generation_id = ?
                  AND (
                    name = ? COLLATE BINARY OR qualified_name = ? COLLATE BINARY
                    OR name LIKE ? ESCAPE '\\'
                    OR qualified_name LIKE ? ESCAPE '\\'
                  )
                ORDER BY
                  CASE
                    WHEN name = ? COLLATE BINARY THEN 0
                    WHEN qualified_name = ? COLLATE BINARY THEN 1
                    WHEN lower(name) = lower(?) THEN 2
                    ELSE 3
                  END,
                  length(qualified_name), path, line_start
                LIMIT ?
                """,
                (
                    generation_id,
                    query,
                    query,
                    f"%{escaped}%",
                    f"%{escaped}%",
                    query,
                    query,
                    query,
                    limit,
                ),
            ).fetchall()
        return [_symbol_from_row(row) for row in rows]

    def symbols_for_path(
        self, path: str, *, limit: int = 200
    ) -> list[CodeSymbol]:
        """Return definitions owned by one exact repository-relative path."""

        generation_id = self._active_id()
        if generation_id is None or limit <= 0:
            return []
        with self._read_connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM symbols
                WHERE generation_id = ? AND path = ? COLLATE BINARY
                ORDER BY line_start, line_end, id
                LIMIT ?
                """,
                (generation_id, path, limit),
            ).fetchall()
        return [_symbol_from_row(row) for row in rows]

    def symbol_by_id(self, symbol_id: str) -> CodeSymbol | None:
        generation_id = self._active_id()
        if generation_id is None:
            return None
        with self._read_connect() as connection:
            row = connection.execute(
                "SELECT * FROM symbols WHERE generation_id = ? AND id = ?",
                (generation_id, symbol_id),
            ).fetchone()
        return _symbol_from_row(row) if row is not None else None

    def edges(
        self,
        symbol_id: str,
        *,
        direction: str,
        relations: Sequence[str] = (),
        limit: int = 100,
    ) -> list[CodeEdge]:
        generation_id = self._active_id()
        if generation_id is None or limit <= 0:
            return []
        incoming = direction in {"incoming", "callers", "dependents"}
        column = "target_symbol_id" if incoming else "source_symbol_id"
        clauses = ["generation_id = ?", f"{column} = ?"]
        parameters: list[object] = [generation_id, symbol_id]
        if relations:
            placeholders = ",".join("?" for _ in relations)
            clauses.append(f"relation IN ({placeholders})")
            parameters.extend(relations)
        parameters.append(limit)
        with self._read_connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM edges
                WHERE {" AND ".join(clauses)}
                ORDER BY confidence DESC, source_path, evidence_line, id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [_edge_from_row(row) for row in rows]

    def all_edges(self, *, limit: int = 100_000) -> list[CodeEdge]:
        generation_id = self._active_id()
        if generation_id is None or limit <= 0:
            return []
        with self._read_connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM edges
                WHERE generation_id = ?
                ORDER BY confidence DESC, source_path, evidence_line, id
                LIMIT ?
                """,
                (generation_id, limit),
            ).fetchall()
        return [_edge_from_row(row) for row in rows]

    def file_text(self, path: str) -> tuple[str, str] | None:
        generation_id = self._active_id()
        if generation_id is None:
            return None
        with self._read_connect() as connection:
            row = connection.execute(
                """
                SELECT text, content_hash FROM files
                WHERE generation_id = ? AND path = ?
                """,
                (generation_id, path),
            ).fetchone()
        if row is None:
            return None
        return str(row["text"]), str(row["content_hash"])

    def file_inventory(self) -> list[dict[str, object]]:
        generation_id = self._active_id()
        if generation_id is None:
            return []
        with self._read_connect() as connection:
            rows = connection.execute(
                """
                SELECT path, language, content_hash, size, git_status,
                       parse_state, line_count
                FROM files WHERE generation_id = ? ORDER BY path
                """,
                (generation_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def diagnostics(self, *, limit: int = 100) -> list[dict[str, object]]:
        generation_id = self._active_id()
        if generation_id is None or limit <= 0:
            return []
        with self._read_connect() as connection:
            rows = connection.execute(
                """
                SELECT code, message, severity, path, details
                FROM diagnostics WHERE generation_id = ?
                ORDER BY id LIMIT ?
                """,
                (generation_id, limit),
            ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(str(item["details"]))
            result.append(item)
        return result

    def all_chunks(self) -> list[CodeChunk]:
        generation_id = self._active_id()
        if generation_id is None:
            return []
        with self._read_connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM chunks WHERE generation_id = ?
                ORDER BY path, line_start, id
                """,
                (generation_id,),
            ).fetchall()
        return [_chunk_from_row(row) for row in rows]

    def chunks_by_ids(self, ids: Sequence[str]) -> dict[str, CodeChunk]:
        generation_id = self._active_id()
        if generation_id is None or not ids:
            return {}
        unique_ids = tuple(dict.fromkeys(ids))
        placeholders = ",".join("?" for _ in unique_ids)
        with self._read_connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM chunks
                WHERE generation_id = ? AND id IN ({placeholders})
                """,
                (generation_id, *unique_ids),
            ).fetchall()
        return {str(row["id"]): _chunk_from_row(row) for row in rows}

    def chunk_content_hashes(self, ids: Sequence[str]) -> dict[str, str]:
        generation_id = self._active_id()
        if generation_id is None or not ids:
            return {}
        unique_ids = tuple(dict.fromkeys(ids))
        placeholders = ",".join("?" for _ in unique_ids)
        with self._read_connect() as connection:
            rows = connection.execute(
                f"""
                SELECT c.id, f.content_hash
                FROM chunks AS c
                JOIN files AS f
                  ON f.generation_id = c.generation_id AND f.path = c.path
                WHERE c.generation_id = ? AND c.id IN ({placeholders})
                """,
                (generation_id, *unique_ids),
            ).fetchall()
        return {str(row["id"]): str(row["content_hash"]) for row in rows}

    def reusable_extraction(
        self,
        file: FileRecord,
        *,
        parser_version: str,
    ) -> ExtractionResult | None:
        """Load immutable derived artifacts for an unchanged compatible file."""
        generation_id = self._active_id()
        if generation_id is None:
            return None
        with self._read_connect() as connection:
            generation = connection.execute(
                "SELECT parser_version FROM generations WHERE id = ?",
                (generation_id,),
            ).fetchone()
            if generation is None or str(generation["parser_version"]) != parser_version:
                return None
            file_row = connection.execute(
                """
                SELECT parse_state FROM files
                WHERE generation_id = ? AND path = ? AND content_hash = ?
                """,
                (generation_id, file.path, file.content_hash),
            ).fetchone()
            if file_row is None:
                return None
            chunk_rows = connection.execute(
                """
                SELECT * FROM chunks
                WHERE generation_id = ? AND path = ?
                ORDER BY line_start, id
                """,
                (generation_id, file.path),
            ).fetchall()
            symbol_rows = connection.execute(
                """
                SELECT * FROM symbols
                WHERE generation_id = ? AND path = ?
                ORDER BY line_start, id
                """,
                (generation_id, file.path),
            ).fetchall()
            edge_rows = connection.execute(
                """
                SELECT * FROM edges
                WHERE generation_id = ? AND source_path = ?
                ORDER BY evidence_line, id
                """,
                (generation_id, file.path),
            ).fetchall()
            diagnostic_rows = connection.execute(
                """
                SELECT code, message, severity, path, details
                FROM diagnostics
                WHERE generation_id = ? AND path = ?
                  AND code NOT IN ('duplicate_artifact_id')
                ORDER BY id
                """,
                (generation_id, file.path),
            ).fetchall()
        diagnostics = tuple(
            Diagnostic(
                code=str(row["code"]),
                message=str(row["message"]),
                severity=str(row["severity"]),  # type: ignore[arg-type]
                path=str(row["path"]) if row["path"] is not None else None,
                details=json.loads(str(row["details"])),
            )
            for row in diagnostic_rows
        )
        return ExtractionResult(
            chunks=tuple(_chunk_from_row(row) for row in chunk_rows),
            symbols=tuple(_symbol_from_row(row) for row in symbol_rows),
            edges=tuple(_edge_from_row(row) for row in edge_rows),
            diagnostics=diagnostics,
            parse_state=str(file_row["parse_state"]),  # type: ignore[arg-type]
        )

    def _active_id(self) -> int | None:
        if not self._database_path.is_file():
            return None
        with self._read_connect() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'active_generation'"
            ).fetchone()
        return int(row["value"]) if row is not None else None

    def _insert_extraction(
        self,
        connection: sqlite3.Connection,
        generation_id: int,
        path: str,
        result: ExtractionResult,
    ) -> None:
        for chunk in result.chunks:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO chunks (
                    generation_id, id, path, language, line_start, line_end,
                    content, kind, heading, symbol_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generation_id,
                    chunk.id,
                    path,
                    chunk.language,
                    chunk.line_start,
                    chunk.line_end,
                    chunk.content,
                    chunk.kind,
                    chunk.heading,
                    chunk.symbol_id,
                ),
            )
            if cursor.rowcount == 0:
                self._insert_duplicate_diagnostic(
                    connection, generation_id, path, "chunk", chunk.id
                )
                continue
            connection.execute(
                """
                INSERT INTO search_fts (
                    kind, item_id, generation_id, path, language, symbol_kind,
                    name, qualified_name, heading, content
                ) VALUES ('chunk', ?, ?, ?, ?, '', '', '', ?, ?)
                """,
                (
                    chunk.id,
                    generation_id,
                    path,
                    chunk.language,
                    chunk.heading or "",
                    chunk.content,
                ),
            )
        for symbol in result.symbols:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO symbols (
                    generation_id, id, path, language, name, qualified_name,
                    kind, line_start, line_end, signature, parent_id, role
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generation_id,
                    symbol.id,
                    path,
                    symbol.language,
                    symbol.name,
                    symbol.qualified_name,
                    symbol.kind,
                    symbol.line_start,
                    symbol.line_end,
                    symbol.signature,
                    symbol.parent_id,
                    symbol.role,
                ),
            )
            if cursor.rowcount == 0:
                self._insert_duplicate_diagnostic(
                    connection, generation_id, path, "symbol", symbol.id
                )
                continue
            connection.execute(
                """
                INSERT INTO search_fts (
                    kind, item_id, generation_id, path, language, symbol_kind,
                    name, qualified_name, heading, content
                ) VALUES ('symbol', ?, ?, ?, ?, ?, ?, ?, '', ?)
                """,
                (
                    symbol.id,
                    generation_id,
                    path,
                    symbol.language,
                    symbol.kind,
                    symbol.name,
                    symbol.qualified_name,
                    symbol.signature,
                ),
            )
        for edge in result.edges:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO edges (
                    generation_id, id, relation, source_symbol_id, source_path,
                    target_symbol_id, target_name, evidence_line, confidence,
                    method, unresolved
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generation_id,
                    edge.id,
                    edge.relation,
                    edge.source_symbol_id,
                    edge.source_path,
                    edge.target_symbol_id,
                    edge.target_name,
                    edge.evidence_line,
                    edge.confidence,
                    edge.method,
                    int(edge.unresolved),
                ),
            )
            if cursor.rowcount == 0:
                self._insert_duplicate_diagnostic(
                    connection, generation_id, path, "edge", edge.id
                )

    def _insert_duplicate_diagnostic(
        self,
        connection: sqlite3.Connection,
        generation_id: int,
        path: str,
        artifact_kind: str,
        artifact_id: str,
    ) -> None:
        self._insert_diagnostic(
            connection,
            generation_id,
            Diagnostic(
                code="duplicate_artifact_id",
                message=f"duplicate {artifact_kind} id ignored",
                path=path,
                details={
                    "artifact_kind": artifact_kind,
                    "artifact_id": artifact_id,
                },
            ),
        )

    def _resolve_unique_edge_targets(
        self,
        connection: sqlite3.Connection,
        generation_id: int,
    ) -> None:
        """Resolve only unambiguous symbol names; preserve uncertain edges."""
        connection.execute(
            """
            UPDATE edges
            SET target_symbol_id = NULL, unresolved = 1
            WHERE generation_id = ? AND target_symbol_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM symbols
                WHERE symbols.generation_id = edges.generation_id
                  AND symbols.id = edges.target_symbol_id
              )
            """,
            (generation_id,),
        )
        symbol_rows = connection.execute(
            """
            SELECT id, name, qualified_name
            FROM symbols WHERE generation_id = ?
            """,
            (generation_id,),
        ).fetchall()
        by_name: dict[str, list[str]] = {}
        by_qualified_name: dict[str, list[str]] = {}
        for row in symbol_rows:
            symbol_id = str(row["id"])
            by_name.setdefault(str(row["name"]), []).append(symbol_id)
            by_qualified_name.setdefault(
                str(row["qualified_name"]), []
            ).append(symbol_id)

        edge_rows = connection.execute(
            """
            SELECT id, target_name, confidence, method
            FROM edges
            WHERE generation_id = ? AND target_symbol_id IS NULL
            """,
            (generation_id,),
        ).fetchall()
        for row in edge_rows:
            target = str(row["target_name"]).strip()
            tiers = [
                by_qualified_name.get(target, []),
                by_name.get(target, []),
            ]
            final_segment = target.rsplit(".", 1)[-1]
            if final_segment != target:
                tiers.append(by_name.get(final_segment, []))
            resolved = next(
                (candidates[0] for candidates in tiers if len(candidates) == 1),
                None,
            )
            if resolved is None:
                continue
            connection.execute(
                """
                UPDATE edges
                SET target_symbol_id = ?, unresolved = 0, confidence = ?,
                    method = ?
                WHERE generation_id = ? AND id = ?
                """,
                (
                    resolved,
                    max(0.0, min(1.0, float(row["confidence"]) * 0.95)),
                    f"{row['method']}+unique_symbol_resolution",
                    generation_id,
                    row["id"],
                ),
            )

    def _insert_diagnostic(
        self,
        connection: sqlite3.Connection,
        generation_id: int,
        diagnostic: Diagnostic,
    ) -> None:
        connection.execute(
            """
            INSERT INTO diagnostics (
                generation_id, code, message, severity, path, details
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id,
                diagnostic.code,
                diagnostic.message,
                diagnostic.severity,
                diagnostic.path,
                json.dumps(diagnostic.details, sort_keys=True),
            ),
        )

    def _validate_generation(
        self, connection: sqlite3.Connection, generation_id: int
    ) -> tuple[int, int, int, int, int]:
        table_names = ("files", "symbols", "chunks", "edges", "diagnostics")
        counts = tuple(
            int(
                connection.execute(
                    f"SELECT count(*) FROM {table} WHERE generation_id = ?",
                    (generation_id,),
                ).fetchone()[0]
            )
            for table in table_names
        )
        integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"generation_validation_failed: {integrity}")
        return counts  # type: ignore[return-value]

    def _search_hit_from_fts(
        self,
        connection: sqlite3.Connection,
        generation_id: int,
        row: sqlite3.Row,
        query: str,
        *,
        query_tokens: Sequence[str],
        strategy: str,
    ) -> SearchHit:
        path = str(row["path"])
        kind = str(row["kind"])
        content_hash_row = connection.execute(
            """
            SELECT content_hash FROM files
            WHERE generation_id = ? AND path = ?
            """,
            (generation_id, path),
        ).fetchone()
        content_hash = (
            str(content_hash_row["content_hash"]) if content_hash_row else ""
        )
        symbol: CodeSymbol | None = None
        line_start = 1
        line_end = 1
        snippet = str(row["content"])
        if kind == "chunk":
            chunk = connection.execute(
                """
                SELECT * FROM chunks WHERE generation_id = ? AND id = ?
                """,
                (generation_id, row["item_id"]),
            ).fetchone()
            if chunk is not None:
                line_start = int(chunk["line_start"])
                line_end = int(chunk["line_end"])
                snippet = str(chunk["content"])
        elif kind == "symbol":
            symbol_row = connection.execute(
                """
                SELECT * FROM symbols WHERE generation_id = ? AND id = ?
                """,
                (generation_id, row["item_id"]),
            ).fetchone()
            if symbol_row is not None:
                symbol = _symbol_from_row(symbol_row)
                line_start = symbol.line_start
                line_end = symbol.line_end
                snippet = symbol.signature or symbol.qualified_name
        else:
            file_row = connection.execute(
                """
                SELECT text, line_count FROM files
                WHERE generation_id = ? AND path = ?
                """,
                (generation_id, path),
            ).fetchone()
            if file_row is not None:
                text = str(file_row["text"])
                line_start = _matching_line(text, query)
                line_end = line_start
                snippet = _line_snippet(text, line_start)

        raw_bm25 = max(0.0, -float(row["rank"]))
        lexical = raw_bm25 / (1.0 + raw_bm25)
        exact = _exact_boost(query, path, str(row["name"]), str(row["qualified_name"]))
        searchable = " ".join(
            (
                path,
                str(row["name"]),
                str(row["qualified_name"]),
                str(row["heading"]),
                str(row["content"]),
            )
        ).casefold()
        matched_terms = sum(token.casefold() in searchable for token in query_tokens)
        coverage = matched_terms / len(query_tokens)
        path_text = path.casefold()
        path_coverage = (
            sum(token.casefold() in path_text for token in query_tokens)
            / len(query_tokens)
        )
        symbol_text = " ".join(
            (str(row["name"]), str(row["qualified_name"]))
        ).casefold()
        symbol_coverage = (
            sum(token.casefold() in symbol_text for token in query_tokens)
            / len(query_tokens)
        )
        all_terms = 1.0 if strategy == "all_terms" else 0.0
        kind_bonus = 0.4 if kind == "symbol" else 0.2 if kind == "chunk" else 0.0
        asks_for_tests = any(
            token.casefold() in {"test", "tests", "testing", "prueba", "pruebas"}
            for token in query_tokens
        )
        test_penalty = (
            -2.25 if _looks_like_test_path(path) and not asks_for_tests else 0.0
        )
        source_bonus = (
            -0.25
            if path.startswith("docs/")
            else 0.25
            if path.startswith(("apps/", "packages/"))
            and not _looks_like_test_path(path)
            else 0.0
        )
        score = (
            exact
            + coverage * 4.0
            + path_coverage * 8.0
            + symbol_coverage * 4.0
            + lexical
            + all_terms
            + kind_bonus
            + test_penalty
            + source_bonus
        )
        score_components = {
            key: value
            for key, value in {
                "lexical": lexical,
                "coverage": coverage,
                "path": path_coverage,
                "symbol": symbol_coverage,
                "all_terms": all_terms,
                "exact": exact,
            }.items()
            if value > 0.0
        }
        return SearchHit(
            kind=kind,  # type: ignore[arg-type]
            path=path,
            line_start=line_start,
            line_end=line_end,
            score=score,
            reason=(
                f"exact+fts5_{strategy}" if exact > 0 else f"fts5_{strategy}"
            ),
            content_hash=content_hash,
            snippet=_bounded_snippet(snippet),
            symbol=symbol,
            score_components=score_components,
        )

    def _generation_from_row(self, row: sqlite3.Row) -> GenerationInfo:
        snapshot = RepositorySnapshot(
            repository_id=str(row["repository_id"]),
            root=str(row["root"]),
            head=str(row["head"]) if row["head"] is not None else None,
            branch=str(row["branch"]) if row["branch"] is not None else None,
            dirty=bool(row["dirty"]),
            worktree_fingerprint=str(row["worktree_fingerprint"]),
            content_fingerprint=str(row["content_fingerprint"]),
            schema_version=int(row["schema_version"]),
            parser_version=str(row["parser_version"]),
            created_at=str(row["created_at"]),
        )
        return GenerationInfo(
            id=int(row["id"]),
            state=str(row["state"]),  # type: ignore[arg-type]
            snapshot=snapshot,
            file_count=int(row["file_count"]),
            symbol_count=int(row["symbol_count"]),
            chunk_count=int(row["chunk_count"]),
            edge_count=int(row["edge_count"]),
            diagnostics_count=int(row["diagnostics_count"]),
            activated_at=(
                str(row["activated_at"]) if row["activated_at"] is not None else None
            ),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self._database_path,
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _read_connect(self) -> Iterator[sqlite3.Connection]:
        """Open an existing index without creating, migrating, or changing PRAGMAs."""
        uri = f"{self._database_path.as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        try:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE generations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    state TEXT NOT NULL CHECK (
                        state IN ('building', 'complete', 'active', 'abandoned')
                    ),
                    repository_id TEXT NOT NULL,
                    root TEXT NOT NULL,
                    head TEXT,
                    branch TEXT,
                    dirty INTEGER NOT NULL,
                    worktree_fingerprint TEXT NOT NULL,
                    content_fingerprint TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    parser_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    activated_at TEXT,
                    file_count INTEGER NOT NULL DEFAULT 0,
                    symbol_count INTEGER NOT NULL DEFAULT 0,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    edge_count INTEGER NOT NULL DEFAULT 0,
                    diagnostics_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE files (
                    generation_id INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    language TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    git_status TEXT NOT NULL,
                    text TEXT NOT NULL,
                    parse_state TEXT NOT NULL,
                    line_count INTEGER NOT NULL,
                    PRIMARY KEY (generation_id, path),
                    FOREIGN KEY (generation_id) REFERENCES generations(id)
                        ON DELETE CASCADE
                );
                CREATE TABLE chunks (
                    generation_id INTEGER NOT NULL,
                    id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    language TEXT NOT NULL,
                    line_start INTEGER NOT NULL,
                    line_end INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    heading TEXT,
                    symbol_id TEXT,
                    PRIMARY KEY (generation_id, id),
                    FOREIGN KEY (generation_id, path)
                        REFERENCES files(generation_id, path) ON DELETE CASCADE
                );
                CREATE TABLE symbols (
                    generation_id INTEGER NOT NULL,
                    id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    language TEXT NOT NULL,
                    name TEXT NOT NULL,
                    qualified_name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    line_start INTEGER NOT NULL,
                    line_end INTEGER NOT NULL,
                    signature TEXT NOT NULL,
                    parent_id TEXT,
                    role TEXT,
                    PRIMARY KEY (generation_id, id),
                    FOREIGN KEY (generation_id, path)
                        REFERENCES files(generation_id, path) ON DELETE CASCADE
                );
                CREATE TABLE edges (
                    generation_id INTEGER NOT NULL,
                    id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    source_symbol_id TEXT,
                    source_path TEXT NOT NULL,
                    target_symbol_id TEXT,
                    target_name TEXT NOT NULL,
                    evidence_line INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    method TEXT NOT NULL,
                    unresolved INTEGER NOT NULL,
                    PRIMARY KEY (generation_id, id),
                    FOREIGN KEY (generation_id) REFERENCES generations(id)
                        ON DELETE CASCADE
                );
                CREATE TABLE diagnostics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    generation_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    message TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    path TEXT,
                    details TEXT NOT NULL,
                    FOREIGN KEY (generation_id) REFERENCES generations(id)
                        ON DELETE CASCADE
                );
                CREATE VIRTUAL TABLE search_fts USING fts5(
                    kind UNINDEXED,
                    item_id UNINDEXED,
                    generation_id UNINDEXED,
                    path,
                    language UNINDEXED,
                    symbol_kind UNINDEXED,
                    name,
                    qualified_name,
                    heading,
                    content,
                    tokenize = 'unicode61 remove_diacritics 2 tokenchars ''_'''
                );
                CREATE INDEX idx_files_generation_language
                    ON files(generation_id, language);
                CREATE INDEX idx_symbols_generation_name
                    ON symbols(generation_id, name);
                CREATE INDEX idx_symbols_generation_qualified
                    ON symbols(generation_id, qualified_name);
                CREATE INDEX idx_edges_generation_source
                    ON edges(generation_id, source_symbol_id);
                CREATE INDEX idx_edges_generation_target
                    ON edges(generation_id, target_symbol_id);
                CREATE INDEX idx_diagnostics_generation
                    ON diagnostics(generation_id);
                PRAGMA user_version = 1;
                COMMIT;
                """
            )
        except sqlite3.OperationalError as exc:
            with suppress(sqlite3.Error):
                connection.execute("ROLLBACK")
            if "fts5" in str(exc).lower():
                raise RuntimeError("SQLite was built without FTS5 support") from exc
            raise

    def _migrate(self, connection: sqlite3.Connection, version: int) -> None:
        if version != SCHEMA_VERSION:
            raise RuntimeError(f"no migration path from schema {version}")


SqliteContextIndex = SQLiteContextIndex


def _query_tokens(query: str) -> tuple[str, ...]:
    raw_tokens = re.findall(r"[\w.:/@-]+", query, flags=re.UNICODE)
    normalized = [token.strip(".:/@-") for token in raw_tokens]
    filtered = [
        token
        for token in normalized
        if token and token.casefold() not in _QUERY_STOPWORDS
    ]
    selected = filtered or [token for token in normalized if token]
    expanded: list[str] = []
    for token in selected:
        expanded.append(token)
        components = tuple(
            part for part in re.split(r"[/:.-]+", token) if len(part) > 1
        )
        if len(components) > 1:
            expanded.extend(components)
        for concept in (token, *components):
            expanded.extend(_QUERY_SYNONYMS.get(concept.casefold(), ()))
    return tuple(dict.fromkeys(expanded))


def _fts_query_plans(tokens: Sequence[str]) -> tuple[tuple[str, str], ...]:
    escaped = [
        f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens
    ]
    if not escaped:
        return ()
    all_terms = " AND ".join(escaped)
    if len(escaped) == 1:
        return (("all_terms", all_terms),)
    return (
        ("all_terms", all_terms),
        ("any_term", " OR ".join(escaped)),
    )


def _looks_like_test_path(path: str) -> bool:
    lowered = path.casefold()
    return (
        "/tests/" in f"/{lowered}"
        or "/__tests__/" in f"/{lowered}"
        or ".test." in lowered
        or ".spec." in lowered
    )


def _retrieval_bucket(path: str) -> str:
    parts = Path(path).parts
    if len(parts) >= 2 and parts[0] in {"apps", "packages"}:
        # ``apps/store`` is too coarse for a cross-layer flow: it makes a
        # result from ``services/sync`` suppress ``services/db`` and
        # ``stores`` even though those are distinct architectural stages.
        # Keep one directory below the conventional ``src`` boundary, and a
        # second one when present (for example ``services/db`` vs
        # ``services/sync``).
        depth = 5 if len(parts) >= 6 else min(4, len(parts) - 1)
        return "/".join(parts[:depth])
    return parts[0] if parts else "."


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _exact_boost(query: str, path: str, name: str, qualified_name: str) -> float:
    if query == name:
        return 8.0
    if query == qualified_name:
        return 7.5
    if query == path or path.endswith(f"/{query}"):
        return 6.5
    lowered = query.casefold()
    if lowered in {name.casefold(), qualified_name.casefold(), path.casefold()}:
        return 5.5
    return 0.0


def _matching_line(text: str, query: str) -> int:
    lowered = query.casefold()
    for number, line in enumerate(text.splitlines(), start=1):
        if lowered in line.casefold():
            return number
    return 1


def _line_snippet(text: str, line_number: int) -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    start = max(0, line_number - 2)
    end = min(len(lines), line_number + 1)
    return "\n".join(lines[start:end])


def _bounded_snippet(value: str, limit: int = 800) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _symbol_from_row(row: sqlite3.Row) -> CodeSymbol:
    return CodeSymbol(
        id=str(row["id"]),
        file_path=str(row["path"]),
        language=str(row["language"]),
        name=str(row["name"]),
        qualified_name=str(row["qualified_name"]),
        kind=str(row["kind"]),
        line_start=int(row["line_start"]),
        line_end=int(row["line_end"]),
        signature=str(row["signature"]),
        parent_id=str(row["parent_id"]) if row["parent_id"] is not None else None,
        role=str(row["role"]) if row["role"] is not None else None,
    )


def _chunk_from_row(row: sqlite3.Row) -> CodeChunk:
    return CodeChunk(
        id=str(row["id"]),
        file_path=str(row["path"]),
        language=str(row["language"]),
        line_start=int(row["line_start"]),
        line_end=int(row["line_end"]),
        content=str(row["content"]),
        kind=str(row["kind"]),
        heading=str(row["heading"]) if row["heading"] is not None else None,
        symbol_id=str(row["symbol_id"]) if row["symbol_id"] is not None else None,
    )


def _edge_from_row(row: sqlite3.Row) -> CodeEdge:
    return CodeEdge(
        id=str(row["id"]),
        relation=str(row["relation"]),
        source_symbol_id=(
            str(row["source_symbol_id"])
            if row["source_symbol_id"] is not None
            else None
        ),
        source_path=str(row["source_path"]),
        target_symbol_id=(
            str(row["target_symbol_id"])
            if row["target_symbol_id"] is not None
            else None
        ),
        target_name=str(row["target_name"]),
        evidence_line=int(row["evidence_line"]),
        confidence=float(row["confidence"]),
        method=str(row["method"]),
        unresolved=bool(row["unresolved"]),
    )

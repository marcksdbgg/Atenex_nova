from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from atenex_nova.repo_context.application.indexing import IndexRepositoryService
from atenex_nova.repo_context.application.services import RepoContextServices
from atenex_nova.repo_context.domain.models import (
    CodeChunk,
    CodeEdge,
    CodeSymbol,
    Diagnostic,
    ExtractionResult,
    FileRecord,
    RepositorySnapshot,
    ScanResult,
)
from atenex_nova.repo_context.domain.policies import IndexPolicy
from atenex_nova.repo_context.infrastructure.git_scanner import GitRepositoryScanner
from atenex_nova.repo_context.infrastructure.sqlite_index import SQLiteContextIndex


class GitRepositoryScannerTests(unittest.TestCase):
    def test_git_inventory_includes_tracked_and_untracked_but_excludes_unsafe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _git(root, "init", "-q")
            (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
            (root / "tracked.py").write_text("def tracked():\n    return 1\n")
            (root / "untracked.ts").write_text("export const value = 2;\n")
            (root / "ignored.txt").write_text("not indexed\n")
            (root / ".env").write_text("TOKEN=secret\n")
            (root / "image.dat").write_bytes(b"abc\0def")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "package.js").write_text("ignored")
            _git(root, "add", ".gitignore", "tracked.py")
            _git(root, "add", "-f", ".env")

            result = GitRepositoryScanner(root).scan()

            by_path = {item.path: item for item in result.files}
            self.assertIn("tracked.py", by_path)
            self.assertIn("untracked.ts", by_path)
            self.assertNotIn("ignored.txt", by_path)
            self.assertNotIn(".env", by_path)
            self.assertNotIn("node_modules/package.js", by_path)
            self.assertEqual(by_path["tracked.py"].git_status, "A ")
            self.assertEqual(by_path["untracked.ts"].git_status, "??")
            self.assertEqual(by_path["tracked.py"].language, "python")
            codes = {item.code for item in result.diagnostics}
            self.assertIn("excluded_secret", codes)
            self.assertIn("excluded_binary", codes)
            self.assertTrue(result.snapshot.dirty)

    def test_filesystem_fallback_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / "main.py").write_text("print('safe')\n")
            try:
                (root / "escape.py").symlink_to(Path(outside) / "secret.py")
            except OSError:
                self.skipTest("the current platform does not permit symlink creation")

            result = GitRepositoryScanner(root).scan()

            self.assertEqual([file.path for file in result.files], ["main.py"])
            self.assertIsNone(result.snapshot.head)
            self.assertEqual(result.files[0].git_status, "filesystem")
            self.assertIn(
                "excluded_symlink_escape",
                {item.code for item in result.diagnostics},
            )

    def test_content_change_changes_fingerprint_and_large_file_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "main.py"
            source.write_text("x = 1\n")
            scanner = GitRepositoryScanner(
                root,
                policy=IndexPolicy(max_file_bytes=16),
            )
            first = scanner.scan()
            source.write_text("x = 2\n")
            second = scanner.scan()
            (root / "large.py").write_text("x" * 17)
            third = scanner.scan()

            self.assertNotEqual(
                first.snapshot.content_fingerprint,
                second.snapshot.content_fingerprint,
            )
            self.assertNotEqual(
                first.snapshot.worktree_fingerprint,
                second.snapshot.worktree_fingerprint,
            )
            self.assertIn(
                "excluded_large_file",
                {item.code for item in third.diagnostics},
            )


class SQLiteContextIndexTests(unittest.TestCase):
    def test_generation_queries_and_atomic_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = SQLiteContextIndex(Path(directory) / "context.sqlite3")
            first_scan = _scan("def alpha():\n    return beta()\n", content="one")
            extraction = _extraction("alpha")

            first = index.build_generation(first_scan, {"src/main.py": extraction})

            self.assertEqual(first.state, "active")
            self.assertEqual(first.file_count, 1)
            self.assertEqual(first.symbol_count, 2)
            self.assertEqual(first.chunk_count, 1)
            self.assertEqual(index.symbols("alpha")[0].qualified_name, "main.alpha")
            self.assertEqual(
                [item.id for item in index.symbols_for_path("src/main.py")],
                ["symbol-alpha", "symbol-beta"],
            )
            self.assertEqual(index.symbol_by_id("symbol-alpha"), extraction.symbols[0])
            outgoing = index.edges("symbol-alpha", direction="callees")
            self.assertEqual(outgoing[0].target_symbol_id, "symbol-beta")
            self.assertFalse(outgoing[0].unresolved)
            incoming = index.edges("symbol-beta", direction="callers")
            self.assertEqual(incoming[0].source_symbol_id, "symbol-alpha")
            self.assertEqual(index.file_text("src/main.py"), (
                first_scan.files[0].text,
                first_scan.files[0].content_hash,
            ))
            self.assertEqual(index.all_chunks(), list(extraction.chunks))
            self.assertEqual(
                index.chunks_by_ids(["chunk-alpha"]),
                {"chunk-alpha": extraction.chunks[0]},
            )
            self.assertEqual(
                index.chunk_content_hashes(["chunk-alpha"]),
                {"chunk-alpha": first_scan.files[0].content_hash},
            )
            hits = index.search("alpha", top_k=5)
            self.assertTrue(hits)
            self.assertTrue(all(hit.content_hash for hit in hits))
            self.assertEqual(index.diagnostics()[0]["code"], "test_diagnostic")

            second_scan = _scan("def replacement():\n    return 2\n", content="two")
            second_extraction = _extraction("replacement")
            second = index.build_generation(
                second_scan,
                {"src/main.py": second_extraction},
            )

            self.assertGreater(second.id, first.id)
            self.assertEqual(index.active_generation(), second)
            self.assertEqual(index.symbols("alpha"), [])
            self.assertTrue(index.search("replacement", top_k=5))
            self.assertEqual(index.search("alpha", top_k=5), [])

            index.build_generation(
                _scan("def gamma():\n    pass\n", content="three"),
                {"src/main.py": _extraction("gamma")},
            )
            with index._read_connect() as connection:
                generation_count = int(
                    connection.execute("SELECT count(*) FROM generations").fetchone()[0]
                )
            self.assertEqual(generation_count, 2)

    def test_failed_generation_keeps_previous_generation_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = SQLiteContextIndex(Path(directory) / "context.sqlite3")
            valid_scan = _scan("def alpha():\n    pass\n", content="valid")
            active = index.build_generation(
                valid_scan,
                {"src/main.py": _extraction("alpha")},
            )
            with patch.object(
                index,
                "_validate_generation",
                side_effect=RuntimeError("forced validation failure"),
            ), self.assertRaisesRegex(RuntimeError, "forced"):
                index.build_generation(
                    valid_scan,
                    {"src/main.py": _extraction("replacement")},
                )

            self.assertEqual(index.active_generation(), active)
            self.assertTrue(index.search("alpha", top_k=5))

    def test_changed_snapshot_is_not_activated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = SQLiteContextIndex(Path(directory) / "context.sqlite3")
            scan = _scan("def alpha():\n    pass\n", content="stable")
            active = index.build_generation(
                scan,
                {"src/main.py": _extraction("alpha")},
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "snapshot_changed_during_index",
            ):
                index.build_generation(
                    scan,
                    {"src/main.py": _extraction("replacement")},
                    validate_snapshot=lambda: False,
                )

            self.assertEqual(index.active_generation(), active)

    def test_duplicate_artifact_ids_are_diagnosed_not_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = SQLiteContextIndex(Path(directory) / "context.sqlite3")
            scan = _scan("def alpha():\n    pass\n", content="duplicates")
            extraction = _extraction("alpha")
            duplicate = ExtractionResult(
                chunks=(extraction.chunks[0], extraction.chunks[0]),
                symbols=(extraction.symbols[0], extraction.symbols[0]),
                edges=(extraction.edges[0], extraction.edges[0]),
            )

            generation = index.build_generation(scan, {"src/main.py": duplicate})

            self.assertEqual(generation.state, "active")
            self.assertGreaterEqual(
                sum(
                    item["code"] == "duplicate_artifact_id"
                    for item in index.diagnostics()
                ),
                3,
            )

    def test_read_methods_do_not_create_a_missing_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "missing" / "context.sqlite3"
            index = SQLiteContextIndex(database)

            self.assertIsNone(index.active_generation())
            self.assertEqual(index.search("anything", top_k=5), [])
            self.assertEqual(index.file_inventory(), [])
            self.assertFalse(database.exists())
            self.assertFalse(database.parent.exists())

    def test_exact_literal_search_complements_fts_with_file_diversity(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as data_dir:
            root = Path(source_dir)
            contents = {
                "migrations/001.sql": "CREATE TABLE exact_identifier (id int);\n",
                "migrations/002.sql": (
                    "ALTER TABLE exact_identifier ADD COLUMN active bool;\n"
                ),
            }
            scan = _multi_file_scan(root, contents)
            index = SQLiteContextIndex(Path(data_dir) / "index.sqlite3")
            index.build_generation(
                scan,
                {path: ExtractionResult() for path in contents},
            )

            hits = index.search("exact_identifier", top_k=2)

            self.assertEqual(
                {item.path for item in hits},
                set(contents),
            )
            self.assertTrue(all(item.reason == "exact" for item in hits))

    def test_exact_symbol_ranks_above_files_that_only_mention_its_name(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as data_dir:
            root = Path(source_dir)
            contents = {
                "src/service.py": "def ImportantService():\n    return 1\n",
                "README.md": "Call ImportantService when the process starts.\n",
            }
            scan = _multi_file_scan(root, contents)
            symbol = CodeSymbol(
                id="important-service",
                file_path="src/service.py",
                language="python",
                name="ImportantService",
                qualified_name="service.ImportantService",
                kind="function",
                line_start=1,
                line_end=2,
                signature="def ImportantService()",
            )
            index = SQLiteContextIndex(Path(data_dir) / "index.sqlite3")
            index.build_generation(
                scan,
                {
                    "src/service.py": ExtractionResult(symbols=(symbol,)),
                    "README.md": ExtractionResult(),
                },
            )

            hits = index.search("ImportantService", top_k=3)

            self.assertEqual(hits[0].kind, "symbol")
            self.assertEqual(hits[0].symbol, symbol)

    def test_natural_language_search_relaxes_all_terms_and_diversifies_files(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as data_dir:
            root = Path(source_dir)
            contents = {
                "apps/store/src/services/db/outbox.ts": (
                    "offline sale queue; export function enqueueEvent() {}\n"
                ),
                "apps/store/src/services/sync/syncService.ts": (
                    "sync pending outbox batches to the server\n"
                ),
                "apps/api/src/routes/sync.ts": "POST sync persists each sale\n",
                "packages/scanner/src/camera.ts": "scan a barcode\n",
            }
            scan = _multi_file_scan(root, contents)
            index = SQLiteContextIndex(Path(data_dir) / "index.sqlite3")
            index.build_generation(
                scan,
                {path: ExtractionResult() for path in contents},
            )

            hits = index.search("outbox enqueue sale offline sync", top_k=10)
            paths = [item.path for item in hits]

            self.assertEqual(paths[0], "apps/store/src/services/db/outbox.ts")
            self.assertIn("apps/store/src/services/sync/syncService.ts", paths[:4])
            self.assertIn("apps/api/src/routes/sync.ts", paths[:4])
            self.assertTrue(any("any_term" in item.reason for item in hits))
            self.assertNotIn("packages/scanner/src/camera.ts", paths)

    def test_indexing_service_uses_lexical_fallback_without_extractors(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as data_dir:
            source = Path(source_dir)
            (source / "README.md").write_text("# Bread\n\nLocal context.\n")
            index = SQLiteContextIndex(Path(data_dir) / "index.sqlite3")
            service = IndexRepositoryService(GitRepositoryScanner(source), index)

            generation = service.execute(full=True)

            self.assertEqual(generation.file_count, 1)
            self.assertEqual(generation.chunk_count, 1)
            self.assertTrue(index.search("Bread", top_k=5))
            self.assertEqual(index.file_inventory()[0]["parse_state"], "lexical")

    def test_indexing_service_reuses_unchanged_extraction_unless_full(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scan = _scan("def alpha():\n    return beta()\n", content="reuse")
            scanner = _FixedScanner(scan)
            extractor = _CountingExtractor()
            index = SQLiteContextIndex(Path(directory) / "index.sqlite3")
            service = IndexRepositoryService(scanner, index, (extractor,))

            first = service.execute()
            unchanged = service.execute()
            self.assertEqual(extractor.calls, 1)
            self.assertEqual(unchanged.id, first.id)

            rebuilt = service.execute(full=True)
            self.assertEqual(extractor.calls, 2)
            self.assertNotEqual(rebuilt.id, first.id)

    def test_resolved_incoming_edge_powers_related_tests(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as data_dir:
            root = Path(source_dir)
            source_text = "def alpha():\n    return 1\n"
            test_text = "def test_alpha():\n    assert alpha() == 1\n"
            (root / "main.py").write_text(source_text)
            (root / "tests").mkdir()
            (root / "tests" / "test_main.py").write_text(test_text)
            scan = _multi_file_scan(
                root,
                {"main.py": source_text, "tests/test_main.py": test_text},
            )
            source_symbol = CodeSymbol(
                id="source-alpha",
                file_path="main.py",
                language="python",
                name="alpha",
                qualified_name="alpha",
                kind="function",
                line_start=1,
                line_end=2,
            )
            test_symbol = CodeSymbol(
                id="test-alpha",
                file_path="tests/test_main.py",
                language="python",
                name="test_alpha",
                qualified_name="test_alpha",
                kind="function",
                line_start=1,
                line_end=2,
                role="test",
            )
            test_edge = CodeEdge(
                id="test-calls-alpha",
                relation="calls",
                source_symbol_id=test_symbol.id,
                source_path="tests/test_main.py",
                target_symbol_id=None,
                target_name="alpha",
                evidence_line=2,
                confidence=0.8,
                method="test_ast",
                unresolved=True,
            )
            index = SQLiteContextIndex(Path(data_dir) / "index.sqlite3")
            index.build_generation(
                scan,
                {
                    "main.py": ExtractionResult(symbols=(source_symbol,)),
                    "tests/test_main.py": ExtractionResult(
                        symbols=(test_symbol,),
                        edges=(test_edge,),
                    ),
                },
            )
            services = RepoContextServices(_FixedScanner(scan), index)

            response = services.related_tests("alpha", top_k=5)

            results = response["data"]["results"]
            self.assertEqual(results[0]["path"], "tests/test_main.py")
            self.assertIn("calls", results[0]["basis"])


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _scan(text: str, *, content: str) -> ScanResult:
    digest = hashlib.sha256(text.encode()).hexdigest()
    snapshot = RepositorySnapshot(
        repository_id="repository",
        root="/authorized/repository",
        head=None,
        branch=None,
        dirty=True,
        worktree_fingerprint=f"worktree-{content}",
        content_fingerprint=f"content-{content}",
        schema_version=1,
        parser_version="tests",
        created_at=datetime.now(UTC).isoformat(),
    )
    return ScanResult(
        snapshot=snapshot,
        files=(
            FileRecord(
                path="src/main.py",
                language="python",
                content_hash=digest,
                size=len(text.encode()),
                git_status="M ",
                text=text,
                line_count=2,
            ),
        ),
        diagnostics=(
            Diagnostic(code="test_diagnostic", message="bounded diagnostic"),
        ),
    )


def _multi_file_scan(root: Path, contents: dict[str, str]) -> ScanResult:
    records = tuple(
        FileRecord(
            path=path,
            language="python",
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            size=len(text.encode()),
            git_status="filesystem",
            text=text,
            line_count=len(text.splitlines()),
        )
        for path, text in sorted(contents.items())
    )
    fingerprint = hashlib.sha256(
        "".join(f"{record.path}:{record.content_hash}\n" for record in records).encode()
    ).hexdigest()
    return ScanResult(
        snapshot=RepositorySnapshot(
            repository_id=hashlib.sha256(os.fsencode(str(root.resolve()))).hexdigest(),
            root=str(root),
            head=None,
            branch=None,
            dirty=False,
            worktree_fingerprint=fingerprint,
            content_fingerprint=fingerprint,
            schema_version=1,
            parser_version="tests",
            created_at=datetime.now(UTC).isoformat(),
        ),
        files=records,
    )


def _extraction(name: str) -> ExtractionResult:
    chunk = CodeChunk(
        id=f"chunk-{name}",
        file_path="src/main.py",
        language="python",
        line_start=1,
        line_end=2,
        content=f"def {name}():\n    return 1\n",
        kind="function",
        symbol_id=f"symbol-{name}",
    )
    symbol = CodeSymbol(
        id=f"symbol-{name}",
        file_path="src/main.py",
        language="python",
        name=name,
        qualified_name=f"main.{name}",
        kind="function",
        line_start=1,
        line_end=2,
        signature=f"def {name}()",
    )
    target = CodeSymbol(
        id="symbol-beta",
        file_path="src/main.py",
        language="python",
        name="beta",
        qualified_name="main.beta",
        kind="function",
        line_start=3,
        line_end=4,
        signature="def beta()",
    )
    edge = CodeEdge(
        id=f"edge-{name}",
        relation="calls",
        source_symbol_id=f"symbol-{name}",
        source_path="src/main.py",
        target_symbol_id=None,
        target_name="beta",
        evidence_line=2,
        confidence=0.75,
        method="test",
        unresolved=True,
    )
    return ExtractionResult(chunks=(chunk,), symbols=(symbol, target), edges=(edge,))


class _FixedScanner:
    def __init__(self, result: ScanResult) -> None:
        self._result = result
        self.root = Path(result.snapshot.root)

    def scan(self) -> ScanResult:
        return self._result


class _CountingExtractor:
    def __init__(self) -> None:
        self.calls = 0

    def supports(self, language: str) -> bool:
        return language == "python"

    def extract(self, file: FileRecord) -> ExtractionResult:
        self.calls += 1
        return _extraction("alpha")

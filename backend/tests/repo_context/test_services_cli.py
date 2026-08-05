from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from atenex_nova.repo_context.application.services import (
    RepoContextError,
    RepoContextServices,
    _focus_queries,
    _fuse_focus_hits,
)
from atenex_nova.repo_context.domain.models import (
    CodeEdge,
    CodeSymbol,
    GenerationInfo,
    RepositorySnapshot,
    ScanResult,
    SearchHit,
)
from atenex_nova.repo_context.presentation.cli import EXIT_MCP_UNAVAILABLE, main
from atenex_nova.repo_context.presentation.mcp_server import (
    TOOL_NAMES,
    McpUnavailableError,
    RepoContextToolHandler,
    run_stdio,
)


def _hash(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"


class FakeScanner:
    def __init__(self, root: Path, snapshot: RepositorySnapshot) -> None:
        self._root = root
        self.snapshot = snapshot

    @property
    def root(self) -> Path:
        return self._root

    def scan(self) -> ScanResult:
        return ScanResult(snapshot=self.snapshot, files=())


class FakeIndex:
    def __init__(
        self,
        root: Path,
        snapshot: RepositorySnapshot,
        source: str,
        test_source: str,
    ) -> None:
        self.database_path = root / ".atenex/context/index.sqlite3"
        self._texts = {
            "src/app.py": (source, _hash(source)),
            "tests/test_app.py": (test_source, _hash(test_source)),
        }
        self.target = CodeSymbol(
            id="target",
            file_path="src/app.py",
            language="python",
            name="target",
            qualified_name="src.app.target",
            kind="function",
            line_start=1,
            line_end=2,
            signature="def target() -> str",
        )
        self.caller = CodeSymbol(
            id="caller",
            file_path="src/app.py",
            language="python",
            name="caller",
            qualified_name="src.app.caller",
            kind="function",
            line_start=4,
            line_end=5,
            signature="def caller() -> str",
        )
        self.test = CodeSymbol(
            id="test",
            file_path="tests/test_app.py",
            language="python",
            name="test_target",
            qualified_name="tests.test_app.test_target",
            kind="test",
            line_start=3,
            line_end=4,
            signature="def test_target()",
        )
        self.call_edge = CodeEdge(
            id="call",
            relation="calls",
            source_symbol_id="caller",
            source_path="src/app.py",
            target_symbol_id="target",
            target_name="target",
            evidence_line=5,
            confidence=1.0,
            method="ast",
        )
        self.test_edge = CodeEdge(
            id="test-edge",
            relation="tests",
            source_symbol_id="test",
            source_path="tests/test_app.py",
            target_symbol_id="target",
            target_name="target",
            evidence_line=4,
            confidence=1.0,
            method="reference",
        )
        self._generation = GenerationInfo(
            id=7,
            state="active",
            snapshot=snapshot,
            file_count=2,
            symbol_count=3,
            chunk_count=4,
            edge_count=2,
            diagnostics_count=0,
            activated_at="2026-07-30T00:00:00Z",
        )

    def initialize(self) -> None:
        pass

    def active_generation(self) -> GenerationInfo:
        return self._generation

    def search(
        self,
        query: str,
        *,
        top_k: int,
        path_prefix: str | None = None,
        languages: Sequence[str] = (),
        symbol_kinds: Sequence[str] = (),
    ) -> list[SearchHit]:
        del query, top_k, path_prefix, languages, symbol_kinds
        return [
            SearchHit(
                kind="symbol",
                path="src/app.py",
                line_start=1,
                line_end=2,
                score=1.0,
                reason="symbol",
                content_hash=self._texts["src/app.py"][1],
                snippet="def target() -> str:",
                symbol=self.target,
                score_components={"symbol": 1.0},
            )
        ]

    def symbols(self, query: str, *, limit: int = 20) -> list[CodeSymbol]:
        del limit
        if query == "src/app.py":
            return [self.target, self.caller]
        if query in {"target", "src.app.target"}:
            return [self.target]
        if query == "duplicate":
            return [
                self.target,
                CodeSymbol(
                    id="other",
                    file_path="other.py",
                    language="python",
                    name="duplicate",
                    qualified_name="other.duplicate",
                    kind="function",
                    line_start=1,
                    line_end=1,
                ),
                CodeSymbol(
                    id="third",
                    file_path="third.py",
                    language="python",
                    name="duplicate",
                    qualified_name="third.duplicate",
                    kind="function",
                    line_start=1,
                    line_end=1,
                ),
            ]
        return []

    def symbols_for_path(
        self, path: str, *, limit: int = 200
    ) -> list[CodeSymbol]:
        del limit
        if path == "src/app.py":
            return [self.target, self.caller]
        if path == "tests/test_app.py":
            return [self.test]
        return []

    def symbol_by_id(self, symbol_id: str) -> CodeSymbol | None:
        return {"target": self.target, "caller": self.caller, "test": self.test}.get(
            symbol_id
        )

    def edges(
        self,
        symbol_id: str,
        *,
        direction: str,
        relations: Sequence[str] = (),
        limit: int = 100,
    ) -> list[CodeEdge]:
        del limit
        candidates = [self.call_edge, self.test_edge]
        if direction in {"dependents", "callers"}:
            candidates = [
                item for item in candidates if item.target_symbol_id == symbol_id
            ]
        else:
            candidates = [
                item for item in candidates if item.source_symbol_id == symbol_id
            ]
        if relations:
            candidates = [item for item in candidates if item.relation in relations]
        return candidates

    def file_text(self, path: str) -> tuple[str, str] | None:
        return self._texts.get(path)

    def file_inventory(self) -> list[dict[str, object]]:
        return [
            {
                "path": "src/app.py",
                "language": "python",
                "content_hash": self._texts["src/app.py"][1],
                "size": len(self._texts["src/app.py"][0]),
                "line_count": 5,
                "parse_state": "parsed",
            },
            {
                "path": "tests/test_app.py",
                "language": "python",
                "content_hash": self._texts["tests/test_app.py"][1],
                "size": len(self._texts["tests/test_app.py"][0]),
                "line_count": 4,
                "parse_state": "parsed",
            },
            {
                "path": "README.md",
                "language": "markdown",
                "content_hash": _hash("# Fixture\n"),
                "size": 10,
                "line_count": 1,
                "parse_state": "lexical",
            },
        ]

    def diagnostics(self, *, limit: int = 100) -> list[dict[str, object]]:
        del limit
        return []


def _make_fixture(
    tmp_path: Path,
) -> tuple[RepoContextServices, FakeScanner, FakeIndex]:
    source = (
        "def target() -> str:\n"
        '    return \"ok\"\n\n'
        "def caller() -> str:\n"
        "    return target()\n"
    )
    test_source = (
        "from src.app import target\n\n"
        "def test_target():\n"
        '    assert target() == \"ok\"\n'
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src/app.py").write_text(source)
    (tmp_path / "tests/test_app.py").write_text(test_source)
    snapshot = RepositorySnapshot(
        repository_id=hashlib.sha256(os.fsencode(str(tmp_path))).hexdigest(),
        root=str(tmp_path),
        head="a" * 40,
        branch="main",
        dirty=False,
        worktree_fingerprint="sha256:worktree",
        content_fingerprint="sha256:content",
        schema_version=1,
        parser_version="test",
        created_at="2026-07-30T00:00:00Z",
    )
    scanner = FakeScanner(tmp_path, snapshot)
    index = FakeIndex(tmp_path, snapshot, source, test_source)
    return RepoContextServices(scanner, index), scanner, index


class RepoContextServicesCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.services, self.scanner, self.index = _make_fixture(self.root)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_all_six_services_return_common_snapshot_envelope(self) -> None:
        responses = [
            self.services.repo_overview(focus="target"),
            self.services.search_repo("target"),
            self.services.get_symbol("target"),
            self.services.trace_symbol("target", direction="dependents"),
            self.services.analyze_impact("target"),
            self.services.related_tests("target"),
        ]
        for response in responses:
            self.assertEqual(response["repo"]["root"], ".")
            self.assertEqual(
                response["snapshot"],
                {
                    "generation": "7",
                    "head": "a" * 40,
                    "worktree_fingerprint": "sha256:worktree",
                    "stale": False,
                },
            )
            self.assertIsInstance(response["token_estimate"], int)
            self.assertIn("truncated", response)
            self.assertIn("diagnostics", response)

    def test_explicit_semantic_search_fails_when_not_configured(self) -> None:
        with self.assertRaises(RepoContextError) as captured:
            self.services.search_repo(
                "target", modes=["lexical", "semantic"], max_tokens=1_000
            )

        self.assertEqual(captured.exception.code, "SEMANTIC_UNAVAILABLE")

    def test_query_envelopes_do_not_repeat_persistent_index_diagnostics(self) -> None:
        with patch.object(
            self.index,
            "diagnostics",
            side_effect=AssertionError("query response loaded global diagnostics"),
        ):
            search = self.services.search_repo("target")
            overview = self.services.repo_overview(focus="target")

        self.assertEqual(search["diagnostics"], [])
        self.assertEqual(overview["diagnostics"], [])
        self.assertEqual(
            overview["data"]["summary"]["index_diagnostics"],
            self.index._generation.diagnostics_count,
        )

    def test_overview_decomposes_and_fuses_cross_layer_focus(self) -> None:
        focus = (
            "offline sale flow from POS/caja to API persistence, "
            "tenant and store isolation"
        )
        queries = _focus_queries(focus)
        self.assertEqual(queries[0], focus)
        self.assertIn(
            "offline outbox enqueue queue pending retry sync", queries
        )
        self.assertIn(
            "flow route endpoint handler service processor projector sync",
            queries,
        )
        self.assertIn(
            "tenant store isolation auth authorization guard rls policy",
            queries,
        )

        def hit(path: str, score: float) -> SearchHit:
            return SearchHit(
                kind="file",
                path=path,
                line_start=1,
                line_end=1,
                score=score,
                reason="fts5_any_term",
                content_hash="sha256:test",
                snippet=path,
            )

        fused = _fuse_focus_hits(
            [
                [hit("src/saleFlowMetrics.ts", 9.0), hit("src/salesStore.ts", 8.0)],
                [hit("src/outbox.ts", 7.0), hit("src/syncService.ts", 6.0)],
                [hit("src/processor.ts", 7.0), hit("src/projector.ts", 6.0)],
                [hit("src/projector.ts", 7.0), hit("src/processor.ts", 6.0)],
                [hit("src/routes/sync.ts", 7.0), hit("src/processor.ts", 6.0)],
            ],
            limit=10,
        )
        paths = [item.path for item in fused]
        self.assertLess(paths.index("src/processor.ts"), paths.index("src/saleFlowMetrics.ts"))
        self.assertLess(paths.index("src/projector.ts"), paths.index("src/saleFlowMetrics.ts"))
        self.assertEqual(fused[0].reason, "focus_rrf:fts5_any_term")

    def test_changed_file_is_not_returned_as_current_source(self) -> None:
        (self.root / "src/app.py").write_text("changed\n")
        response = self.services.get_symbol("target")
        self.assertEqual(response["data"]["source"], "")
        self.assertIn(
            "FILE_CHANGED_SINCE_INDEX",
            {item["code"] for item in response["diagnostics"]},
        )

    def test_stale_fingerprint_is_explicit(self) -> None:
        self.scanner.snapshot = RepositorySnapshot(
            **{
                **self.scanner.snapshot.to_dict(),
                "worktree_fingerprint": "sha256:new-worktree",
            }
        )
        response = self.services.repo_overview()
        self.assertTrue(response["snapshot"]["stale"])
        self.assertIn(
            "INDEX_STALE", {item["code"] for item in response["diagnostics"]}
        )

    def test_sidecar_bound_to_another_repository_is_rejected(self) -> None:
        mismatched_snapshot = RepositorySnapshot(
            **{
                **self.scanner.snapshot.to_dict(),
                "repository_id": "different-repository",
                "root": str(self.root / "other"),
            }
        )
        self.index._generation = GenerationInfo(
            **{
                **self.index._generation.to_dict(),
                "snapshot": mismatched_snapshot,
            }
        )

        with self.assertRaises(RepoContextError) as captured:
            self.services.repo_overview()
        self.assertEqual(captured.exception.code, "INDEX_UNAVAILABLE")
        status = self.services.status()
        self.assertFalse(status["core_available"])
        self.assertIn(
            "REPOSITORY_BINDING_MISMATCH",
            {item["code"] for item in status["diagnostics"]},
        )
        self.assertFalse(self.services.doctor()["healthy"])

    def test_generation_change_during_query_fails_closed(self) -> None:
        original_search = self.index.search

        def rotating_search(*args: object, **kwargs: object) -> list[SearchHit]:
            hits = original_search(*args, **kwargs)  # type: ignore[arg-type]
            self.index._generation = GenerationInfo(
                **{
                    **self.index._generation.to_dict(),
                    "id": self.index._generation.id + 1,
                }
            )
            return hits

        with (
            patch.object(self.index, "search", side_effect=rotating_search),
            self.assertRaises(RepoContextError) as captured,
        ):
            self.services.search_repo("target")
        self.assertEqual(captured.exception.code, "INDEX_UNAVAILABLE")

    def test_graph_impact_and_related_tests_are_evidence_grounded(self) -> None:
        trace = self.services.trace_symbol(
            "target", direction="dependents", depth=2
        )
        self.assertEqual(
            {item["id"] for item in trace["data"]["nodes"]}, {"caller", "test"}
        )
        self.assertEqual(
            {item["relation"] for item in trace["data"]["edges"]},
            {"calls", "tests"},
        )

        impact = self.services.analyze_impact("target")
        self.assertIn("src/app.py", impact["data"]["affected_files"])
        self.assertIn("tests/test_app.py", impact["data"]["affected_files"])

        path_impact = self.services.analyze_impact("src/app.py")
        self.assertEqual(path_impact["data"]["target"]["path"], "src/app.py")
        self.assertEqual(
            {item["id"] for item in path_impact["data"]["target"]["symbols"]},
            {"target", "caller"},
        )
        self.assertIn("src/app.py", path_impact["data"]["affected_files"])

        structural_impact = self.services.analyze_impact("README.md")
        self.assertEqual(structural_impact["data"]["target"]["symbols"], [])
        self.assertEqual(
            structural_impact["data"]["affected_files"], ["README.md"]
        )

        compact_impact = self.services.analyze_impact(
            "src/app.py", max_tokens=128
        )
        self.assertEqual(compact_impact["data"]["affected_files"], ["src/app.py"])

        both = self.services.trace_symbol("target", direction="both", depth=1)
        self.assertEqual(
            {item["id"] for item in both["data"]["nodes"]}, {"caller", "test"}
        )

        tests = self.services.related_tests("target")
        self.assertEqual(
            tests["data"]["results"][0]["path"], "tests/test_app.py"
        )
        self.assertEqual(tests["data"]["results"][0]["confidence"], 1.0)

    def test_handler_exposes_exactly_six_tools_and_bad_arguments(self) -> None:
        handler = RepoContextToolHandler(self.services)
        self.assertEqual(handler.tool_names, TOOL_NAMES)
        self.assertEqual(
            handler.call_tool("repo_overview", {})["snapshot"]["generation"], "7"
        )
        with self.assertRaises(RepoContextError) as captured:
            handler.call_tool("search_repo", {})
        self.assertEqual(captured.exception.code, "INVALID_ARGUMENT")
        with self.assertRaises(RepoContextError) as outside:
            handler.call_tool("get_symbol", {"symbol_or_path": "/etc/passwd"})
        self.assertEqual(outside.exception.code, "OUTSIDE_REPOSITORY")

    def test_cli_query_uses_same_services_and_json_stdout(self) -> None:
        runtime = SimpleNamespace(
            services=self.services,
            index_repository=lambda **kwargs: {"full": kwargs["full"]},
            tool_handler=lambda: RepoContextToolHandler(self.services),
        )

        def factory(**kwargs: object) -> object:
            self.assertEqual(Path(str(kwargs["repo"])), self.scanner.root)
            self.assertIsNone(kwargs["data_dir"])
            return runtime

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(
                [
                    "search",
                    "--repo",
                    str(self.scanner.root),
                    "--json",
                    "target",
                ],
                runtime_factory=factory,  # type: ignore[arg-type]
            )
        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            json.loads(stdout.getvalue())["data"]["results"][0]["id"],
            self.index.target.id,
        )

    def test_cli_serve_keeps_failure_on_stderr(self) -> None:
        runtime = SimpleNamespace(
            services=SimpleNamespace(ensure_ready=lambda: None),
            tool_handler=lambda: object(),
        )

        def unavailable(_: object) -> None:
            raise McpUnavailableError("mcp is absent")

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch(
                "atenex_nova.repo_context.presentation.cli.run_stdio",
                unavailable,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = main(
                ["serve", "--repo", str(self.root)],
                runtime_factory=lambda **_: runtime,  # type: ignore[arg-type]
            )
        self.assertEqual(result, EXIT_MCP_UNAVAILABLE)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            json.loads(stderr.getvalue())["error"]["code"],
            "MCP_UNAVAILABLE",
        )

    def test_stdio_adapter_registers_exactly_six_tools_lazily(self) -> None:
        class FakeMCPServer:
            instance: FakeMCPServer | None = None

            def __init__(self, *_: object, **__: object) -> None:
                self.names: list[str] = []
                self.transport: str | None = None
                FakeMCPServer.instance = self

            def tool(self) -> object:
                def decorator(function: object) -> object:
                    self.names.append(getattr(function, "__name__", ""))
                    return function

                return decorator

            def run(self, *, transport: str) -> None:
                self.transport = transport

        mcp_module = ModuleType("mcp")
        server_module = ModuleType("mcp.server")
        server_module.MCPServer = FakeMCPServer  # type: ignore[attr-defined]
        mcp_module.server = server_module  # type: ignore[attr-defined]
        modules = {
            "mcp": mcp_module,
            "mcp.server": server_module,
        }
        with patch.dict(sys.modules, modules):
            run_stdio(RepoContextToolHandler(self.services))
        instance = FakeMCPServer.instance
        self.assertIsNotNone(instance)
        assert instance is not None
        self.assertEqual(tuple(instance.names), TOOL_NAMES)
        self.assertEqual(instance.transport, "stdio")

    @unittest.skipUnless(
        importlib.util.find_spec("mcp") is not None,
        "official MCP SDK is an optional dependency",
    )
    def test_official_mcp_client_lists_and_calls_tools(self) -> None:
        import anyio
        from mcp import ClientSession
        from mcp.shared.message import SessionMessage

        from atenex_nova.repo_context.presentation.mcp_server import (
            _create_mcp_server,
        )

        async def exercise_protocol() -> None:
            server = _create_mcp_server(RepoContextToolHandler(self.services))
            lowlevel = server._lowlevel_server
            client_send, server_receive = anyio.create_memory_object_stream[
                SessionMessage
            ](8)
            server_send, client_receive = anyio.create_memory_object_stream[
                SessionMessage
            ](8)
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(
                    lowlevel.run,
                    server_receive,
                    server_send,
                    lowlevel.create_initialization_options(),
                )
                async with ClientSession(
                    client_receive,
                    client_send,
                    read_timeout_seconds=5,
                ) as session:
                    initialized = await session.initialize()
                    tools = await session.list_tools()
                    result = await session.call_tool(
                        "get_symbol",
                        {"symbol_or_path": "target", "include_source": False},
                    )
                    self.assertEqual(initialized.server_info.name, "atenex-context")
                    self.assertEqual(
                        tuple(tool.name for tool in tools.tools),
                        TOOL_NAMES,
                    )
                    self.assertFalse(result.is_error)
                    self.assertIsNotNone(result.structured_content)
                    assert result.structured_content is not None
                    self.assertEqual(
                        result.structured_content["data"]["name"],
                        "target",
                    )
                await client_send.aclose()
                task_group.cancel_scope.cancel()

        anyio.run(exercise_protocol)


if __name__ == "__main__":
    unittest.main()

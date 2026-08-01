from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from scripts.evaluate_repo_context import (
    SUPPORTED_TOOLS,
    evaluate_manifest,
    extract_ranked_paths,
    main,
    parse_mappings,
)


def _envelope(data: dict[str, Any], *, stale: bool = False) -> dict[str, Any]:
    return {
        "snapshot": {"stale": stale},
        "data": data,
    }


class FakeServices:
    def __init__(self, *, miss: bool = False) -> None:
        self.miss = miss

    def repo_overview(self, **_: object) -> dict[str, Any]:
        path = "wrong.py" if self.miss else "overview.py"
        return _envelope(
            {
                "focus_results": [{"path": path}],
                "repo_map": {"entries": [{"path": "map.py"}]},
                "landmarks": [{"path": "README.md"}],
            }
        )

    def search_repo(self, _: str, **__: object) -> dict[str, Any]:
        path = "wrong.py" if self.miss else "search.py"
        return _envelope({"results": [{"path": path}]})

    def get_symbol(self, _: str, **__: object) -> dict[str, Any]:
        path = "wrong.py" if self.miss else "symbol.py"
        return _envelope({"type": "symbol", "file_path": path})

    def trace_symbol(self, _: str, **__: object) -> dict[str, Any]:
        path = "wrong.py" if self.miss else "trace.py"
        return _envelope(
            {
                "root": {"file_path": path},
                "nodes": [{"file_path": "trace-dependent.py"}],
                "edges": [{"source_path": "trace-edge.py"}],
            }
        )

    def analyze_impact(self, _: str, **__: object) -> dict[str, Any]:
        path = "wrong.py" if self.miss else "impact.py"
        test_path = "wrong-test.py" if self.miss else "impact-test.py"
        return _envelope(
            {
                "target": {"symbols": [{"file_path": path}]},
                "affected_symbols": [{"file_path": "impact-symbol.py"}],
                "affected_files": ["impact-file.py"],
                "related_tests": [{"path": test_path}],
                "relations": [{"source_path": "impact-edge.py"}],
            }
        )

    def related_tests(self, _: str, **__: object) -> dict[str, Any]:
        path = "wrong.py" if self.miss else "tests/test_related.py"
        return _envelope({"results": [{"path": path}]})


class FakeRuntime:
    def __init__(self, *, miss: bool = False) -> None:
        self.services = FakeServices(miss=miss)
        self.index_calls: list[bool] = []

    def index_repository(self, *, full: bool = False) -> dict[str, Any]:
        self.index_calls.append(full)
        return {"generation": "1", "full": full}


class EvaluationRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.manifest = self.root / "acceptance.json"
        queries = [
            {
                "tool": "repo_overview",
                "query": "overview",
                "expected_paths": ["overview.py"],
            },
            {
                "tool": "search_repo",
                "query": "search",
                "expected_paths": ["search.py"],
            },
            {
                "tool": "get_symbol",
                "query": "symbol",
                "expected_paths": ["symbol.py"],
            },
            {
                "tool": "trace_symbol",
                "query": "trace",
                "expected_paths": ["trace.py"],
            },
            {
                "tool": "analyze_impact",
                "query": "impact",
                "expected_paths": ["impact.py", "impact-test.py"],
            },
            {
                "tool": "related_tests",
                "query": "related",
                "expected_paths": ["tests/test_related.py"],
            },
        ]
        self.manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "repositories": [
                        {
                            "id": "fixture",
                            "root_hint": ".",
                            "queries": queries,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_all_six_tools_are_scored_with_stable_metrics(self) -> None:
        runtime = FakeRuntime()
        report = evaluate_manifest(
            self.manifest,
            repo_overrides={"fixture": self.root},
            data_dir_overrides={"fixture": self.root / "index"},
            reindex=True,
            full=True,
            runtime_factory=lambda **_: runtime,  # type: ignore[arg-type]
        )
        self.assertEqual(set(SUPPORTED_TOOLS), {
            item["tool"]
            for item in report["repositories"][0]["queries"]
        })
        self.assertEqual(runtime.index_calls, [True])
        self.assertEqual(report["summary"]["queries"], 6)
        self.assertEqual(report["summary"]["hits"], 6)
        self.assertEqual(report["summary"]["failures"], 0)
        self.assertEqual(report["summary"]["hit_rate"], 1.0)
        self.assertEqual(report["summary"]["mrr"], 1.0)
        self.assertEqual(report["summary"]["mean_recall_at_k"], 1.0)
        self.assertEqual(report["summary"]["zero_result_queries"], 0)
        self.assertEqual(report["summary"]["truncated_queries"], 0)
        self.assertEqual(report["summary"]["diagnostics"], 0)
        self.assertEqual(report["summary"]["mean_response_tokens"], 0.0)
        self.assertTrue(
            all(
                query["result_count"] > 0
                for query in report["repositories"][0]["queries"]
            )
        )
        repeated = evaluate_manifest(
            self.manifest,
            repo_overrides={"fixture": self.root},
            data_dir_overrides={"fixture": self.root / "index"},
            runtime_factory=lambda **_: FakeRuntime(),  # type: ignore[arg-type]
        )
        first_without_index = {
            **report,
            "repositories": [
                {
                    **report["repositories"][0],
                    "reindexed": False,
                    "index": None,
                }
            ],
        }
        self.assertEqual(
            json.dumps(first_without_index, sort_keys=True),
            json.dumps(repeated, sort_keys=True),
        )

    def test_path_extraction_preserves_tool_ranking_and_deduplicates(self) -> None:
        response = _envelope(
            {
                "root": {"file_path": "a.py"},
                "nodes": [{"file_path": "b.py"}, {"file_path": "a.py"}],
                "edges": [{"source_path": "c.py"}],
            }
        )
        self.assertEqual(
            extract_ranked_paths("trace_symbol", response),
            ["a.py", "b.py", "c.py"],
        )

    def test_cli_returns_one_for_golden_miss_and_two_for_bad_mapping(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(
                [
                    "--manifest",
                    str(self.manifest),
                    "--repo",
                    f"fixture={self.root}",
                    "--data-dir",
                    f"fixture={self.root / 'index'}",
                ],
                runtime_factory=(
                    lambda **_: FakeRuntime(miss=True)  # type: ignore[arg-type]
                ),
            )
        self.assertEqual(result, 1)
        self.assertEqual(stderr.getvalue(), "")
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["summary"]["failures"], 6)

        with self.assertRaises(ValueError):
            parse_mappings(["invalid"], option="--repo")

        bad_stdout = io.StringIO()
        bad_stderr = io.StringIO()
        with redirect_stdout(bad_stdout), redirect_stderr(bad_stderr):
            bad_result = main(["--repo", "invalid"])
        self.assertEqual(bad_result, 2)
        self.assertEqual(bad_stdout.getvalue(), "")
        self.assertEqual(
            json.loads(bad_stderr.getvalue())["error"]["code"],
            "EVALUATION_CONFIGURATION_ERROR",
        )


if __name__ == "__main__":
    unittest.main()

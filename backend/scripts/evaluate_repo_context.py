"""Reproducible golden evaluation for Repo Context application services."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from atenex_nova.repo_context.application.services import (  # noqa: E402
    RepoContextError,
)
from atenex_nova.repo_context.composition import (  # noqa: E402
    RepoContextRuntime,
    build_runtime,
)

DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "repo_context"
    / "goldens"
    / "acceptance.json"
)
SUPPORTED_TOOLS = frozenset(
    {
        "repo_overview",
        "search_repo",
        "get_symbol",
        "trace_symbol",
        "analyze_impact",
        "related_tests",
    }
)
RuntimeFactory = Callable[..., RepoContextRuntime]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate Repo Context services against a frozen golden manifest."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        metavar="ID=PATH",
        help="override a repository root; repeat per repository",
    )
    parser.add_argument(
        "--data-dir",
        action="append",
        default=[],
        metavar="ID=PATH",
        help="override derived index data; repeat per repository",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="build an index generation before evaluating each repository",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="request a full rebuild; only meaningful with --reindex",
    )
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument(
        "--output",
        type=Path,
        help="write JSON to this file instead of stdout",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runtime_factory: RuntimeFactory = build_runtime,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.full and not args.reindex:
            raise ValueError("--full requires --reindex")
        if not 1 <= args.top_k <= 200:
            raise ValueError("--top-k must be between 1 and 200")
        report = evaluate_manifest(
            args.manifest,
            repo_overrides=parse_mappings(args.repo, option="--repo"),
            data_dir_overrides=parse_mappings(
                args.data_dir, option="--data-dir"
            ),
            reindex=args.reindex,
            full=args.full,
            top_k=args.top_k,
            runtime_factory=runtime_factory,
        )
        serialized = json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        if args.output:
            args.output.expanduser().resolve().write_text(
                f"{serialized}\n", encoding="utf-8"
            )
        else:
            sys.stdout.write(f"{serialized}\n")
        return 0 if report["summary"]["failures"] == 0 else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(
            json.dumps(
                {
                    "error": {
                        "code": "EVALUATION_CONFIGURATION_ERROR",
                        "message": str(exc),
                    }
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        return 2
    except Exception as exc:  # pragma: no cover - process safety boundary
        sys.stderr.write(
            json.dumps(
                {
                    "error": {
                        "code": "EVALUATION_RUNTIME_ERROR",
                        "message": f"{type(exc).__name__}: {exc}",
                    }
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        return 2


def evaluate_manifest(
    manifest_path: Path,
    *,
    repo_overrides: Mapping[str, Path] | None = None,
    data_dir_overrides: Mapping[str, Path] | None = None,
    reindex: bool = False,
    full: bool = False,
    top_k: int = 20,
    runtime_factory: RuntimeFactory = build_runtime,
) -> dict[str, Any]:
    """Evaluate every manifest query and return a deterministic report."""

    manifest_path = manifest_path.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_manifest(manifest)
    repo_map = dict(repo_overrides or {})
    data_map = dict(data_dir_overrides or {})
    repository_reports: list[dict[str, Any]] = []

    for repository in manifest["repositories"]:
        repository_id = str(repository["id"])
        root = _resolve_repository_root(
            repository,
            manifest_path=manifest_path,
            override=repo_map.get(repository_id),
        )
        data_dir = (
            data_map[repository_id].expanduser().resolve()
            if repository_id in data_map
            else root / ".atenex" / "context"
        )
        runtime = runtime_factory(repo=root, data_dir=data_dir)
        index_result: dict[str, Any] | None = None
        repository_error: dict[str, str] | None = None
        if reindex:
            try:
                index_result = runtime.index_repository(full=full)
            except Exception as exc:
                repository_error = _error_payload(exc)

        query_reports: list[dict[str, Any]] = []
        for query in repository["queries"]:
            if repository_error is not None:
                query_reports.append(
                    _failed_query_report(
                        query,
                        top_k=top_k,
                        error=repository_error,
                    )
                )
                continue
            query_reports.append(evaluate_query(runtime, query, top_k=top_k))
        repository_reports.append(
            {
                "id": repository_id,
                "reindexed": reindex,
                "index": _redact_local_paths(index_result),
                "queries": query_reports,
            }
        )

    query_reports = [
        query
        for repository in repository_reports
        for query in repository["queries"]
    ]
    failures = sum(
        1
        for query in query_reports
        if query["error"] is not None or query["stale"] or not query["hit"]
    )
    count = len(query_reports)
    return {
        "schema_version": 1,
        "manifest_schema_version": int(manifest["schema_version"]),
        "top_k": top_k,
        "repositories": repository_reports,
        "summary": {
            "queries": count,
            "hits": sum(1 for query in query_reports if query["hit"]),
            "failures": failures,
            "hit_rate": _mean(
                [1.0 if query["hit"] else 0.0 for query in query_reports]
            ),
            "mrr": _mean(
                [float(query["reciprocal_rank"]) for query in query_reports]
            ),
            "mean_recall_at_k": _mean(
                [float(query["recall_at_k"]) for query in query_reports]
            ),
            "zero_result_queries": sum(
                1 for query in query_reports if int(query["result_count"]) == 0
            ),
            "truncated_queries": sum(
                1 for query in query_reports if bool(query["truncated"])
            ),
            "diagnostics": sum(
                int(query["diagnostic_count"]) for query in query_reports
            ),
            "mean_response_tokens": _mean(
                [
                    float(query["response_token_estimate"])
                    for query in query_reports
                ]
            ),
        },
    }


def evaluate_query(
    runtime: RepoContextRuntime,
    query: Mapping[str, Any],
    *,
    top_k: int,
) -> dict[str, Any]:
    """Invoke one service and score its ranked repository-relative paths."""

    tool = str(query.get("tool", ""))
    query_text = str(query.get("query", "")).strip()
    expected = _unique_paths(query.get("expected_paths", []))
    if tool not in SUPPORTED_TOOLS:
        return _failed_query_report(
            query,
            top_k=top_k,
            error={
                "code": "UNSUPPORTED_TOOL",
                "message": f"unsupported tool in manifest: {tool}",
            },
        )
    try:
        response = invoke_tool(
            runtime,
            tool=tool,
            query=query_text,
            arguments=query.get("arguments", {}),
            top_k=top_k,
        )
        ranked = extract_ranked_paths(tool, response)
        stale = bool(response.get("snapshot", {}).get("stale", False))
        scored = _score_query(
            tool=tool,
            query=query_text,
            expected_paths=expected,
            ranked_paths=ranked,
            top_k=top_k,
            stale=stale,
            error=None,
        )
        diagnostics = response.get("diagnostics", [])
        return {
            **scored,
            "result_count": len(ranked),
            "response_token_estimate": int(response.get("token_estimate", 0)),
            "diagnostic_count": (
                len(diagnostics) if isinstance(diagnostics, list) else 0
            ),
            "truncated": bool(response.get("truncated", False)),
        }
    except Exception as exc:
        return _failed_query_report(
            query,
            top_k=top_k,
            error=_error_payload(exc),
        )


def invoke_tool(
    runtime: RepoContextRuntime,
    *,
    tool: str,
    query: str,
    arguments: object,
    top_k: int,
) -> dict[str, Any]:
    """Dispatch to the same application services used by CLI and MCP."""

    kwargs = dict(arguments) if isinstance(arguments, dict) else {}
    services = runtime.services
    if tool == "repo_overview":
        kwargs.setdefault("focus", query)
        kwargs.setdefault("max_tokens", 16_000)
        return services.repo_overview(**kwargs)
    if tool == "search_repo":
        kwargs.setdefault("top_k", top_k)
        kwargs.setdefault("max_tokens", 16_000)
        return services.search_repo(query, **kwargs)
    if tool == "get_symbol":
        kwargs.setdefault("include_source", False)
        kwargs.setdefault("max_tokens", 16_000)
        return services.get_symbol(query, **kwargs)
    if tool == "trace_symbol":
        kwargs.setdefault("direction", "dependents")
        kwargs.setdefault("depth", 2)
        kwargs.setdefault("max_nodes", max(50, top_k))
        kwargs.setdefault("max_tokens", 16_000)
        return services.trace_symbol(query, **kwargs)
    if tool == "analyze_impact":
        kwargs.setdefault("depth", 2)
        kwargs.setdefault("max_nodes", max(100, top_k))
        kwargs.setdefault("max_tokens", 16_000)
        return services.analyze_impact(query, **kwargs)
    if tool == "related_tests":
        kwargs.setdefault("top_k", top_k)
        kwargs.setdefault("max_tokens", 16_000)
        return services.related_tests(query, **kwargs)
    raise ValueError(f"unsupported tool: {tool}")


def extract_ranked_paths(
    tool: str,
    response: Mapping[str, Any],
) -> list[str]:
    """Normalize each tool payload into one deterministic path ranking."""

    data = response.get("data", {})
    if not isinstance(data, dict):
        return []
    candidates: list[object] = []
    if tool == "repo_overview":
        candidates.extend(_paths_from_records(data.get("focus_results")))
        repo_map = data.get("repo_map", {})
        if isinstance(repo_map, dict):
            candidates.extend(_paths_from_records(repo_map.get("entries")))
        candidates.extend(_paths_from_records(data.get("landmarks")))
    elif tool == "search_repo":
        candidates.extend(_paths_from_records(data.get("results")))
    elif tool == "get_symbol":
        if data.get("type") == "candidates":
            candidates.extend(_paths_from_records(data.get("candidates")))
        else:
            candidates.append(data.get("file_path") or data.get("path"))
    elif tool == "trace_symbol":
        root = data.get("root", {})
        if isinstance(root, dict):
            candidates.append(root.get("file_path") or root.get("path"))
        candidates.extend(_paths_from_records(data.get("nodes")))
        candidates.extend(
            _paths_from_records(data.get("edges"), key="source_path")
        )
    elif tool == "analyze_impact":
        target = data.get("target", {})
        if isinstance(target, dict):
            candidates.extend(_paths_from_records(target.get("symbols")))
        candidates.extend(_paths_from_records(data.get("related_tests")))
        candidates.extend(_paths_from_records(data.get("affected_symbols")))
        affected = data.get("affected_files", [])
        if isinstance(affected, list):
            candidates.extend(affected)
        candidates.extend(
            _paths_from_records(data.get("relations"), key="source_path")
        )
    elif tool == "related_tests":
        candidates.extend(_paths_from_records(data.get("results")))
    return _unique_paths(candidates)


def parse_mappings(values: Sequence[str], *, option: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        identifier, separator, raw_path = value.partition("=")
        if not separator or not identifier.strip() or not raw_path.strip():
            raise ValueError(f"{option} expects ID=PATH, got {value!r}")
        identifier = identifier.strip()
        if identifier in result:
            raise ValueError(f"duplicate {option} mapping for {identifier!r}")
        result[identifier] = Path(raw_path.strip())
    return result


def _score_query(
    *,
    tool: str,
    query: str,
    expected_paths: Sequence[str],
    ranked_paths: Sequence[str],
    top_k: int,
    stale: bool,
    error: dict[str, str] | None,
) -> dict[str, Any]:
    expected = list(expected_paths)
    ranked = list(ranked_paths)
    bounded = ranked[:top_k]
    expected_set = set(expected)
    matches = [path for path in bounded if path in expected_set]
    first_rank = next(
        (
            index
            for index, path in enumerate(ranked, start=1)
            if path in expected_set
        ),
        None,
    )
    return {
        "tool": tool,
        "query": query,
        "expected_paths": expected,
        "ranked_paths": ranked,
        "matched_paths": matches,
        "top_k": top_k,
        "hit": bool(matches),
        "first_relevant_rank": first_rank,
        "reciprocal_rank": (
            round(1.0 / first_rank, 8) if first_rank is not None else 0.0
        ),
        "recall_at_k": (
            round(len(set(matches)) / len(expected_set), 8)
            if expected_set
            else 0.0
        ),
        "stale": stale,
        "error": error,
    }


def _failed_query_report(
    query: Mapping[str, Any],
    *,
    top_k: int,
    error: dict[str, str],
) -> dict[str, Any]:
    return {
        **_score_query(
        tool=str(query.get("tool", "")),
        query=str(query.get("query", "")),
        expected_paths=_unique_paths(query.get("expected_paths", [])),
        ranked_paths=[],
        top_k=top_k,
        stale=False,
        error=error,
        ),
        "result_count": 0,
        "response_token_estimate": 0,
        "diagnostic_count": 0,
        "truncated": False,
    }


def _paths_from_records(
    value: object,
    *,
    key: str = "path",
) -> list[object]:
    if not isinstance(value, list):
        return []
    return [
        item.get(key) or (item.get("file_path") if key == "path" else None)
        for item in value
        if isinstance(item, dict)
        and (item.get(key) or (item.get("file_path") if key == "path" else None))
    ]


def _unique_paths(values: object) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        path = value.replace("\\", "/")
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _resolve_repository_root(
    repository: Mapping[str, Any],
    *,
    manifest_path: Path,
    override: Path | None,
) -> Path:
    if override is not None:
        root = override.expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"repository root does not exist: {root}")
        return root
    hint = Path(str(repository.get("root_hint", ""))).expanduser()
    if hint.is_absolute():
        root = hint.resolve()
        if not root.is_dir():
            raise ValueError(f"repository root does not exist: {root}")
        return root

    expected = [
        path
        for query in repository.get("queries", [])
        for path in query.get("expected_paths", [])
        if isinstance(path, str)
    ]
    candidates = [
        (manifest_path.parent / hint).resolve(),
        *(parent.resolve() for parent in manifest_path.parents),
    ]
    for candidate in candidates:
        if candidate.is_dir() and any(
            (candidate / path).exists() for path in expected
        ):
            return candidate
    raise ValueError(
        f"cannot resolve repository {repository.get('id')!r}; "
        "pass --repo ID=PATH"
    )


def _validate_manifest(manifest: object) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("manifest root must be an object")
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported manifest schema_version")
    repositories = manifest.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise ValueError("manifest repositories must be a non-empty array")
    identifiers: set[str] = set()
    for repository in repositories:
        if not isinstance(repository, dict):
            raise ValueError("repository entries must be objects")
        identifier = repository.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("repository id must be a non-empty string")
        if identifier in identifiers:
            raise ValueError(f"duplicate repository id: {identifier}")
        identifiers.add(identifier)
        queries = repository.get("queries")
        if not isinstance(queries, list) or not queries:
            raise ValueError(f"repository {identifier!r} has no queries")
        for query in queries:
            if not isinstance(query, dict):
                raise ValueError("query entries must be objects")
            if query.get("tool") not in SUPPORTED_TOOLS:
                raise ValueError(f"unsupported tool: {query.get('tool')!r}")
            text = query.get("query")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("query text must be a non-empty string")
            expected = query.get("expected_paths")
            if not isinstance(expected, list) or not expected:
                raise ValueError("expected_paths must be a non-empty array")


def _error_payload(exc: Exception) -> dict[str, str]:
    if isinstance(exc, RepoContextError):
        return {"code": exc.code, "message": exc.message}
    return {"code": type(exc).__name__, "message": str(exc)}


def _redact_local_paths(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    sanitized = dict(result)
    if "database" in sanitized:
        sanitized["database"] = "index.sqlite3"
    return sanitized


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 8) if values else 0.0


if __name__ == "__main__":
    raise SystemExit(main())

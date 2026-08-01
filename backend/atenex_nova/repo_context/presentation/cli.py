"""Command-line interface for the local Repo Context engine."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from atenex_nova.repo_context.application.services import RepoContextError
from atenex_nova.repo_context.composition import RepoContextRuntime, build_runtime
from atenex_nova.repo_context.presentation.mcp_server import (
    McpUnavailableError,
    run_stdio,
)

RuntimeFactory = Callable[..., RepoContextRuntime]

EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_INDEX_UNAVAILABLE = 3
EXIT_PATH_POLICY = 4
EXIT_AMBIGUOUS = 5
EXIT_MCP_UNAVAILABLE = 6


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atenex-context",
        description="Local, read-only repository intelligence for coding agents.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="build an index generation")
    _add_repository_arguments(index_parser)
    index_parser.add_argument(
        "--full", action="store_true", help="request a full rebuild"
    )
    index_parser.add_argument("--json", action="store_true", dest="as_json")

    serve_parser = subparsers.add_parser("serve", help="serve the six MCP tools")
    _add_repository_arguments(serve_parser)
    serve_parser.add_argument("--transport", choices=("stdio",), default="stdio")
    serve_parser.add_argument(
        "--stdio",
        action="store_true",
        help="compatibility alias for --transport stdio",
    )

    status_parser = subparsers.add_parser("status", help="inspect index freshness")
    _add_repository_arguments(status_parser)
    status_parser.add_argument("--json", action="store_true", dest="as_json")

    doctor_parser = subparsers.add_parser("doctor", help="run non-destructive checks")
    _add_repository_arguments(doctor_parser)
    doctor_parser.add_argument("--json", action="store_true", dest="as_json")

    overview_parser = subparsers.add_parser(
        "overview", help="show a bounded repository map"
    )
    _add_repository_arguments(overview_parser)
    overview_parser.add_argument("--focus")
    _add_output_arguments(overview_parser)

    search_parser = subparsers.add_parser(
        "search", help="search indexed repository facts"
    )
    _add_repository_arguments(search_parser)
    search_parser.add_argument("query")
    search_parser.add_argument(
        "--mode",
        dest="modes",
        action="append",
        choices=("lexical", "symbol", "semantic"),
    )
    search_parser.add_argument("--top-k", type=int, default=20)
    search_parser.add_argument("--path-prefix")
    search_parser.add_argument("--language", dest="languages", action="append")
    search_parser.add_argument("--symbol-kind", dest="symbol_kinds", action="append")
    _add_output_arguments(search_parser)

    symbol_parser = subparsers.add_parser(
        "symbol", help="resolve a symbol or source path"
    )
    _add_repository_arguments(symbol_parser)
    symbol_parser.add_argument("symbol_or_path")
    symbol_parser.add_argument(
        "--no-source", action="store_false", dest="include_source"
    )
    symbol_parser.set_defaults(include_source=True)
    _add_output_arguments(symbol_parser)

    trace_parser = subparsers.add_parser(
        "trace", help="traverse static symbol relations"
    )
    _add_repository_arguments(trace_parser)
    trace_parser.add_argument("symbol")
    trace_parser.add_argument(
        "--direction",
        required=True,
        choices=("callers", "callees", "dependencies", "dependents"),
    )
    trace_parser.add_argument("--depth", type=int, default=1)
    trace_parser.add_argument("--relation", dest="relations", action="append")
    trace_parser.add_argument("--max-nodes", type=int, default=50)
    _add_output_arguments(trace_parser)

    impact_parser = subparsers.add_parser(
        "impact", help="find static change-impact candidates"
    )
    _add_repository_arguments(impact_parser)
    impact_parser.add_argument("symbol_or_path")
    impact_parser.add_argument("--depth", type=int, default=2)
    impact_parser.add_argument("--max-nodes", type=int, default=100)
    _add_output_arguments(impact_parser)

    tests_parser = subparsers.add_parser("tests", help="find related tests")
    _add_repository_arguments(tests_parser)
    tests_parser.add_argument("symbol_or_path")
    tests_parser.add_argument("--top-k", type=int, default=20)
    _add_output_arguments(tests_parser)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runtime_factory: RuntimeFactory = build_runtime,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        runtime = runtime_factory(
            repo=Path(args.repo),
            data_dir=Path(args.data_dir) if args.data_dir else None,
        )
        result = _dispatch(args, runtime)
        if result is not None:
            _write_result(result, as_json=bool(getattr(args, "as_json", False)))
        return 0
    except RepoContextError as exc:
        _write_error(exc.to_dict())
        return _error_exit_code(exc.code)
    except McpUnavailableError as exc:
        _write_error(
            {
                "error": {
                    "code": "MCP_UNAVAILABLE",
                    "message": str(exc),
                    "details": {},
                }
            }
        )
        return EXIT_MCP_UNAVAILABLE
    except (OSError, ValueError) as exc:
        _write_error(
            {
                "error": {
                    "code": "INVALID_ARGUMENT",
                    "message": str(exc),
                    "details": {},
                }
            }
        )
        return EXIT_USAGE
    except Exception as exc:  # pragma: no cover - final process boundary
        _write_error(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"{type(exc).__name__}: {exc}",
                    "details": {},
                }
            }
        )
        return EXIT_INTERNAL


def _dispatch(
    args: argparse.Namespace, runtime: RepoContextRuntime
) -> dict[str, Any] | None:
    services = runtime.services
    if args.command == "index":
        return runtime.index_repository(full=args.full)
    if args.command == "serve":
        services.ensure_ready()
        run_stdio(runtime.tool_handler())
        return None
    if args.command == "status":
        return services.status()
    if args.command == "doctor":
        return services.doctor()
    if args.command == "overview":
        return services.repo_overview(focus=args.focus, max_tokens=args.max_tokens)
    if args.command == "search":
        return services.search_repo(
            args.query,
            modes=args.modes,
            top_k=args.top_k,
            path_prefix=args.path_prefix,
            languages=args.languages,
            symbol_kinds=args.symbol_kinds,
            max_tokens=args.max_tokens,
        )
    if args.command == "symbol":
        return services.get_symbol(
            args.symbol_or_path,
            include_source=args.include_source,
            max_tokens=args.max_tokens,
        )
    if args.command == "trace":
        return services.trace_symbol(
            args.symbol,
            direction=args.direction,
            depth=args.depth,
            relations=args.relations,
            max_nodes=args.max_nodes,
            max_tokens=args.max_tokens,
        )
    if args.command == "impact":
        return services.analyze_impact(
            args.symbol_or_path,
            depth=args.depth,
            max_nodes=args.max_nodes,
            max_tokens=args.max_tokens,
        )
    if args.command == "tests":
        return services.related_tests(
            args.symbol_or_path,
            top_k=args.top_k,
            max_tokens=args.max_tokens,
        )
    raise RepoContextError("INVALID_ARGUMENT", f"unsupported command: {args.command}")


def _add_repository_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", required=True, help="fixed repository root")
    parser.add_argument("--data-dir", help="derived sidecar directory")


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-tokens", type=int, default=4_000)
    parser.add_argument("--json", action="store_true", dest="as_json")


def _write_result(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
        return
    sys.stdout.write(_human_result(result) + "\n")


def _human_result(result: dict[str, Any]) -> str:
    if "snapshot" in result and "data" in result:
        snapshot = result["snapshot"]
        lines = [
            f"repository: {result['repo']['name']}",
            f"generation: {snapshot['generation']}",
            f"stale: {str(snapshot['stale']).lower()}",
            f"truncated: {str(result.get('truncated', False)).lower()}",
        ]
        lines.append(json.dumps(result["data"], ensure_ascii=False, indent=2))
        if result.get("diagnostics"):
            lines.append(
                "diagnostics: "
                + ", ".join(
                    str(item.get("code", "NOTICE"))
                    for item in result["diagnostics"]
                )
            )
        return "\n".join(lines)
    return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)


def _write_error(error: dict[str, Any]) -> None:
    sys.stderr.write(json.dumps(error, ensure_ascii=False, sort_keys=True) + "\n")


def _error_exit_code(code: str) -> int:
    return {
        "INVALID_ARGUMENT": EXIT_USAGE,
        "INDEX_UNAVAILABLE": EXIT_INDEX_UNAVAILABLE,
        "OUTSIDE_REPOSITORY": EXIT_PATH_POLICY,
        "AMBIGUOUS": EXIT_AMBIGUOUS,
        "SEMANTIC_UNAVAILABLE": EXIT_USAGE,
    }.get(code, EXIT_INTERNAL)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

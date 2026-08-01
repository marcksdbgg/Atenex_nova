"""Read-only MCP stdio adapter.

The direct handler has no dependency on the MCP SDK and is the primary adapter
contract used by tests.  SDK imports occur only when a server is actually
started, so indexing and CLI queries remain core-only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from atenex_nova.repo_context.application.services import (
    DEFAULT_MAX_TOKENS,
    RepoContextError,
    RepoContextServices,
)

TOOL_NAMES = (
    "repo_overview",
    "search_repo",
    "get_symbol",
    "trace_symbol",
    "analyze_impact",
    "related_tests",
)


class McpUnavailableError(RuntimeError):
    """Raised when serve is requested without the optional MCP SDK."""


class RepoContextToolHandler:
    """Testable, SDK-independent dispatch for exactly six read-only tools."""

    def __init__(self, services: RepoContextServices) -> None:
        self._services = services

    @property
    def tool_names(self) -> tuple[str, ...]:
        return TOOL_NAMES

    def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        if name not in TOOL_NAMES:
            raise RepoContextError("NOT_FOUND", f"unknown MCP tool: {name}")
        kwargs = dict(arguments or {})
        method = getattr(self, name)
        try:
            result = method(**kwargs)
        except TypeError as exc:
            raise RepoContextError(
                "INVALID_ARGUMENT",
                f"invalid arguments for {name}: {exc}",
            ) from exc
        if not isinstance(result, dict):
            raise RepoContextError(
                "INTERNAL_ERROR", f"{name} returned a non-object response"
            )
        return result

    def repo_overview(
        self,
        focus: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        return self._services.repo_overview(focus=focus, max_tokens=max_tokens)

    def search_repo(
        self,
        query: str,
        modes: list[str] | None = None,
        top_k: int = 20,
        path_prefix: str | None = None,
        languages: list[str] | None = None,
        symbol_kinds: list[str] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        return self._services.search_repo(
            query,
            modes=modes,
            top_k=top_k,
            path_prefix=path_prefix,
            languages=languages,
            symbol_kinds=symbol_kinds,
            max_tokens=max_tokens,
        )

    def get_symbol(
        self,
        symbol_or_path: str,
        include_source: bool = True,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        return self._services.get_symbol(
            symbol_or_path,
            include_source=include_source,
            max_tokens=max_tokens,
        )

    def trace_symbol(
        self,
        symbol: str,
        direction: str,
        depth: int = 1,
        relations: list[str] | None = None,
        max_nodes: int = 50,
    ) -> dict[str, Any]:
        return self._services.trace_symbol(
            symbol,
            direction=direction,
            depth=depth,
            relations=relations,
            max_nodes=max_nodes,
        )

    def analyze_impact(
        self,
        symbol_or_path: str,
        depth: int = 2,
        max_nodes: int = 100,
    ) -> dict[str, Any]:
        return self._services.analyze_impact(
            symbol_or_path, depth=depth, max_nodes=max_nodes
        )

    def related_tests(
        self,
        symbol_or_path: str,
        top_k: int = 20,
    ) -> dict[str, Any]:
        return self._services.related_tests(symbol_or_path, top_k=top_k)


def run_stdio(handler: RepoContextToolHandler) -> None:
    """Register the six tools with the optional SDK and block on stdio."""

    server = _create_mcp_server(handler)
    server.run(transport="stdio")


def _create_mcp_server(handler: RepoContextToolHandler) -> Any:
    """Build the official SDK server without starting a transport."""

    try:
        from mcp.server import MCPServer
    except ImportError as exc:  # pragma: no cover - depends on optional package
        raise McpUnavailableError(
            "The optional `mcp` package is not installed. Install the Repo Context "
            "MCP extra before running `atenex-context serve`."
        ) from exc

    server = MCPServer(
        "atenex-context",
        instructions=(
            "Read-only context for one fixed repository. Start with repo_overview, "
            "search for candidates, trace cross-module changes, then read exact "
            "source. Indexed summaries are navigation aids; source/tests/config "
            "are authoritative."
        ),
    )

    @server.tool()
    async def repo_overview(
        focus: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        """Return a compact, evidence-grounded map of the bound repository."""
        return _mcp_call(
            handler,
            "repo_overview",
            {"focus": focus, "max_tokens": max_tokens},
        )

    @server.tool()
    async def search_repo(
        query: str,
        modes: list[str] | None = None,
        top_k: int = 20,
        path_prefix: str | None = None,
        languages: list[str] | None = None,
        symbol_kinds: list[str] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        """Search lexical source and indexed symbols within the fixed root."""
        return _mcp_call(
            handler,
            "search_repo",
            {
                "query": query,
                "modes": modes,
                "top_k": top_k,
                "path_prefix": path_prefix,
                "languages": languages,
                "symbol_kinds": symbol_kinds,
                "max_tokens": max_tokens,
            },
        )

    @server.tool()
    async def get_symbol(
        symbol_or_path: str,
        include_source: bool = True,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        """Resolve one symbol or repository-relative source path."""
        return _mcp_call(
            handler,
            "get_symbol",
            {
                "symbol_or_path": symbol_or_path,
                "include_source": include_source,
                "max_tokens": max_tokens,
            },
        )

    @server.tool()
    async def trace_symbol(
        symbol: str,
        direction: str,
        depth: int = 1,
        relations: list[str] | None = None,
        max_nodes: int = 50,
    ) -> dict[str, Any]:
        """Traverse bounded static callers, callees, dependencies, or dependents."""
        return _mcp_call(
            handler,
            "trace_symbol",
            {
                "symbol": symbol,
                "direction": direction,
                "depth": depth,
                "relations": relations,
                "max_nodes": max_nodes,
            },
        )

    @server.tool()
    async def analyze_impact(
        symbol_or_path: str,
        depth: int = 2,
        max_nodes: int = 100,
    ) -> dict[str, Any]:
        """Return conservative static change-impact candidates and tests."""
        return _mcp_call(
            handler,
            "analyze_impact",
            {
                "symbol_or_path": symbol_or_path,
                "depth": depth,
                "max_nodes": max_nodes,
            },
        )

    @server.tool()
    async def related_tests(
        symbol_or_path: str,
        top_k: int = 20,
    ) -> dict[str, Any]:
        """Rank tests statically related to a symbol or source path."""
        return _mcp_call(
            handler,
            "related_tests",
            {"symbol_or_path": symbol_or_path, "top_k": top_k},
        )

    return server


def _mcp_call(
    handler: RepoContextToolHandler,
    name: str,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        return handler.call_tool(name, arguments)
    except RepoContextError as exc:
        # MCPServer turns adapter exceptions into protocol tool errors. Keep the
        # body machine-readable and free of absolute paths or source content.
        raise RuntimeError(json.dumps(exc.to_dict(), sort_keys=True)) from exc

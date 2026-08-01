---
name: atenex-repo-context
description: Navigate and understand large local repositories through the Atenex Repo Context MCP. Use for non-trivial codebase questions, cross-module flow tracing, symbol/dependency discovery, impact analysis, related-test selection, repository onboarding, or when an agent would otherwise scan the whole repo, README set, or project tracker to reconstruct context.
---

# Atenex Repo Context

Use Repo Context as a navigation layer. Treat the current source, tests and build
configuration as authority.

## Workflow

1. Call `repo_overview` with the user's real task as `focus` and a suitable token
   budget. Confirm `snapshot.stale=false` and inspect `focus_queries`.
2. Check whether the focused results cover every architectural stage implied by the
   task. For a cross-layer flow, look for the entry point, local state/persistence,
   transport, server boundary, orchestration/domain logic, durable persistence,
   authorization and tests when applicable.
3. Call `search_repo` with concise identifiers or missing stage concepts. Do not
   accept a broad overview as complete when a critical stage is absent.
4. Open the exact current source. Use `get_symbol` for definitions and local context;
   summaries and excerpts only select what to open.
5. For cross-module edits or claims, use `trace_symbol` or `analyze_impact`. Use
   `related_tests` to select checks, then execute those checks outside MCP.
6. Cite paths and lines from the source actually inspected. Separate observed facts,
   inferred relations and unresolved links.

## Retrieval quality checks

- Prefer results supported by several focused facets over a file matching one broad
  word. `focus_rrf` means the path appeared across decomposed task intents.
- Treat `fts5_any_term` as useful recall, not proof that a result belongs to the
  requested flow.
- Do not demand that one broad `search_repo` call reconstruct a complete architecture.
  Use the focused overview for task decomposition and narrow searches for direct
  evidence at each missing stage.
- If results are empty or noisy, search exact symbols, endpoints, errors, table names
  or stage-specific terms. Apply path/language filters when known.
- Persistent index warnings belong to `status`/`doctor`. Query diagnostics describe
  only the current response. Honor `RESULT_TRUNCATED` by requesting a narrower query.
- Never infer completeness from RepoMap alone. Read the exact source before changing
  code or making security claims.

## Authorization tracing

When analyzing identity or isolation, trace each value from authenticated context to
the final write. Check whether client-controlled actor fields are rejected or replaced
before ingestion and projection. Distinguish tenant, store, resource and actor
boundaries; one does not imply the others.

## Fallback

If MCP is unavailable, stale or still misses a stage, use targeted `rg`/`rg --files`,
then follow imports, calls and tests. Do not scan dependencies, build outputs,
sidecars or virtual environments.

For the full contract, consult
[`docs/mcp-tools.md`](../../../docs/mcp-tools.md) and
[`docs/architecture-repo-context.md`](../../../docs/architecture-repo-context.md)
only when the task needs protocol or implementation detail.

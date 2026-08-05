# ADR-0007: Require semantic retrieval in the MCP runtime

- **Status:** Implemented
- **Date:** 2026-08-03
- **Verification status:** fake contracts, focused tests and live two-repository MCP
  acceptance **Verified**

## Context

The lexical and structural index remains essential for evidence, symbols and graph
navigation, but running production MCP sessions without embeddings made retrieval
quality depend on an opt-in environment flag. The user-scoped Codex registration was
also pinned to the Atenex Nova path, so a session opened in another repository still
queried Atenex.

## Decision

Every composed Repo Context runtime includes local Ollama embeddings and a Qdrant
semantic index. Indexing must complete or reuse a generation-scoped semantic
projection before MCP starts. `search_repo` and focused `repo_overview` use hybrid
retrieval by default. Missing providers, models, completion sentinels or compatible
vectors fail explicitly with `SEMANTIC_UNAVAILABLE`; the runtime does not silently
publish a lexical-only MCP under the same contract.

SQLite remains the source/snapshot authority. Semantic records remain derived,
repository- and generation-scoped, and may never substitute fake vectors.

The launcher accepts `.` without an expected checkout only when it resolves to a Git
checkout. This supports one user-scoped Codex registration that follows the working
directory of each session. Project MCP configurations may still supply an expected
main checkout to restrict the launcher to that repository and its worktrees.

## Consequences

- Ollama, the configured embedding model and Qdrant are runtime prerequisites.
- First-time indexing takes longer because MCP waits for semantic ingestion.
- Reopening an unchanged generation reuses its compatible completion sentinel.
- Provider outages are visible startup/query failures, not implicit quality changes.
- Each repository root keeps an independent SQLite sidecar and Qdrant namespace.
- Explicit single-mode searches remain available for diagnostics and paired
  evaluation, while omitted modes select hybrid retrieval.

## Related

- [ADR-0002: SQLite core index](0002-sqlite-core-index.md)
- [ADR-0003: Atomic index generations](0003-atomic-index-generations.md)
- [ADR-0006: Previous optional semantic contract](0006-optional-semantic-retrieval.md)
- [MCP tools contract](../mcp-tools.md)

# ADR-0001: Pivot to a repository context product

- **Status:** Accepted
- **Date:** 2026-07-30
- **Implementation status:** **Implemented**; smoke acceptance **Verified**.

## Context

The current repository presents Atenex Nova primarily as a local-first
document-memory and RAG application. The approved v1 product direction instead
needs a small, reliable context engine for coding agents: index a local Git
worktree, expose grounded repository context over MCP, and make freshness and
evidence explicit.

Requiring the full document-RAG runtime would make the first useful repository
workflow depend on services and product concepts that are not necessary for
lexical, symbol, dependency, impact, and test discovery.

## Decision

The primary v1 product is `atenex-context`, a local-first repository context
engine with:

- a CLI for indexing, serving, status, and diagnostics;
- a SQLite core sidecar;
- a read-only MCP surface over `stdio`;
- source-grounded repository overview, search, symbol, trace, impact, and test
  tools;
- explicit generation, `HEAD`, worktree-fingerprint, staleness, truncation, and
  confidence metadata;
- semantic retrieval (made a required MCP-runtime projection by ADR-0007).

The existing document-RAG application is retained as a legacy/future bounded
context. Its code is not removed by this decision, but it is no longer the
primary v1 promise or a prerequisite for the repository-context core.

## Consequences

- Product documentation distinguishes the primary `atenex-context` contract
  from the maintained document-RAG application.
- The v1 success path can run locally without PostgreSQL, a worker fleet,
  Qdrant, Ollama, or an HTTP API.
- Existing RAG components may be reused later only behind explicit boundaries;
  they do not define repository-source authority.
- The decision alone is not evidence; the live snapshot and audit provide the
  implementation and verification record.

## Rejected alternatives

- **Keep document RAG as the v1 product promise:** does not match the approved
  coding-agent use case and retains unnecessary operational dependencies.
- **Delete the existing RAG code during the pivot:** creates avoidable migration
  risk and discards a viable bounded context.
- **Make a hosted multi-repository service first:** weakens local authority and
  expands identity, security, and operations beyond v1.

## Related

- [MCP tools contract](../mcp-tools.md)
- [Operations](../operations.md)

# ADR-0003: Publish indexes as atomic generations

- **Status:** Accepted
- **Date:** 2026-07-30
- **Implementation status:** **Implemented / Verified** for the core

## Context

An index contains several mutually dependent projections: files, hashes,
lexical records, symbols, relations, tests, and possibly semantic vectors.
Updating those projections in place can expose half-old, half-new results to an
MCP reader or destroy the last usable index when parsing fails.

## Decision

Every indexing attempt builds a new opaque staging generation. The active
generation is never mutated in place.

The indexer:

1. captures the repository source manifest, `HEAD`, file hashes, and worktree
   fingerprint;
2. builds all required core projections in staging, reusing unchanged derived
   records when safe;
3. validates core referential and manifest consistency;
4. confirms by a second scan, inside the transaction, that the worktree did not
   change during the attempt;
5. changes the generation state and active pointer in that transaction;
6. after core activation, builds or reuses semantic data for the same
   repository/generation and advertises MCP only after its completion sentinel.

Readers capture one active generation and verify the pointer again before
returning; an intervening activation makes the query fail closed and retry. A failed, interrupted, or
source-raced **core** staging attempt is never query-visible; the preceding
active generation remains intact. Failure of a semantic provider does not invalidate
an otherwise valid SQLite generation, but it fails indexing/serving and no partial
semantic data is advertised. The store retains the active generation and one inactive
generation.

## Consequences

- New requests see either the old complete generation or the new complete
  generation.
- Indexing can proceed while an MCP server reads.
- Incremental indexing saves computation but does not weaken publication
  atomicity.
- Storage temporarily includes staging and prior generations.
- SQLite `BEGIN IMMEDIATE` serializes writers per sidecar.
- Semantic data that is absent or mismatched cannot contaminate results or be served
  as a compatible MCP generation.

## Rejected alternatives

- **Update active rows in place:** exposes partial state and complicates
  recovery.
- **Delete then rebuild:** creates downtime and loses the last known-good
  context on failure.
- **Treat each file as independently current:** cannot give one coherent
  snapshot identity for graph and impact results.

## Related

- [ADR-0002: SQLite core index](0002-sqlite-core-index.md)
- [ADR-0005: Source and worktree authority](0005-source-worktree-authority.md)
- [Operations](../operations.md)

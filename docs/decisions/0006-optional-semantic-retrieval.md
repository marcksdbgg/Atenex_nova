# ADR-0006: Make semantic retrieval optional

- **Status:** Historical
- **Date:** 2026-07-30
- **Implementation status:** **Historical**; superseded by
  [ADR-0007](0007-required-semantic-retrieval.md)

This ADR records the previous runtime contract and no longer describes current
behavior.

## Context

Embeddings can improve conceptual search, but local model and vector-service
availability varies. Requiring Ollama and Qdrant for basic repository discovery
would make the core less portable and turn an enhancement outage into a total
context outage. Pretending that hash or random vectors are semantic would hide
quality failure.

## Decision

Lexical search, symbol lookup, static relations, impact analysis, and related
tests form the required SQLite core. Semantic retrieval is optional.

When configured:

- Ollama may generate local embeddings;
- Qdrant may store and search semantic vectors;
- semantic records carry the same generation and file-hash provenance as the
  SQLite generation;
- only semantic data aligned with the active generation may contribute to a
  result.

Default `search_repo` modes are `lexical` and `symbol`. A mixed-mode request
continues with core modes when semantic retrieval is unavailable and returns a
diagnostic. A semantic-only request also degrades to the core in this version,
removes `semantic` from the effective modes and returns
`SEMANTIC_UNAVAILABLE` as a diagnostic.

No implementation may substitute hash/random vectors or lexical scores and
label the result semantic.

## Consequences

- The v1 core works offline without Ollama or Qdrant.
- Semantic outages are visible but do not disable grounded structural tools.
- Operations must report provider health and generation alignment separately
  from core health.
- Semantic indexing follows an already active core generation and becomes ready
  only after a compatible persistent completion sentinel.
- Search quality may differ by deployment, so responses expose contributing
  modes and diagnostics.

## Rejected alternatives

- **Require semantic services:** increases setup and availability coupling for
  core use cases.
- **Silently fall back to fake embeddings:** misrepresents retrieval quality.
- **Allow vectors from another generation:** can return evidence for obsolete
  source.
- **Enable semantic mode by default:** makes default behavior depend on an
  optional provider.

## Related

- [ADR-0002: SQLite core index](0002-sqlite-core-index.md)
- [ADR-0003: Atomic index generations](0003-atomic-index-generations.md)
- [MCP tools contract](../mcp-tools.md)

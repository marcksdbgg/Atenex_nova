# ADR-0002: Use SQLite as the v1 core index

- **Status:** Accepted
- **Date:** 2026-07-30
- **Implementation status:** **Implemented / Verified**

## Context

Repository context needs durable manifests, file hashes, lexical search,
symbols, static relations, test links, diagnostics, and an atomic pointer to a
queryable snapshot. These records are local, derived, and naturally scoped to
one repository. Making PostgreSQL, Qdrant, or a distributed job system
mandatory would raise the setup and failure surface without improving the
single-worktree authority model.

## Decision

SQLite is the required v1 core index. By default it lives at:

```text
<repo>/.atenex/context/index.sqlite3
```

An operator may choose another directory with `--data-dir`; that directory
still contains `index.sqlite3` and does not become a source root.

SQLite stores repository/generation metadata, file manifests and hashes,
lexical/FTS data, symbols, source spans, static relations, diagnostics, and the
active-generation pointer. Related tests are derived from relations and bounded
lexical evidence at query time.

The sidecar is a disposable projection. Repository source and Git/worktree
state remain authoritative. SQLite serializes writers; readers use read-only
connections and services verify that the active generation did not change
during a call.

## Consequences

- The lexical and structural core has no external database dependency.
- Copying or editing the sidecar cannot redefine repository truth.
- Schema migrations and integrity checks must preserve the last known-good
  generation or require a rebuild from source.
- SQLite is not used as a distributed queue or multi-host coordination layer.
- Large-scale hosted operation, if added, may need another storage decision;
  that does not change the v1 local contract.

## Rejected alternatives

- **PostgreSQL as mandatory core:** unnecessary service overhead for one local
  worktree.
- **Qdrant as the only index:** does not replace transactional metadata,
  lexical/structural relations, or atomic generation activation.
- **Loose JSON files:** make concurrent reads, queryability, migrations, and
  atomic activation harder to guarantee.

## Related

- [ADR-0003: Atomic index generations](0003-atomic-index-generations.md)
- [ADR-0005: Source and worktree authority](0005-source-worktree-authority.md)
- [Operations](../operations.md)

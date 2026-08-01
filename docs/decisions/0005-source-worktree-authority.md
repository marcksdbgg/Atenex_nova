# ADR-0005: Treat repository source and worktree state as authority

- **Status:** Accepted
- **Date:** 2026-07-30
- **Implementation status:** **Implemented / Verified**

## Context

A repository index becomes dangerous when consumers cannot tell whether it
describes the checked-out code, a prior commit, or a mixture of indexed and
live files. Git `HEAD` alone is insufficient because staged, unstaged, deleted,
and eligible untracked files can materially change the code an agent will edit.

## Decision

The canonical repository root, Git metadata, and current worktree bytes define
source truth. The index is a derived snapshot.

Each active generation records:

- its opaque generation identity;
- captured Git `HEAD`, or `null` when unavailable;
- every included repository-relative path and content hash;
- a fingerprint of the complete indexed worktree source set.

The source set includes current bytes for tracked files and eligible untracked,
non-ignored files. It excludes `.git`, the active Atenex data directory,
ignored-untracked files, and any path or symlink resolving outside the root.

Every MCP response reports generation, captured `HEAD`, worktree fingerprint,
and `stale`. Source evidence uses relative paths, one-based inclusive line
spans, and content hashes. Before returning an excerpt, the server revalidates
the current file hash; it never labels obsolete indexed text as current source.

## Consequences

- Branch switches and local edits are visible as staleness even before commit.
- Consumers can associate cached context with one explicit generation.
- Stale derived relations may remain queryable only with clear diagnostics and
  reduced confidence; current source always wins a conflict.
- An index copied from another repository/worktree is not authoritative merely
  because its schema is readable.
- Indexing must abort activation if the source manifest changes during a build.

## Rejected alternatives

- **Use `HEAD` only:** misses local worktree state.
- **Use index contents as authority:** can present deleted or changed source as
  current.
- **Read arbitrary absolute paths on demand:** breaks the startup authority
  boundary.
- **Silently serve stale excerpts:** makes evidence and line spans unsafe for
  editing agents.

## Related

- [ADR-0003: Atomic index generations](0003-atomic-index-generations.md)
- [MCP tools contract](../mcp-tools.md)
- [Operations](../operations.md)

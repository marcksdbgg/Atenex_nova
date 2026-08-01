# ADR-0004: Keep the v1 MCP surface read-only

- **Status:** Accepted
- **Date:** 2026-07-30
- **Implementation status:** **Implemented / Verified** with an official-client
  `stdio` subprocess

## Context

Coding agents need focused repository evidence, but file mutation and command
execution have materially different security and authorization requirements.
Combining context retrieval with shell, Git, test, or editing tools would make
the repository server harder to trust and would duplicate capabilities already
owned by agent hosts.

## Decision

The v1 MCP server uses Python MCP SDK 2.x over `stdio`, is bound to exactly one
repository root at startup, and exposes only:

- `repo_overview`
- `search_repo`
- `get_symbol`
- `trace_symbol`
- `analyze_impact`
- `related_tests`

These tools may read the active index and bounded source evidence. They may not
write source or index data, execute processes, invoke tests or Git mutations,
select arbitrary roots, or open an HTTP listener.

Index construction remains a CLI action. It can be invoked explicitly by an
operator or by the local launcher before MCP protocol startup. The MCP server does
not auto-index as a tool side effect during a conversation.

## Consequences

- MCP clients can grant repository-context access without implicitly granting
  code execution or modification.
- The server's path boundary is fixed and auditable.
- Editing, testing, and Git operations remain the responsibility of the agent
  host or another explicitly authorized tool.
- Index freshness must be reported because a read-only server cannot repair a
  stale index during a request.
- A future write-capable or HTTP surface requires a separate versioned contract
  and threat-model decision.

## Rejected alternatives

- **Add a generic file-read tool:** broadens exfiltration surface beyond
  evidence-oriented context and duplicates host facilities.
- **Add shell/test tools:** conflates retrieval with execution authority.
- **Accept `repo` on every tool:** permits root confusion and arbitrary-source
  probing.
- **Expose HTTP in v1:** adds network authentication and deployment concerns
  before they are required.

## Related

- [MCP tools contract](../mcp-tools.md)
- [ADR-0005: Source and worktree authority](0005-source-worktree-authority.md)

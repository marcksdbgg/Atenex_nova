# Documentation Index

This directory separates the product contract, verified implementation evidence,
live architecture notes, and future plans. A document can describe more than one
state, but every non-trivial claim should make its state clear.

## Status Vocabulary

| Status | Meaning |
|---|---|
| **Implemented** | The described artifact or behavior exists in the current checkout. This does not by itself mean it was exercised in the current verification run. |
| **Verified** | The claim is backed by a named test, inspection, or runtime check recorded in the repository. |
| **Planned** | The item is an approved target or design contract that is not yet present in the current implementation. |
| **Historical** | The content records an earlier finding, decision, or result and must not be read as the live state without its later contrast. |

`Planned` is never evidence of implementation. When documents disagree, use the
precedence rules below instead of choosing the newest-looking statement.

## Sources of Truth

| Document | State | Role |
|---|---|---|
| [../README.md](../README.md) | **Implemented / Verified** | Live repository snapshot, quick start, commands, and current verification summary. |
| [baseline.md](baseline.md) | **Implemented** | Current product contract and rationale; optional/live-provider gates remain explicit. |
| [auditoria-completa.md](auditoria-completa.md) | **Implemented / Verified** | Canonical contrastive Repo Context ledger and pointer to the historical RAG audit. |
| [architecture-repo-context.md](architecture-repo-context.md) | **Implemented / Verified** | Delivered bounded context, deterministic core, CLI/MCP adapter and optional semantic boundary. |
| [indexing-and-storage.md](indexing-and-storage.md) | **Implemented / Verified** | Scanner, parser, SQLite/FTS5 and atomic generation contract as implemented. |
| [mcp-tools.md](mcp-tools.md) | **Implemented / Verified** | Six read-only tool schemas and common response/error contract. |
| [operations.md](operations.md) | **Implemented** | Installation, lifecycle commands, diagnostics and optional semantics. |
| [runbook-local.md](runbook-local.md) | **Implemented / Verified** | Exact startup, verification and safe shutdown procedure for this Linux station. |
| [evaluation-repo-context.md](evaluation-repo-context.md) | **Implemented / Planned** | Reproducible smoke runner and current evidence; larger held-out/release matrix remains planned. |
| [plan-repo-context-mcp.md](plan-repo-context-mcp.md) | **Implemented / Planned** | Original end-to-end plan plus execution ledger and remaining gates. |
| [architecture-backend.md](architecture-backend.md) | **Implemented** | Repo Context boundary plus historical RAG backend boundaries. |
| [architecture-frontend.md](architecture-frontend.md) | **Implemented / Historical scope** | RAG frontend snapshot; not revalidated in this delivery. |
| [api-endpoints.md](api-endpoints.md) | **Implemented / Historical scope** | RAG HTTP contract; previous test evidence is archived. |
| [jobs-and-workers.md](jobs-and-workers.md) | **Implemented / Historical scope** | RAG background job model, separate from Repo Context. |
| [turboquant-integration.md](turboquant-integration.md) | **Historical / Experimental** | Vector-quantization design from the RAG bounded context. |
| [plan-correccion-vecquant-operacional.md](plan-correccion-vecquant-operacional.md) | **Historical** | Redirect to the archived operational plan. |

## Reading Paths

### Understand the current Atenex application

1. Read [../README.md](../README.md).
2. Read [architecture-backend.md](architecture-backend.md) or
   [architecture-frontend.md](architecture-frontend.md), depending on the area.
3. Read [api-endpoints.md](api-endpoints.md) and
   [jobs-and-workers.md](jobs-and-workers.md) for public and asynchronous
   contracts.
4. Check [auditoria-completa.md](auditoria-completa.md) before treating a
   baseline claim as delivered.

### Change backend behavior

1. Read [baseline.md](baseline.md).
2. Read [auditoria-completa.md](auditoria-completa.md).
3. Read [architecture-backend.md](architecture-backend.md) and
   [jobs-and-workers.md](jobs-and-workers.md).
4. If retrieval quantization or candidate indexes are involved, also read
   [turboquant-integration.md](turboquant-integration.md).

### Work on Repo Context

1. Read [../README.md](../README.md) for installation and verified state.
2. Use [runbook-local.md](runbook-local.md) for the exact commands on this PC.
3. Read [architecture-repo-context.md](architecture-repo-context.md) and
   [indexing-and-storage.md](indexing-and-storage.md) before changing core code.
4. Read [mcp-tools.md](mcp-tools.md) before changing a public response.
5. Use [plan-repo-context-mcp.md](plan-repo-context-mcp.md) and
   [evaluation-repo-context.md](evaluation-repo-context.md) to distinguish the
   delivered core from the pending full release matrix.
6. Agent clients use the canonical project workflow in
   `../.agents/skills/atenex-repo-context/SKILL.md`; Claude loads the thin adapter in
   `../.claude/skills/atenex-repo-context/SKILL.md`.

## Precedence and Drift Rules

1. The product contract in [baseline.md](baseline.md) explains what Atenex Nova
   is meant to become.
2. The contrastive ledger in
   [auditoria-completa.md](auditoria-completa.md) determines whether a baseline
   claim is **Implemented**, **Verified**, still **Planned**, or only
   **Historical**.
3. [../README.md](../README.md) is the operational snapshot for setup and the
   latest recorded checks.
4. The generated OpenAPI schema is authoritative for live HTTP routes;
   [api-endpoints.md](api-endpoints.md) must remain synchronized with it.
5. Architecture documents describe delivered boundaries plus explicitly marked
   extensions. Plan documents record both completed work and future gates but do
   not prove verification by themselves.

When a change affects product behavior, architecture, or a declared gap, update
the live snapshot and the canonical audit together. Change `Verified` claims only
alongside reproducible evidence.

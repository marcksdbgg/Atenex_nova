# MCP Tools Contract

> **Status:** **Implemented / Verified** tool contract for `atenex-context` v1.
>
> The official MCP 2.0 client has initialized the server as a real `stdio`
> subprocess, discovered all six schemas and executed `repo_overview`
> successfully on the local Claude runtime.

## Purpose

`atenex-context` exposes a local repository index to coding agents through a
small, read-only Model Context Protocol (MCP) surface. The server is bound to one
repository root at startup. Tools return compact, source-grounded context; they
do not edit the repository, execute commands, or select a different root.

The v1 server contract is:

- Python MCP SDK 2.x;
- `stdio` transport;
- one server process bound to one canonical repository root;
- a SQLite core index at `.atenex/context/index.sqlite3` by default;
- source-relative paths and explicit line spans in every source reference;
- snapshot metadata on every response;
- required hybrid retrieval backed by a compatible Ollama/Qdrant projection for
  the active SQLite generation.

HTTP, remote multi-repository serving, and write-capable tools are outside the
v1 contract.

## Starting the server

The command is:

```text
atenex-context serve --repo PATH [--data-dir PATH] [--transport stdio]
```

`--repo` is required and fixes the authority boundary for the lifetime of the
process. `--transport` accepts only `stdio` in v1. Tool arguments never accept a
repository path, absolute source path, command, shell fragment, or transport
override.

Before serving useful results, the repository must have an active index
generation produced by:

```text
atenex-context index --repo PATH [--data-dir PATH] [--full]
```

See [operations.md](operations.md) for indexing, staleness, and recovery.
The checked-in Claude/Cursor configuration calls the local launcher documented
there; it verifies the resolved Git checkout/worktree identity, refreshes
incrementally, and only then starts the read-only server. Relative roots bind to the
MCP process working directory and must resolve to a Git checkout; project-scoped
configurations may additionally restrict them to an expected main checkout and its
worktrees. Indexing is still outside the MCP tool surface.

## Common response envelope

Every successful tool call returns one JSON object with the following shape.
Tool-specific content lives under `data`.

```json
{
  "repo": {
    "name": "Atenex_nova",
    "root": "."
  },
  "snapshot": {
    "generation": "opaque-generation-id",
    "head": "full-git-object-id-or-null",
    "worktree_fingerprint": "64-lowercase-hex-digits",
    "stale": false
  },
  "data": {},
  "truncated": false,
  "token_estimate": 812,
  "diagnostics": []
}
```

The fields are normative:

- `repo.name` is a display name derived from the bound repository.
- `repo.root` is always `"."`. Source paths are relative to this root; the
  server does not disclose or accept alternate source roots through tools.
- `snapshot.generation` is the opaque identifier of the active, committed index
  generation used by the call.
- `snapshot.head` is the Git `HEAD` object id captured by that generation, or
  `null` for a repository without a resolvable commit.
- `snapshot.worktree_fingerprint` identifies the source/worktree state captured
  by the generation.
- `snapshot.stale` is `true` when the current authoritative repository state no
  longer matches the active generation.
- `data` contains the tool-specific payload.
- `truncated` is `true` when the response omitted lower-ranked records, source,
  graph nodes, or detail to honor a budget or an explicit limit.
- `token_estimate` is the server's estimate of the serialized response size in
  model tokens. It is an estimate, not an accounting guarantee.
- `diagnostics` is an array of structured notices that affect this call. An
  empty array means no known degradation was observed for the returned result.
  Persistent scanner/parser diagnostics are summarized by `repo_overview` as
  `data.summary.index_diagnostics` and inspected in full with CLI `status` or
  `doctor`; query responses do not replay that global backlog.

`max_tokens` is an output budget, not an instruction to generate prose. The server
compacts lower-priority collections and redundant rendered views before removing the
minimum useful set of ranked results. It then bounds source excerpts. It must not cut
JSON or a source line in the middle. The fixed response envelope may make the
serialized result slightly larger than `max_tokens`; the server sets
`truncated=true` and emits `RESULT_TRUNCATED` whenever budget pressure removed data.

### Source evidence

Tool results that make a claim about source include evidence records:

```json
{
  "path": "src/example.py",
  "line_start": 12,
  "line_end": 28,
  "content_hash": "64-lowercase-hex-digits",
  "confidence": 0.94,
  "basis": ["definition", "import", "call"]
}
```

- `path` uses `/` separators and is relative to the bound repository root.
- Lines are one-based and inclusive.
- `content_hash` is the hash of the authoritative file content associated with
  the evidence.
- `confidence` is a number from `0.0` to `1.0`. It describes evidence quality,
  not a probability that generated prose is true.
- `basis` names the observed signals supporting the result.

The worktree is authoritative. Before returning a source excerpt, the server
re-reads the in-scope file and verifies its content hash. If the file no longer
matches the indexed generation, the server must not present an indexed excerpt
as current source. It returns `snapshot.stale=true`, omits or clearly marks the
affected excerpt, lowers confidence for derived claims, and adds a
`FILE_CHANGED_SINCE_INDEX` diagnostic.

### Diagnostics

A diagnostic has this shape:

```json
{
  "code": "SEMANTIC_UNAVAILABLE",
  "severity": "warning",
  "message": "Semantic search was requested but is not configured.",
  "path": null
}
```

`severity` is one of `info`, `warning`, or `error`. Stable v1 diagnostic codes
include:

- `INDEX_STALE`
- `FILE_CHANGED_SINCE_INDEX`
- `RESULT_TRUNCATED`
- `SEMANTIC_UNAVAILABLE`
- `SYMBOL_AMBIGUOUS`
- `RELATION_INFERRED`
- `FRESHNESS_CHECK_FAILED`
- `REPOSITORY_BINDING_MISMATCH`
- `NO_RESULTS`

Diagnostics are part of the result, not log text. Implementations may add new
codes, but clients must treat unknown codes as informational unless
`severity="error"`.

### Tool errors

Invalid calls and calls that cannot produce their primary result return an MCP
tool error with a machine-readable JSON body:

```json
{
  "error": {
    "code": "INVALID_ARGUMENT",
    "message": "depth must be between 1 and the server limit",
    "details": {}
  }
}
```

Stable v1 error codes are:

- `INVALID_ARGUMENT`
- `INDEX_UNAVAILABLE`
- `NOT_FOUND`
- `AMBIGUOUS`
- `OUTSIDE_REPOSITORY`
- `SEMANTIC_UNAVAILABLE`
- `INTERNAL_ERROR`

A stale index is normally a successful, explicitly stale response, not a tool
error. A semantic request whose compatible generation is unavailable fails with
`SEMANTIC_UNAVAILABLE`. The server also refuses to start without a compatible
completed projection.

## Search modes and relation vocabulary

`search_repo.modes` accepts:

- `lexical`: exact and token-based matches over indexed source and metadata;
- `symbol`: names, qualified names, definitions, and structural references;
- `semantic`: embedding-based retrieval fused with lexical candidates.

When `modes` is omitted, the runtime uses `lexical`, `symbol`, and `semantic`.
Individual modes remain selectable for diagnostics and paired evaluation.

Relationship-oriented tools use this normalized vocabulary when the relevant
language adapter can establish the relation:

- `defines`
- `references`
- `imports`
- `calls`
- `extends`
- `inherits`
- `implements`
- `contains`
- `tests`
- `exports`
- `configured_by`
- `declares_table`
- `alters_table`
- `reads_table`
- `writes_table`

Language adapters may expose additional relation labels. Unknown requested
labels are invalid; unavailable-but-valid relations produce no edges plus a
diagnostic rather than fabricated links.

## `repo_overview`

Returns a compact map of the repository grounded in the active generation.

### Input

```text
repo_overview(
  focus?: string,
  max_tokens: integer = 4000
)
```

- `focus` optionally prioritizes paths, modules, concepts, or symbols relevant
  to a task. It is a ranking hint and does not change the repository boundary.
- `max_tokens` limits output detail.

`search_repo` ranks direct lexical, symbol, path and semantic evidence for
the supplied terms. It does not claim to reconstruct every stage of an architectural
flow from a broad phrase. Use `repo_overview(focus=...)` for cross-layer orientation,
then use narrower searches for stages that are absent or need exact evidence.

### Output

`data` contains:

- repository language and file summaries;
- principal directories/modules and their source evidence;
- high-signal entry points and symbols;
- dependency or test landmarks when established by indexed relations;
- the applied `focus`, when supplied;
- `focus_queries`, the bounded deterministic intent decomposition used for the task;
- `focus_results`, fused by repository-relative path with RRF evidence;
- the focused RepoMap, ranked with shallower decay and subsystem-level diversity.

To keep the orientation call useful inside the default budget, focused results omit
source bodies (their hashes, spans, snippets and evidence remain), and languages,
directories, landmarks and focus hits use fixed top-k bounds. `repo_map.truncated`
continues to state explicitly when lower-ranked candidates were omitted.

Cross-layer focus terms such as offline operation, flow, persistence and isolation
activate small auditable query facets. A path found by several facets exposes
`match_reason=focus_rrf:*` and `score_components.focus_facets`; this is still a
navigation signal, not proof of behavior.

The tool summarizes indexed facts. It must not infer product behavior solely
from filenames or generate an architectural narrative without evidence.

## `search_repo`

Searches indexed source with one or more explicit retrieval modes.

### Input

```text
search_repo(
  query: string,
  modes?: string[],
  top_k: integer = 20,
  path_prefix?: string,
  languages?: string[],
  symbol_kinds?: string[],
  max_tokens: integer = 4000
)
```

- `query` is required and must not be blank. Natural-language queries are accepted:
  the lexical core first tries all useful terms and supplements that strict pass with
  a deterministic relaxed plan for cross-file flows. Prefix matching and bounded Spanish/English code
  synonyms bridge prose with identifiers without requiring semantic services.
- `modes` uses the vocabulary above.
- `top_k` is the maximum number of ranked results before token compaction.
- `path_prefix` is a normalized repository-relative prefix. Absolute paths,
  parent traversal, and paths resolving outside the root are rejected.
- `languages` filters by normalized indexed language identifiers.
- `symbol_kinds` filters by kinds reported by language adapters, such as
  `module`, `class`, `function`, `method`, `type`, `variable`, or `test`.
- `max_tokens` limits output detail.

### Output

Each result includes:

- a stable result id within the generation;
- kind and display label;
- repository-relative path and inclusive line span;
- score and contributing modes;
- content hash;
- a bounded source excerpt when it still matches the authoritative worktree;
- evidence confidence and basis.

Excerpts are navigation aids and intentionally short. Clients must open the exact
current source before making a code claim or edit. `match_reason` and score components
expose whether a candidate came from strict FTS, relaxed FTS, literal, symbol, or
semantic evidence.

Scores are meaningful only for ordering within one response. They are not
required to be comparable across queries, modes, or generations.

If semantic mode is requested but unavailable or belongs to a different generation,
the server returns `SEMANTIC_UNAVAILABLE`. It must not use hash vectors or label
lexical fallback as semantic.

## `get_symbol`

Resolves a symbol or repository-relative path and returns its definition and
local context.

### Input

```text
get_symbol(
  symbol_or_path: string,
  include_source: boolean = true,
  max_tokens: integer = 4000
)
```

Resolution order is:

1. an exact normalized repository-relative path;
2. an exact qualified symbol name;
3. an exact unqualified symbol name;
4. ranked candidates for an otherwise ambiguous name.

An ambiguous request does not silently choose one definition. It returns an
`AMBIGUOUS` error with bounded candidates, or a successful candidate list
marked by `SYMBOL_AMBIGUOUS` when the implementation can provide useful
disambiguation without pretending a unique match.

### Output

For a symbol, `data` contains its qualified name, kind, signature when known,
definition span, containing symbols, selected direct relations, and evidence.
For a path, it contains indexed file metadata and its top-level symbols.

When `include_source=false`, source text is omitted but spans and hashes remain.
When `include_source=true`, the source excerpt is included only after the
authority/hash check described above.

## `trace_symbol`

Traverses known static relations from or to a symbol.

### Input

```text
trace_symbol(
  symbol: string,
  direction: "callers" | "callees" | "dependencies" | "dependents" | "both",
  depth: integer = 1,
  relations?: string[],
  max_nodes: integer = 50
)
```

- `symbol` must resolve uniquely.
- `direction` is required and controls graph orientation.
- `both` unions incoming and outgoing evidence at every traversed node; it is useful
  for orientation and remains subject to the same depth and node limits.
- `depth` is the maximum traversal depth, with `1` meaning direct neighbors.
- `relations` optionally restricts traversal to the normalized relation
  vocabulary.
- `max_nodes` bounds the returned graph.

### Output

`data` contains:

- the resolved root symbol;
- nodes with definitions and evidence;
- directed edges with relation, source span, and confidence;
- traversal depth reached;
- omitted-node and omitted-edge counts when truncated.

`callers` and `callees` prioritize `calls`; `dependencies` and `dependents`
include relevant imports, references, inheritance, implementation, and
containment relations unless `relations` narrows them. Results are static
evidence, not proof of runtime reachability. Inferred or adapter-limited edges
must carry confidence and diagnostics.

## `analyze_impact`

Finds likely consequences of changing a symbol or path.

### Input

```text
analyze_impact(
  symbol_or_path: string,
  depth: integer = 2,
  max_nodes: integer = 100
)
```

### Output

`data` contains:

- the resolved target;
- directly affected definitions/files;
- transitive dependents up to `depth`;
- related tests known to the index;
- affected relation types;
- confidence and evidence for every impact path;
- unknowns or language-adapter gaps that limit the analysis.

An exact indexed path is a valid target even for structural/lexical languages with
no extracted symbols. Exact paths are resolved by their indexed `path`, not by a
symbol-name search, and the target file itself is always included in
`affected_files`.

This tool reports static impact candidates. It does not claim that a test will
fail, execute a test suite, inspect runtime telemetry, or modify files.

## `related_tests`

Returns tests statically related to a symbol or path.

### Input

```text
related_tests(
  symbol_or_path: string,
  top_k: integer = 20
)
```

### Output

Each result includes:

- test path and test symbol when known;
- inclusive line span and content hash;
- relation basis, for example direct reference, import, naming convention, or
  co-location;
- confidence;
- the production symbol/path to which the evidence was linked.

Direct references rank above naming and co-location heuristics. A missing result
means “no related test was established by the active index,” not “no test
exists.”

## Security and side-effect boundary

All six v1 tools are read-only. In particular, the MCP server provides no tool
to:

- create, edit, rename, or delete files;
- stage or commit Git changes;
- run tests, builds, shells, package managers, or arbitrary executables;
- invoke repository hooks;
- rebuild or mutate the index;
- change the bound repository or data directory;
- read paths outside the canonical repository root;
- start HTTP listeners.

Index construction is an operator or startup-launcher action through the CLI,
outside the MCP tool surface. Required Ollama and Qdrant adapters perform the protocol calls
needed for semantic indexing/search, but they do not expand source authority or
grant agents write/execute capabilities.

## Versioning

This is the v1 contract. Backward-compatible additions may add optional fields,
diagnostics, relation labels, or symbol kinds. Removing a tool, renaming a
field, changing a default, adding side effects, or changing stale/error
semantics requires a new contract version and an architecture decision.

Related decisions:

- [ADR-0001: Pivot to a repository context product](decisions/0001-repository-context-product.md)
- [ADR-0003: Atomic index generations](decisions/0003-atomic-index-generations.md)
- [ADR-0004: Read-only MCP surface](decisions/0004-read-only-mcp-surface.md)
- [ADR-0005: Source and worktree authority](decisions/0005-source-worktree-authority.md)
- [ADR-0006: Previous optional semantic contract](decisions/0006-optional-semantic-retrieval.md)
- [ADR-0007: Required semantic retrieval](decisions/0007-required-semantic-retrieval.md)

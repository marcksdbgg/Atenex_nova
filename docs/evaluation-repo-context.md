# Repository Context: Evaluation Protocol

> **Current state (2026-07-31):** the versioned smoke runner and thirteen cases are
> **Implemented / Verified**. The larger reviewer-authored held-out set,
> performance repetitions, live hybrid comparison, JUnit/HTML artifacts and full
> release gates described later are **Planned**.

## Implemented smoke acceptance

The executable runner is `backend/scripts/evaluate_repo_context.py`; its manifest is
`backend/tests/repo_context/goldens/acceptance.json`. It invokes all six application
services, can reindex multiple repositories with the same release code, emits stable
JSON and exits `0` only when every case hits a required relative path without a stale
snapshot. Besides hit/Recall/MRR, each case records result count, response-token
estimate, diagnostic count and truncation; the summary counts zero-result queries,
diagnostics and truncated responses.

```bash
cd backend
python scripts/evaluate_repo_context.py \
  --manifest tests/repo_context/goldens/acceptance.json \
  --repo atenex-nova=.. \
  --repo client-romero=/ruta/local/client-romero \
  --data-dir atenex-nova=/tmp/atenex-context/atenex \
  --data-dir client-romero=/tmp/atenex-context/client \
  --reindex --full --top-k 20 \
  --output /tmp/atenex-context/report.json
```

Resultado verificado:

| Métrica | Resultado |
|---|---:|
| Casos | 13 |
| Hits | 13 |
| Fallos/stale | 0 |
| Hit rate | 1.0 |
| Recall@20 medio | 1.0 |
| MRR | 0.90384615 |
| Consultas sin resultados | 0 |
| Diagnósticos de respuesta | 5 |
| Respuestas truncadas | 3 |
| Tokens de respuesta medios | 4924.53846154 |

Atenex produjo 362 archivos, 3508 símbolos y 14532 relaciones.
`client-romero` produjo 816 archivos, 11997 símbolos y 37049 relaciones. La
ejecución usó el core sin semántica y un caché local con gramáticas Tree-sitter
precargadas. El reporte guarda rutas relativas requeridas y rankings, pero redacta
el root y la ruta del sidecar y no incluye fragmentos fuente.

### Regresión de la conversación Claude sobre `client-romero`

Estado: **Implemented / Verified**. La consulta literal usada para reconstruir el
flujo fue incorporada al manifest como caso no sensible:

```text
outbox enqueue sale offline sync
```

Antes de la corrección, sobre el índice real y con `max_tokens=4000`, la búsqueda
devolvía cero resultados, 46 diagnósticos globales repetidos y una respuesta estimada
en 3316 tokens. La causa era una intersección FTS obligatoria entre todos los términos;
el presupuesto se consumía además con warnings de parser no relacionados con la
consulta.

Después de la primera corrección, el run aislado llegó a ubicar seis archivos del
recorrido dentro de los primeros 20 resultados. Esa observación reveló un criterio
de aceptación incorrecto: una búsqueda cuyos términos nombran outbox y sync local no
debe prometer inferir por sí sola toda la arquitectura del servidor. El contrato
vigente exige que `search_repo` recupere directamente `salesStore.ts`, `outbox.ts` y
`syncService.ts`; la prueba MCP real los mantuvo en 20 resultados con 3874/4000
tokens. La cobertura transversal se mide por separado con `repo_overview`.

El segundo caso reproduce el foco en español para `repo_overview`; alcanza Recall@20
1.0 y mantiene cliente, proyección y procesamiento entre sus resultados pertinentes.
El tercer caso usa literalmente el foco observado en la prueba de Claude:

```text
offline sale flow from POS/caja to API persistence, tenant and store isolation
```

La aplicación lo descompone en cinco consultas auditables: el foco original más
facetas de offline/outbox, recorrido HTTP, persistencia y aislamiento. Fusiona paths
por RRF y entrega pesos de foco al RepoMap con diversidad por subsistema. En el
subprocess MCP real, los seis archivos críticos (`salesStore.ts`, `outbox.ts`,
`syncService.ts`, `routes/sync.ts`, `processor.ts` y `projector.ts`) quedaron dentro
de los primeros siete paths tanto en `focus_results` como en RepoMap. La respuesta
fue fresca, declaró su único truncamiento y consumió 5979/6000 tokens.

La primera prueba subprocess del launcher tardó 45.910 s en inicializar porque
publicaba otra generación aunque el snapshot no hubiera cambiado. Después de añadir
el no-op por identidad completa de snapshot, una segunda ejecución sobre el mismo
checkout inicializó MCP en 1.087 s (aproximadamente 42 veces más rápido). La prueba
actual, con seis herramientas descubiertas y cinco llamadas que incluyen el overview
transversal, terminó en 7.314 s. Un cambio real o `--full` sigue forzando la
publicación atómica normal.

El smoke set es una prueba de usabilidad y generalidad inicial; no se presenta como
un benchmark estadísticamente robusto.

## Purpose

This document defines the reproducible acceptance protocol for the repository-context
index described in [indexing-and-storage.md](indexing-and-storage.md). It is separate
from the current document-RAG evaluation framework: existing keyword-based scorers
are useful smoke tests, but they are not sufficient evidence for source-code
retrieval quality.

The first evaluation release uses two corpora:

- **Atenex Nova**, a public, version-pinned corpus that exercises Python, TypeScript,
  TSX, Markdown, JSON, YAML/TOML-style configuration, CSS, shell, and SQL-adjacent
  repository content; and
- **client-romero**, a private, version-pinned corpus that exercises production
  cross-file flows, SQL, access guards, tests, and Java fixtures.

El claim smoke exige resultados de ambos corpus. Los claims de release completos
exigirán además el protocolo planificado que sigue.

## Planned full reproducibility manifest

The full release runner will emit a machine-readable manifest containing:

```text
run_id
golden_schema_version
golden_set_name/version/digest
repository_id
base_commit
snapshot_id
dirty
generation_id
index_schema_version
parser_bundle_versions
core_configuration_digest
semantic_fingerprint?
retrieval_mode
tokenizer/revision
token_budget
operating_system
cpu / logical cores / RAM
warm_or_cold
random_seeds
started_at / completed_at
```

The evaluated snapshot is immutable for the duration of a run. The runner rejects a
golden set whose pinned repository identity or snapshot does not match, unless the
case is explicitly a dirty-worktree mutation scenario.

Reports contain result IDs, ranks, paths, line ranges, digests, scores, and aggregate
metrics. They do not embed private source text.

## Planned held-out golden-set schema

The larger goldens will use stable, reviewer-authored relevance judgments rather than
`expected_keywords` alone. Each case contains:

```text
id
corpus
split
category
query
filters?
gold_spans[]:
  relative_path
  symbol_or_locator?
  start_line? / end_line?
  relevance: 1..3
required_groups[]?
forbidden_paths[]?
expected_mode: core | hybrid | either
token_budget: 8000
notes
```

`required_groups` expresses multi-file tasks: the case is complete only when the
packed context covers at least one valid span from every required group. Exact cases
have one unambiguous gold target and are scored with stricter rules.

Line ranges are reviewed against the pinned snapshot. A nearby span in the correct
symbol can receive graded relevance for nDCG but cannot satisfy an exact-gold gate
unless it overlaps the reviewed target. Renames or line movement require a new
golden-set version, not silent relabeling during a run.

At least two maintainers review each new or changed judgment. Disagreements are
resolved before the test split is used as a release gate. Development and test
splits are reported separately; test labels are not used for tuning rank weights.

## Security of the private corpus

The client-romero repository, source excerpts, queries that reveal confidential
business data, and private absolute paths must not be committed to this repository.
Its golden pack is a local encrypted or access-controlled evaluation input. The
committed project may contain only the schema, case IDs, and non-sensitive evaluation
instructions.

El smoke manifest versiona únicamente nombres técnicos y rutas relativas no
confidenciales aprobadas; no versiona el root, source text ni el sidecar externo.
Una futura evaluación privada puede sustituirlas por digests y resolvers locales.
Ninguna evaluación semántica puede enviar contenido de `client-romero` a un
proveedor remoto.

## Planned Atenex Nova held-out coverage

The Atenex set is pinned to a reviewed commit and contains, at minimum, these case
families:

| Family | Representative target |
|---|---|
| Exact symbol | `create_app` in `backend/atenex_nova/main.py` |
| Exact policy | `dense_goes_to_qdrant` and its profile behavior |
| Class lookup | `PurePyTurboQuantCandidateIndex` |
| Cross-file worker flow | job registration in `workers/main.py`, dispatch in `workers/runner.py`, and the relevant handler |
| Retrieval architecture | routing/orchestration plus BM25 and candidate-index adapters |
| Persistence boundary | a domain repository protocol and its SQL implementation |
| Frontend-to-API trace | route/page call, API client method, DTO/schema, and backend router |
| Configuration | a setting and every behaviorally relevant consumer |
| Tests for implementation | an implementation span together with the tests that constrain it |
| Documentation/config lookup | Markdown heading, JSON key/path, TOML section, CSS selector/custom property, or shell function |
| Negative/exclusion | ignored, binary, secret-like, too-large, and traversal/symlink fixtures |

The exact paths and line spans live in the versioned golden file, not in this
descriptive table. Cases cover each v1 AST language present in the fixture set and
each structured-lexical format listed in
[indexing-and-storage.md](indexing-and-storage.md).

The Atenex suite also includes controlled worktree mutations:

- one staged edit;
- a second unstaged edit to the same file, proving working-tree bytes win;
- an eligible untracked source file;
- a tracked deletion;
- a file modified during capture, which must retry or fail without publication; and
- a one-file incremental change followed by a deletion, proving no stale result
  remains.

These mutations are created in a disposable copy or temporary worktree. The
evaluator never changes the developer's checkout.

## Planned client-romero held-out coverage

The private set includes at least the following reviewer-labeled tasks:

| Case ID / topic | Required evidence |
|---|---|
| `romero-sort-category-names` | `sortCategoryNames`, its behaviorally relevant implementation context, and its tests |
| `romero-sync-project-event-flow` | the cross-file chain `syncRoutes -> processSyncBatch -> projectEvent` and the tests that constrain the flow |
| `romero-require-store-access` | the `requireStoreAccess` guard, its callers/registration point, and its tests |
| `romero-store-active-sql` | the exact `STORE_ACTIVE_SQL` declaration and relevant use |
| `romero-store-product-price-sql` | the `store_product_price` SQL definition/query and the code path that uses it |
| `romero-java-yape-fixtures` | the Java Yape fixtures and the production/test symbols they exercise |

Maintainers assign exact relative paths and line spans locally. The cross-file cases
use `required_groups`, so retrieving only the best-known symbol cannot pass the task.
At least one exact, one call/data-flow, one SQL, one access-control, and one
implementation-plus-tests case must remain in the held-out split.

## Planned full test matrix

The evaluation runner executes:

1. **SQLite core / cold**: exercise scanner, parsers and atomic storage directly from
   an empty data root; this is component evidence, not a servable MCP runtime.
2. **Hybrid / cold**: build SQLite plus the required Ollama/Qdrant projection from an
   empty data root.
3. **Hybrid / warm**: repeated default queries against the published generation.
4. **Hybrid / incremental**: add, edit, rename where supported, and delete a controlled
   file.
5. **Signal ablations**: run the same quality cases with explicit lexical, semantic
   and hybrid modes for paired comparison.
6. **Semantic outage**: build/query with an adapter unavailable and verify explicit
   `SEMANTIC_UNAVAILABLE` plus refusal to serve MCP.
7. **Dirty snapshot**: staged, unstaged, untracked, deleted, and capture-race cases.
8. **Atomic publication**: concurrent query load while a successful and a failing
   generation are built.
9. **Security**: path traversal, symlink escape, binary, large, secret, malicious
   filename, and prompt-injection-like content fixtures.
10. **Non-Git scanner component**: equivalent fixture copied without `.git`; the
    Git-only session launcher must reject it.

Core and hybrid use the same query text, gold judgments, filters, token budget, and
deduplication policy. This makes their comparison paired rather than anecdotal.

## Planned full metrics

### Parsing and coverage

- `eligible_files`: non-excluded files offered to the appropriate v1 parser.
- `parser_eligible_files`: eligible files in any AST or structured-lexical v1 format.
- `parser_success_rate`: successfully parsed / parser-eligible.
- `ast_eligible_files`: eligible Python, TS/TSX/JS, SQL, and Java files.
- `ast_parsed_rate`: AST-parsed / AST-eligible.
- `lexical_fallback_rate` and fallback counts by language/reason.
- structured-lexical coverage by supported format.
- excluded counts by reason, with zero excluded content in reports.

A file using lexical fallback remains searchable, but is not counted as AST parsed.

### Retrieval

For each query, compute:

- Recall@5, Recall@10, and **Recall@20** over binary-relevant gold spans;
- reciprocal rank and mean reciprocal rank (MRR);
- nDCG@20 using reviewer relevance grades;
- exact-gold success for unambiguous path/symbol/span cases;
- required-group coverage for cross-file cases;
- correct-file-in-context, which is true when the context packed within 8,000 tokens
  contains a relevant span from the required file or every required group; and
- forbidden/excluded hit count.

Deduplication is performed by gold span before scoring so overlapping child and
parent chunks do not inflate recall. A returned result belongs to a gold span when
its file matches and its byte/line range overlaps the reviewed range; a symbol match
alone is not enough when the golden includes a range.

Metrics are reported per corpus, category, language, and retrieval mode, plus macro
averages. Query-weighted micro averages are informative only and cannot satisfy a
gate.

### Snapshot and atomicity

- snapshot manifest/content agreement;
- result provenance agreement (`snapshot_id` and `generation_id`);
- dirty-state capture correctness;
- stale-hit count after delete;
- mixed-generation response count;
- failed-build pointer changes; and
- old/new generation availability during publication.

These are exact invariants, not percentage quality metrics.

### Performance and footprint

On the declared reference machine, report:

- cold full-build wall time and files/second;
- one-file incremental build time and reuse percentage;
- warm query latency p50/p95/p99 for core and hybrid;
- peak resident memory during build and query;
- core and semantic artifact bytes, plus bytes/source-byte ratio; and
- context packing time and returned model-token count.

Each latency suite has at least two warmups and 30 measured queries. Build suites run
at least five times when practical and report the median plus the worst observed run.
Background load and power mode are recorded. Performance regressions are compared on
the same machine and snapshot.

### End-to-end usefulness

An agent or answer-model evaluation may additionally measure citation precision,
supported-answer rate, and task completion. It must pin the model/prompt and preserve
the retrieval report. These metrics are diagnostic in v1; a generative score cannot
compensate for a failed retrieval, security, or atomicity gate.

## Planned full release gates

All gates are evaluated on the held-out split unless stated otherwise.

### Blocking correctness and security gates

- **100% exact-gold success** for unambiguous exact path, symbol, configuration key,
  and SQL declaration cases in both corpora.
- **100% provenance consistency**: every result and packed span matches the run's
  pinned snapshot and generation.
- **0 mixed-generation responses**, **0 stale hits after deletion**, and **0 changes
  to the active-generation pointer after a failed build**.
- Dirty snapshots include the expected staged, unstaged, untracked, and deleted
  states exactly; capture races retry or fail closed.
- **0 forbidden-path, secret, binary, oversized, traversal, or symlink-escape content
  in any index, semantic request, result, report, or log**.
- The full core suite passes with external services and network unavailable.
- Semantic outage produces an explicit core fallback and no partial semantic
  generation.

Any failure above blocks release regardless of aggregate retrieval scores.

### Parsing gate

- At least **95% of parser-eligible files are parsed successfully**, per corpus and
  globally. AST coverage is also reported separately so structured formats cannot
  conceal an AST regression.
- Every remaining parser-eligible file has a bounded diagnostic and is retrievable
  through lexical fallback.
- Structured-lexical fixtures for Markdown, JSON/JSONC, YAML, TOML, CSS, and shell
  produce the expected locators and spans.

### Retrieval gates

- Recall@20 is **at least 0.85** per corpus and globally.
- MRR is **at least 0.65** per corpus and globally.
- At least **80% of tasks contain the correct file or every required file group
  within the 8,000-token packed context**, per corpus and globally.
- Hybrid retrieval is **globally non-inferior** to core: its paired macro Recall@20,
  MRR, nDCG@20, and correct-file-in-context rate may not decrease beyond the
  registered tolerance of 0.01, and it may not fail an exact-gold case passed by core.

The non-inferiority comparison publishes paired per-case deltas and a bootstrap 95%
confidence interval. If the sample is too small for a stable interval, the absolute
0.01 tolerance and zero exact regressions are the binding rules.

### Performance regression gate

Until representative absolute budgets are calibrated on both repositories, the
checked-in passing baseline is the reference:

- warm core query p95 may not regress by more than 20%;
- one-file incremental wall time may not regress by more than 25%;
- peak build RSS and core artifact size may not regress by more than 20%; and
- incremental reuse must remain at least 95% when exactly one small source file
  changes.

The report still records absolute values. Changing the reference hardware,
repository snapshot, tokenizer, parser bundle, or index schema creates a new baseline
rather than silently comparing incompatible runs.

## Planned gate output

La evolución planificada del runner producirá:

- `manifest.json` with provenance and environment;
- `cases.jsonl` with ranked judgments and per-case metrics;
- `summary.json` with per-corpus/category/mode aggregates and gate decisions;
- `junit.xml` for blocking correctness/security cases; and
- an optional local HTML report that resolves authorized source spans.

The process exits non-zero if any blocking gate fails. A waived gate remains visible
as `waived` with owner, reason, and expiry; it is never rewritten as `passed`.

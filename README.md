# Atenex Nova

**Next-Generation Local-First Document Memory & RAG Platform**

<p align="center">
  <em>A document memory system with multiple retrieval engines — not another chatbot with vectors.</em>
</p>

<p align="center">
  <a href="#architecture">Architecture</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#api-surface">API</a> ·
  <a href="#evaluation-framework">Evaluation</a> ·
  <a href="#why-open-source">Why Open Source</a>
</p>

---

## Overview

Atenex Nova is an **open-source, local-first platform** for loading documents, building structured document memory, and answering questions with real grounding. It represents a second-generation approach to Retrieval-Augmented Generation that moves beyond the "single vector index + LLM" paradigm.

Instead of relying on one retrieval mechanism, Atenex Nova coordinates **multiple specialized retrieval engines** — dense, sparse, propositional, summary-based, and visual — with intelligent query routing that selects the optimal strategy based on question type. Every answer is verified before delivery, with full citation traceability back to source document spans.

### What Makes This Different

| Traditional RAG | Atenex Nova |
|---|---|
| Single vector index | 5-index architecture: dense + sparse + proposition + summary + visual |
| One-size-fits-all retrieval | Query routing: 6 specialized modes (exact, factual, multi-hop, global, argumentative, visual) |
| Text-only chunking | Structural document parsing with Docling — headings, tables, captions, reading order |
| No verification | Two-step verification + grounding score + regeneration before answering |
| Approximate citations | Span-level citation binding to real document positions |
| Cloud-dependent | Local-first: everything runs on-prem with optional cloud decoupling |

### Core Capabilities

- **Hybrid retrieval** — EmbeddingGemma dense vectors + local BM25 sparse + reranking fusion
- **Multi-layer memory** — Chunks, propositions, summaries, and visual pages stored independently
- **Query routing** — Automatic classification selects optimal retrieval mode per question type
- **Propositional graph** — Claims, definitions, and relationships for multi-hop reasoning
- **Visual retrieval** — ColPali-style page-level retrieval for scanned documents and complex layouts
- **Answer verification** — Deterministic check + LLM second pass + grounding score before delivery
- **Evidence traceability** — Every citation resolves to a real document span with page, bbox, and heading path
- **Evaluation framework** — Dataset management, golden sets, and per-mode benchmarking
- **Full observability** — Pipeline audit trails, job state tracking, dependency health checks

---

## Architecture

Atenex Nova follows a **Modular Monolith + Hexagonal Architecture** pattern, designed for maintainability, testability, and clear separation of concerns.

```
presentation  →  application  →  domain  →  infrastructure  →  workers  →  evaluation
   (APIs)         (services)    (entities)    (adapters)       (jobs)      (metrics)
```

| Layer | Responsibility | Key Components |
|---|---|---|
| `presentation` | FastAPI routers, DTOs, HTTP responses | 10 routers, OpenAPI-contracted |
| `application` | Services, orchestrators, policies, use cases | Retrieval & answer orchestration, query routing, context packing |
| `domain` | Entities, value objects, domain contracts, rules | 15+ entity types, typed identifiers, metadata schemas |
| `infrastructure` | DB, parsing, embeddings, vector store, LLM, visual | PostgreSQL/SQLite, Qdrant, Docling, EmbeddingGemma, Gemma 4, ColPali |
| `workers` | Async job processing | Ingestion, memory enrichment, visual indexing |
| `evaluation` | Datasets, runs, scoring, regression | Answer & retrieval scorers, dataset manager |
| `shared` | Configuration, logging, exceptions, observability | Settings, structured logging, pipeline audit |

### Technology Stack

| Component | Technology |
|---|---|
| **Backend** | Python 3.11+, FastAPI, SQLAlchemy async, SQLModel, Pydantic v2 |
| **Relational DB** | PostgreSQL (production) / SQLite (development) |
| **Vector Store** | Qdrant (dense + sparse + multi-vector) |
| **Document Parser** | Docling (structural parsing: headings, tables, captions, OCR, reading order) |
| **LLM Generation** | Gemma 4 via Ollama or llama.cpp (E2B / E4B / 26B profiles) |
| **Embeddings** | EmbeddingGemma (256d / 384d / 768d via Matryoshka Representation Learning) |
| **Visual Retrieval** | ColPali-style visual page retrieval |
| **Frontend** | React 18, TypeScript, Vite |

### Hardware Profiles

| Profile | RAM | Generator | Embeddings | Capabilities |
|---|---|---|---|---|
| **Lite** | 8 GB | Gemma 4 E2B | EmbeddingGemma 256d | Core retrieval, no persistent visual index |
| **Standard** | 16 GB | Gemma 4 E4B | EmbeddingGemma 384d | Full propositional graph, optional visual |
| **Advanced** | 32 GB+ | Gemma 4 26B/31B | EmbeddingGemma 768d | All indices active, full DRIFT/global mode |

---

## Document Ingestion Pipeline

Atenex Nova prioritizes **document understanding over fast vectorization**. The ingestion pipeline transforms raw documents into a rich, multi-layered memory structure:

```
Document → Structural Parsing → Normalization → Multi-Layer Segmentation
         → Embeddings → Memory Enrichment → Visual Indexing → Ready
```

### Pipeline Stages

1. **Reception** — Upload, local import, or folder watch. Metadata, checksum, version, and process traces generated.
2. **Structural Parsing** — Docling extracts headings, paragraphs, lists, tables, captions, figures, footnotes, and reading order.
3. **Semantic Normalization** — Language detection, whitespace cleanup, numeral/date/code preservation, caption↔figure linking, cell↔table↔header linking.
4. **Multi-Layer Segmentation** — Four views of each document:
   - **Structural spans** — Paragraphs, sections, table cells, captions
   - **Retrieval chunks** — Structure-aware chunks with context (400-800 token budget)
   - **Propositions/claims** — Atomic assertions extracted from spans
   - **Hierarchical summaries** — Section, document, and collection-level summaries
5. **Embedding & Indexing** — EmbeddingGemma encodes chunks, propositions, and summaries into Qdrant. Local BM25 complements for keywords, proper names, dates, and codes.
6. **Memory Enrichment** — Worker extracts propositions, generates summaries, builds heuristic relationships for multi-hop reasoning.
7. **Visual Indexing** — Complex/scanned documents get visual page representations for layout-aware retrieval.

### Document State Machine

```
registered → parsed → normalized → segmented → embedded → indexed → ready
                                                    ↓
                                                  failed (with recovery)
```

---

## Query Pipeline

Questions flow through a multi-stage routing and synthesis pipeline:

```
Question → Normalization → Classification → Routing → Multi-Engine Retrieval
         → Fusion + Rerank → Evidence Pack → Synthesis → Verification → Answer
```

### Query Modes

| Mode | Use Case | Retrieval Strategy |
|---|---|---|
| `exact` | Codes, proper names, dates, IDs | Sparse-dominant + dense auxiliary |
| `factual_local` | Point questions about few passages | Dense+sparse hybrid + reranking |
| `multi_hop` | Connecting dispersed pieces | Hybrid seeds + propositional graph traversal |
| `global` | Corpus-wide overview questions | Summary index + thematic communities + DRIFT |
| `argumentative` | Conflicting positions across sources | Hybrid retrieval + evidence clustering + support/attack structure |
| `visual` | Tables, complex layouts, scans | ColPali visual index + parser text spans |

### What Happens Under the Hood

- Detects query language and intent
- Resolves permitted document scope (tenant-aware)
- Combines sparse, dense, summary, and visual retrieval
- Reranks and deduplicates evidence
- Builds evidence pack with token budget management
- Selects synthesis plan (direct, hierarchical, global, argument, visual-grounded)
- Generates response with Gemma 4
- Verifies grounding and citations before persisting output

### Answer Output

Every persisted answer includes:

- Response text
- Verification verdict
- Grounding score
- Citations with span-level binding
- Associated evidence
- Routing mode and reason
- Verification metadata
- Markdown and PDF export support

---

## Frontend Workspace

The frontend is an **operational workspace**, not a demo UI. It provides full visibility into the document memory system.

### Routes

| Route | Purpose |
|---|---|
| `/` | Dashboard |
| `/collections` | Collection management, document upload, rebuild |
| `/query` | Query workspace with conversation thread, answer panel, citation sidebar |
| `/observability` | Pipeline audit trails, evidence inspection |
| `/evaluation` | Dataset management, evaluation runs, metrics |
| `/jobs` | Job state monitoring |

### Query Workspace Features

- Conversation thread with history
- Answer panel with synthesis output
- Citation sidebar with span-level navigation
- Evidence cards with source document context
- Document tree inspector
- Page viewer for visual evidence
- Query history and memory rail

---

## API Surface

Full documentation at [docs/api-endpoints.md](docs/api-endpoints.md). Contract-validated against FastAPI OpenAPI via `test_openapi_documentation_contract.py`.

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Service health status |
| GET | `/health/dependencies` | Runtime dependency health (LLM, Qdrant, embeddings, Docling, visual) |
| POST | `/collections` | Create collection |
| GET | `/collections` | List collections |
| GET | `/collections/{id}/documents` | Document inventory with pagination |
| POST | `/collections/{id}/documents` | Upload document |
| POST | `/collections/{id}/documents/import` | Register local path |
| POST | `/collections/{id}/documents/import-folder` | Import local folder |
| POST | `/collections/{id}/rebuild` | Queue collection rebuild |
| GET | `/documents/{id}/structure` | Document tree |
| GET | `/documents/{id}/nodes` | Structural nodes |
| GET | `/documents/{id}/chunks` | Persisted chunks |
| GET | `/documents/{id}/propositions` | Persisted propositions |
| GET | `/documents/{id}/pages/{page}` | Visual page asset |
| GET | `/queries/history` | Query history |
| POST | `/queries/search` | Retrieval without answer synthesis |
| POST | `/queries/answer` | Retrieval + synthesis + verification |
| GET | `/answers/{id}` | Persisted answer |
| GET | `/answers/{id}/export/markdown` | Export answer as Markdown |
| GET | `/answers/{id}/export/pdf` | Export answer as PDF |
| GET | `/jobs` | List jobs |
| GET | `/observability/audit` | Pipeline audit trail |
| GET | `/observability/documents/{id}/evidence` | Document evidence inspection |
| GET | `/evaluation/datasets` | Evaluation datasets |
| POST | `/evaluation/runs` | Launch evaluation run |

---

## Evaluation Framework

Atenex Nova includes a built-in evaluation system for measuring retrieval and answer quality:

- **Dataset management** — JSON-based golden sets with questions, expected answers, and evaluation criteria
- **Per-mode benchmarking** — Separate evaluation for each query routing mode
- **Retrieval scoring** — Precision, recall, and MRR for retrieval quality
- **Answer scoring** — Groundedness, faithfulness, and answer relevance metrics
- **Regression comparison** — Track quality changes across pipeline iterations

---

## Quick Start

### Prerequisites

- Python >= 3.11
- Node.js >= 20 LTS
- Docker Desktop (for Qdrant and PostgreSQL)
- Git

### 1. Clone

```bash
git clone <repository-url>
cd Atenex_nova
```

### 2. Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -e ".[dev]"
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

### 4. Local Services

```bash
# Qdrant
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
  -v qdrant_storage:/qdrant/storage qdrant/qdrant

# LLM runtime: Ollama + Gemma 4
ollama serve
ollama pull gemma4:e4b

# Alternative: llama.cpp
llama-server -m models/gemma-4-e4b.gguf --port 8080 --ctx-size 8192
```

### 5. Verify Dependencies

```bash
curl http://127.0.0.1:8000/health/dependencies
# Response should show llm.available=true when Ollama + gemma4:e4b are ready
```

### 6. Run

```bash
# API server
cd backend
uvicorn atenex_nova.main:app --reload --port 8000

# Worker (async job processing)
cd backend
python -m atenex_nova.workers.main

# Frontend
cd frontend
npm run dev
```

---

## Project Structure

```
Atenex_nova/
├── AGENTS.md                          # Development conventions
├── README.md                          # This file
├── backend/
│   ├── pyproject.toml                 # Package definition, dev dependencies
│   ├── ruff.toml                      # Linting configuration
│   ├── atenex_nova/
│   │   ├── main.py                    # FastAPI application entry point
│   │   ├── dependencies.py            # Dependency injection wiring
│   │   ├── presentation/              # API routers, DTOs, schemas
│   │   ├── application/               # Services, orchestrators, policies
│   │   ├── domain/                    # Entities, value objects, contracts
│   │   ├── infrastructure/            # DB, embeddings, LLM, Qdrant, parsing, visual
│   │   ├── workers/                   # Async job definitions and runner
│   │   ├── evaluation/                # Datasets, scorers, regression
│   │   └── shared/                    # Config, logging, exceptions, observability
│   └── tests/
│       ├── unit/                      # Unit tests (43+ passing)
│       ├── integration/               # Integration tests (pipeline validation)
│       └── e2e/                       # End-to-end tests (API surface, ingestion, chat)
├── design-system/                     # UI design tokens and page specs
├── docs/                              # Architecture, API, gap inventory
├── frontend/                          # React/TypeScript/Vite workspace
├── prompts/                           # Versioned prompt suite per synthesis mode
└── storage/                           # Local blob storage (uploads, visual pages)
```

---

## Why Open Source

Atenex Nova is being developed as open source because we believe that **document memory and retrieval infrastructure should be transparent, auditable, and under user control**. The current RAG landscape is dominated by opaque cloud services that lock organizations into vendor-specific retrieval patterns.

This project demonstrates that a **local-first, multi-engine retrieval architecture** can outperform single-index approaches while maintaining complete data sovereignty. By open-sourcing Atenex Nova, we aim to:

1. **Advance open RAG research** — Provide a reference implementation of hybrid retrieval, query routing, proposition graphs, and verification pipelines that others can study, extend, and benchmark against.
2. **Enable privacy-preserving AI** — Give organizations a path to powerful document understanding without sending sensitive data to external APIs.
3. **Lower the barrier to production RAG** — Show that sophisticated retrieval doesn't require massive infrastructure; the same architecture scales from 8 GB laptops to 32 GB+ workstations.
4. **Build a community around document understanding** — Contribute to the open-source ecosystem with structural parsing pipelines, multi-layer memory patterns, and evaluation frameworks that benefit all RAG practitioners.

### Active Maintenance

This project is under **active development** with a clear roadmap and rigorous quality standards:

- **27 commits** across the project lifecycle
- **10 FastAPI routers** with OpenAPI contract validation
- **19 test files** spanning unit, integration, and e2e coverage
- **15+ domain entities** with typed identifiers and value objects
- **Modular hexagonal architecture** with clear layer boundaries
- **Comprehensive documentation** — architecture specs, API contracts, gap inventory, design system

### How API Credits Will Be Used

API credits from the Codex for Open Source program would directly accelerate essential open-source maintenance and development:

- **Automated evaluation pipelines** — Run golden set benchmarks across all 6 query modes to validate retrieval and answer quality improvements
- **Code quality automation** — Power automated linting, type checking, and refactoring suggestions across the 223-file codebase
- **Documentation generation** — Auto-generate API documentation, architecture diagrams, and contributor guides from the codebase
- **Pull request review assistance** — Use Codex to review incoming PRs against the hexagonal architecture contract and domain boundaries
- **Test generation and maintenance** — Expand unit and integration test coverage, particularly for edge cases in retrieval routing and citation binding
- **Release workflow automation** — Automate changelog generation, version bumping, and release notes for consistent project releases

---

## Verified Workspace Status

This README reflects the current repository checkout, not just the product vision.

| Check | Status | Command |
|---|---|---|
| OpenAPI/docs contract | 1 passed | `pytest tests/unit/test_openapi_documentation_contract.py -q` |
| Backend unit tests | 1 failed, 43 passed | `pytest tests/unit -q` |
| Frontend build | pending fix | `npm run build` |
| Frontend lint | pending fix | `npm run lint` |
| Backend `ruff` | 6 issues | `ruff check .` |
| Backend `mypy` | 5 errors | `mypy atenex_nova` |
| Integration / e2e | present | Tests exist, depend on local runtimes |

The canonical gap inventory is [docs/final-gap-inventory.md](docs/final-gap-inventory.md).

---

## Known Gaps

The repository is substantially complete but not yet 100% closed against the baseline. The canonical gap inventory is [docs/final-gap-inventory.md](docs/final-gap-inventory.md). Current open items include:

- One unit test failure in `AnswerOrchestrator` (empty citations)
- Frontend build and lint fixes
- Backend `ruff` and `mypy` cleanup
- Hardened sparse persisted index
- Stronger measurable reranking
- Strict mode visual policy
- Formal evaluation with golden sets per mode
- Complete e2e validation with active local runtimes

---

## Related Documentation

- [Final Gap Inventory](docs/final-gap-inventory.md)
- [Product Baseline](docs/baseline.md)
- [Backend Architecture](docs/architecture-backend.md)
- [Frontend Architecture](docs/architecture-frontend.md)
- [API Endpoints](docs/api-endpoints.md)
- [Jobs and Workers](docs/jobs-and-workers.md)
- [Design System](design-system/atenex-nova/MASTER.md)
- [AGENTS.md](AGENTS.md)

---

## License

Pending definition.

---

<p align="center">
  <strong>Atenex Nova</strong> — Next-generation local-first document memory platform
</p>
<p align="center">
  <em>Open source. Local-first. Multi-engine retrieval. Verified answers.</em>
</p>
